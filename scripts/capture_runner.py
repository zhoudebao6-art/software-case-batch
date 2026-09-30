"""Trusted, bounded recording of a case-owned local web app from a JSON plan.

Does not launch/stop a case service, execute case scripts, change permissions,
or grant visual acceptance. A parent must hold the recording slot for record().
"""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import time
from urllib.error import URLError
from urllib.parse import urlsplit
from urllib.request import urlopen


class CaptureError(ValueError):
    pass


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def save(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2)+'\n', encoding='utf-8')


def local_file(case, relative):
    if not isinstance(relative, str) or not relative or Path(relative).is_absolute() or '..' in Path(relative).parts:
        raise CaptureError('Unsafe case artifact path')
    target=case/relative
    if target.is_symlink() or target.resolve() != target.absolute() or not target.is_file():
        raise CaptureError(f'Artifact missing or linked: {relative}')
    return target


def scene_dependencies(case, plan, *, check_hashes=True):
    """Schema 2 binds only real inputs to the two recorded pages."""
    modules = plan.get('modules')
    if not isinstance(modules, list) or len(modules) != 2 or any(not isinstance(m, dict) for m in modules):
        raise CaptureError('Output-focused recording requires two prepared modules')
    routes = [m.get('route') for m in modules]
    if any(not isinstance(r, str) or not r.startswith('/') or r.startswith('//') or
           any(c in r for c in ('?', '#', '\\', '\n', '\r')) for r in routes):
        raise CaptureError('Invalid module route')
    if len(set(routes)) != 2:
        raise CaptureError('Recorded module routes must be distinct')
    bound = {}
    for field in ('application_files', 'scene_data_files'):
        files = plan.get(field)
        if not isinstance(files, dict) or not files or len(files) > 200:
            raise CaptureError(f'Bind nonempty {field} for the recorded pages')
        for name, expected in files.items():
            if not isinstance(expected, str) or len(expected) != 64 or any(c not in '0123456789abcdef' for c in expected):
                raise CaptureError(f'Invalid SHA256 in {field}: {name}')
            actual = digest(local_file(case, name))
            if check_hashes and actual != expected:
                raise CaptureError(f'Recording input changed after preparation: {name}')
            bound[name] = actual
    return bound


def validate_plan(case, case_id, ports):
    case=Path(case).resolve(strict=True)
    filename=local_file(case, 'evidence/capture-plan.json')
    try:
        plan=json.loads(filename.read_text(encoding='utf-8'))
    except ValueError as exc:
        raise CaptureError('Invalid capture plan JSON') from exc
    if not isinstance(plan,dict):
        raise CaptureError('Capture plan must be an object')
    if plan.get('schema_version') not in (1, 2) or plan.get('case_id') != case_id:
        raise CaptureError('Capture plan schema or case identity differs')
    try:
        url=urlsplit(plan.get('base_url',''))
        port=url.port
    except (ValueError,TypeError) as exc:
        raise CaptureError('Invalid capture base URL') from exc
    if (url.scheme!='http' or url.hostname!='127.0.0.1' or port not in ports or
            url.username or url.password or url.path or url.query or url.fragment):
        raise CaptureError('Capture URL must use an assigned local case port and no credentials/path')
    if not isinstance(plan.get('version'),str) or not plan['version'].strip():
        raise CaptureError('Missing frozen service version')
    def route(value):
        return isinstance(value,str) and value.startswith('/') and not value.startswith('//') and not any(c in value for c in ('?', '#', '\\','\n','\r'))
    if not route(plan.get('health_path')):
        raise CaptureError('Invalid relative health endpoint')
    modules=plan.get('modules')
    if not isinstance(modules,list) or not 1 <= len(modules) <= 2:
        raise CaptureError('Select one or two representative modules')
    for index, module in enumerate(modules):
        if not isinstance(module,dict) or not route(module.get('route')):
            raise CaptureError('Invalid module route')
        if any(not isinstance(module.get(k),str) or not module[k].strip() for k in ('name','heading')):
            raise CaptureError('Module name and exact H1 required')
        selectors=module.get('ready_selectors')
        if not isinstance(selectors,list) or not 1 <= len(selectors) <= 8 or any(not isinstance(s,str) or not s.strip() or len(s)>500 for s in selectors):
            raise CaptureError('Bounded visible ready selectors required')
        if index and (not isinstance(module.get('enter_selector'),str) or not module['enter_selector'].strip() or len(module['enter_selector'])>500):
            raise CaptureError('Second module must use a real navigation control')
    files=plan.get('application_files')
    if not isinstance(files,dict) or not files or len(files)>200:
        raise CaptureError('Bind application source hashes to this capture plan')
    for name, expected in files.items():
        if digest(local_file(case,name)) != expected:
            raise CaptureError(f'Application changed after preparation: {name}')
    if plan['schema_version'] == 2:
        scene_dependencies(case, plan)
    return plan


