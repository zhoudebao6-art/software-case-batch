"""Generate technical checks and full-timeline image evidence; never grants visual approval."""
from pathlib import Path
import argparse, hashlib, json, math, re, shutil, subprocess
from fractions import Fraction
from PIL import Image, ImageDraw, ImageFont

def digest(path):
    h=hashlib.sha256()
    with open(path,'rb') as f:
        for b in iter(lambda:f.read(1024*1024),b''):h.update(b)
    return h.hexdigest()

def media_tool(name,tool_paths=None):
    config=Path(__file__).resolve().parents[1]/'config.json'
    configured=tool_paths.get(name) if tool_paths is not None else (json.loads(config.read_text(encoding='utf-8')).get('runtime',{}).get(name) if config.exists() else None)
    found=configured or shutil.which(name)
    if not found or not Path(found).is_file():raise RuntimeError(f'Missing {name}; update config.json runtime paths')
    return str(Path(found).resolve())

def command(args,tool_paths=None):
    if args[0] in {'ffmpeg','ffprobe'}:args=[media_tool(args[0],tool_paths),*args[1:]]
    return subprocess.run(args,check=True,capture_output=True,text=True,encoding='utf-8',errors='replace',timeout=300)

def generate(video,output,sample_fps=5,min_seconds=8,max_seconds=12,tool_paths=None):
    def run(args):return command(args,tool_paths)
    video=Path(video).resolve(strict=True);output=Path(output).resolve()
    if sample_fps<1 or sample_fps>30:raise ValueError('sample_fps must be between 1 and 30')
    if min_seconds<=0 or max_seconds<min_seconds:raise ValueError('invalid duration range')
    if output.exists() and any(output.iterdir()):raise ValueError('Use a new empty output directory; stale evidence cannot be reused')
    meta=json.loads(run(['ffprobe','-v','error','-count_frames','-show_streams','-show_format','-of','json',str(video)]).stdout)
    v=next(s for s in meta['streams'] if s.get('codec_type')=='video')
    duration=float(meta['format']['duration'])
    if not math.isfinite(duration) or duration<=0 or duration>120:raise ValueError('Expected a clip of at most 120 seconds')
    fps=float(Fraction(v.get('avg_frame_rate','0/1')))
    frame_count=int(v['nb_read_frames'])
    # Decode every frame. Decoding success is a technical check only.
    decode=run(['ffmpeg','-v','error','-i',str(video),'-map','0:v:0','-f','null','-'])
    output.mkdir(parents=True,exist_ok=True);frames_dir=output/'frames';frames_dir.mkdir()
    source_sha=digest(video)
    run(['ffmpeg','-v','error','-i',str(video),'-map','0:v:0','-vf',f'fps={sample_fps}','-pix_fmt','yuvj420p','-q:v','2',str(frames_dir/'frame-%05d.jpg')])
    frames=[]
    for i,path in enumerate(sorted(frames_dir.glob('frame-*.jpg'))):
        frames.append({'file':str(path),'seconds':round(i/sample_fps,4),'sha256':digest(path),'type':'uniform_sample'})
    for label,t,n in [('first',0,0),('last',max(0,duration-1/max(fps,1)),frame_count-1)]:
        path=frames_dir/f'{label}.jpg'
        run(['ffmpeg','-v','error','-i',str(video),'-vf',f'select=eq(n\\,{n})','-frames:v','1','-fps_mode','vfr','-pix_fmt','yuvj420p','-q:v','2',str(path)])
        if not path.exists():raise ValueError(f'Missing required {label} frame')
        frames.append({'file':str(path),'seconds':round(t,4),'source_frame_index':n,'sha256':digest(path),'type':label})
    if not frames:raise ValueError('No frames were extracted')
    samples=[x for x in frames if x['type']=='uniform_sample']
    if not samples or len(samples)<math.floor(duration*sample_fps)-1:raise ValueError('Incomplete timeline sampling')
    frames.sort(key=lambda x:x['seconds'])
    font_path=Path('C:/Windows/Fonts/arial.ttf')
    font=ImageFont.truetype(str(font_path),22) if font_path.exists() else ImageFont.load_default()
    contacts=[]
    for group in range(0,len(frames),12):
        subset=frames[group:group+12];width=1920;height=math.ceil(len(subset)/3)*396
        board=Image.new('RGB',(width,height),'white');draw=ImageDraw.Draw(board)
        for i,item in enumerate(subset):
            im=Image.open(item['file']).convert('RGB');im.thumbnail((630,354))
            x=(i%3)*640;y=(i//3)*396
            board.paste(im,(x+(640-im.width)//2,y+34))
            draw.text((x+10,y+4),f"{item['seconds']:.3f}s  {item['type']}",font=font,fill='black')
        target=output/f'contact-{group//12+1:03d}.jpg';board.save(target,quality=94)
        contacts.append({'file':str(target),'sha256':digest(target),'first_seconds':subset[0]['seconds'],'last_seconds':subset[-1]['seconds'],
                         'frame_files':[item['file'] for item in subset]})
    detection=run(['ffmpeg','-hide_banner','-i',str(video),'-vf','blackdetect=d=0.03:pix_th=0.10,freezedetect=n=-55dB:d=1.0','-an','-f','null','-'])
    signals=[line for line in detection.stderr.splitlines() if ('black_start:' in line or 'freeze_' in line)]
    report={'schema_version':1,'video':str(video),'video_sha256':source_sha,'duration':duration,'source_frame_count':frame_count,
            'width':v['width'],'height':v['height'],'fps':fps,'codec':v['codec_name'],'pixel_format':v.get('pix_fmt'),
            'duration_in_requested_range':min_seconds<=duration<=max_seconds,
            'decode_ok':not bool(decode.stderr.strip()),'decode_diagnostics':decode.stderr,
            'sample_fps':sample_fps,'sampling_note':'Uniform resampled timeline; timestamps approximate source presentation times. Review all contacts and inspect full-resolution frames. This is not a claim that every original frame was viewed.',
            'automatic_signals':signals,'signal_note':'Black and freeze detections are prompts for inspection, not automatic quality verdicts; static reading scenes may be appropriate.',
            'frames':frames,'contact_sheets':contacts,'visual_review_status':'pending_astra'}
    if digest(video)!=source_sha:raise ValueError('Video changed while evidence was being generated')
    (output/'timeline.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    return report

def main():
    p=argparse.ArgumentParser();p.add_argument('video',type=Path);p.add_argument('output',type=Path);p.add_argument('--sample-fps',type=int,default=5);p.add_argument('--min-seconds',type=float,default=8);p.add_argument('--max-seconds',type=float,default=12);a=p.parse_args()
    r=generate(a.video,a.output,a.sample_fps,a.min_seconds,a.max_seconds)
    print(json.dumps({k:r[k] for k in ('duration','width','height','fps','codec','decode_ok','duration_in_requested_range','visual_review_status')},ensure_ascii=False))
    print(f'frames={len(r["frames"])} contacts={len(r["contact_sheets"])} timeline={a.output / "timeline.json"}')
if __name__=='__main__':main()