def service_ready(case, case_id, plan, timeout=90):
    deadline=time.monotonic()+timeout
    last='No response'
    while True:
        try:
            with urlopen(plan['base_url']+plan['health_path'],timeout=min(5,max(.1,deadline-time.monotonic()))) as response:
                health=json.load(response)
            if (not isinstance(health,dict) or health.get('case_id')!=case_id or health.get('version')!=plan['version'] or
                    Path(str(health.get('workspace',''))).resolve()!=Path(case).resolve()):
                raise CaptureError('Running service case/workspace/version differs; do not reuse or restart it blindly')
            return health
        except (URLError,TimeoutError,ConnectionError) as exc:
            last=str(exc)
        except ValueError as exc:
            if isinstance(exc,CaptureError):
                raise
            raise CaptureError('Service health endpoint did not return valid JSON') from exc
        if time.monotonic()>=deadline:
            raise CaptureError('Service is not ready; no restart was attempted: '+last)
        time.sleep(min(.5,max(0,deadline-time.monotonic())))


def run_command(command, cwd, timeout=180):
    result=subprocess.run(command,cwd=cwd,capture_output=True,text=True,encoding='utf-8',errors='replace',timeout=timeout)
    if result.returncode:
        raise CaptureError(result.stderr[-3000:] or result.stdout[-3000:] or f'Command exit {result.returncode}')
    return result


def stable_start(raw, reference, output, ffmpeg, raw_duration, target):
    """Find real consecutive video frames matching the ready browser screenshot."""
    from PIL import Image, ImageChops, ImageStat
    span=min(5.0,raw_duration-target)
    if span < .2:
        raise CaptureError('Raw recording lacks a stable crop margin')
    folder=output/'start-match';folder.mkdir()
    run_command([ffmpeg,'-v','error','-i',str(raw),'-t',str(span),'-vf','fps=10,scale=320:180','-q:v','2',str(folder/'%04d.jpg')],output)
    desired=Image.open(reference).convert('RGB').resize((320,180))
    streak=0;matches=[]
    for index,path in enumerate(sorted(folder.glob('*.jpg'))):
        current=Image.open(path).convert('RGB')
        error=sum(ImageStat.Stat(ImageChops.difference(current,desired)).mean)/(3*255)
        matches.append({'seconds':round(index/10,2),'mean_absolute_error':round(error,5)})
        streak=streak+1 if error<=.035 else 0
        if streak>=3:
            start=(index+1)/10
            if start+target<=raw_duration:
                save(output/'start-match.json',{'start_seconds':start,'matches':matches,'method':'Three consecutive actual video frames match the browser ready screenshot; not a visual acceptance verdict'})
                return start
    save(output/'start-match.json',{'matches':matches,'error':'No stable consecutive match'})
    raise CaptureError('No stable first frame match; inspect raw recording and repair preparation')


def mark_recording_completed(manifest, report):
    if report.get('decode_ok') is not True or not report.get('video') or not report.get('video_sha256'):
        raise CaptureError('Recording completion requires decoded current video evidence')
    manifest['recording_pending'] = False
    manifest['status'] = 'recorded_pending_independent_review'
    manifest['recording_status'] = 'recorded_pending_independent_review'
    manifest['video_sha256'] = report['video_sha256']
    manifest['video_current_for_application'] = True


def capture(cfg, case, case_id, resources, *, mode='record'):
    from caseflow import atomic_json, visible_copy_hits, VISIBLE_FORBIDDEN
    case=Path(case).resolve(strict=True)
    plan=validate_plan(case,case_id,resources['ports'])
    health=service_ready(case,case_id,plan)
    output=case/'recording'/f'capture-{time.time_ns()}'
    output.mkdir(parents=True)
    if output.resolve()!=output.absolute():
        raise CaptureError('Linked recording output refused')
    runtime=cfg['runtime']
    request={'case_id':case_id,'case_dir':str(case),'output':str(output),'plan':plan,'mode':mode,
             'node_modules':runtime['node_modules'],'target_seconds':cfg['video']['target_seconds'],
             'forbidden':list(VISIBLE_FORBIDDEN)}
    save(output/'request.json',request)
    command=[runtime['node'],str(Path(__file__).with_name('capture_page.cjs')),str(output/'request.json')]
    started=time.monotonic()
    result=run_command(command,case)
    (output/'capture.log').write_text(result.stdout+'\n'+result.stderr,encoding='utf-8')
    proof=json.loads((output/'browser.json').read_text(encoding='utf-8'))
    if proof['errors'] or len(proof['pages'])!=len(plan['modules']):
        raise CaptureError('Browser errors or missing module evidence')
    for row in proof['pages']:
        if visible_copy_hits(row['visible_text']) or digest(local_file(case,row['screenshot']))!=row['screenshot_sha256']:
            raise CaptureError('Visible-copy or screenshot binding failure')
    validate_plan(case,case_id,resources['ports'])
    service_ready(case,case_id,plan,timeout=5)
    report={'mode':mode,'health':health,'output':str(output),'duration_seconds':round(time.monotonic()-started,2),
            'pages':proof['pages'],'independent_review':'pending'}
    if mode=='probe':
        save(output/'result.json',report)
        return report
    raw=Path(proof['raw_video'])
    if not raw.is_file() or not raw.resolve().is_relative_to(output):
        raise CaptureError('Raw browser recording missing/outside output')
    metadata=json.loads(run_command([runtime['ffprobe'],'-v','error','-show_format','-show_streams','-of','json',str(raw)],case).stdout)
    duration=float(metadata['format']['duration']);target=cfg['video']['target_seconds']
    start=stable_start(raw,case/proof['pages'][0]['screenshot'],output,runtime['ffmpeg'],duration,target)
    video=output/'final.mp4'
    run_command([runtime['ffmpeg'],'-v','error','-ss',str(start),'-i',str(raw),'-t',str(target),'-an','-vf','fps=30',
                 '-c:v','libx264','-preset','fast','-crf','18','-pix_fmt','yuv420p','-movflags','+faststart',str(video)],case)
    decode=run_command([runtime['ffmpeg'],'-v','error','-i',str(video),'-map','0:v:0','-f','null','-'],case)
    if decode.stderr.strip():
        raise CaptureError('Video decode emitted errors')
    report.update(video=video.relative_to(case).as_posix(),video_sha256=digest(video),raw_video=raw.relative_to(case).as_posix(),
                  raw_sha256=digest(raw),raw_duration=duration,source_start_seconds=start,source_end_seconds=start+target,
                  events=proof['events'],decode_ok=True,duration_seconds=round(time.monotonic()-started,2))
    save(output/'result.json',report)
    manifest_path=local_file(case,'evidence/artifact-manifest.json')
    manifest=json.loads(manifest_path.read_text(encoding='utf-8'))
    audit_path=local_file(case,manifest['ui_text_audit'])
    audit=json.loads(audit_path.read_text(encoding='utf-8'))
    prior_capture=set(manifest.get('capture_ui_screenshots',[]))
    manifest['ui_screenshots']=[p for p in manifest['ui_screenshots'] if p not in prior_capture]+[p['screenshot'] for p in proof['pages']]
    audit['pages']=[p for p in audit['pages'] if p['screenshot'] not in prior_capture]+proof['pages']
    manifest.update(video=report['video'],capture_ui_screenshots=[p['screenshot'] for p in proof['pages']],
                    capture_report=(output/'result.json').relative_to(case).as_posix(),capture_plan='evidence/capture-plan.json')
    mark_recording_completed(manifest, report)
    atomic_json(audit_path,audit)
    atomic_json(manifest_path,manifest)
    return report


if __name__=='__main__':
    parser=argparse.ArgumentParser()
    parser.add_argument('mode',choices=['probe'])
    parser.add_argument('case',type=Path)
    parser.add_argument('--case-id',required=True)
    parser.add_argument('--port',type=int,required=True)
    parser.add_argument('--config',type=Path,default=Path(__file__).resolve().parents[1]/'config.json')
    args=parser.parse_args()
    from caseflow import config_at
    print(json.dumps(capture(config_at(args.config),args.case,args.case_id,{'ports':[args.port]},mode=args.mode),ensure_ascii=False))
