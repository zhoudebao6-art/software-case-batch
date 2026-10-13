"""Controlled full 5fps timeline and interaction original frames for product-v2."""
import argparse
import json
import math
import os
import shutil
from pathlib import Path
from common import digest,inside,no_links,read_json,write_json
from _video_evidence_core import generate as core_generate,command

def generate(workspace,video,recording,output,media_token=None,owner_pid=None,runtime_pid=None):
    workspace=no_links(workspace);video=no_links(video);recording=no_links(recording);output=no_links(output)
    from batch_control import media_binding,mutate
    binding=media_binding(workspace)
    if binding:
        if not media_token or not owner_pid or not runtime_pid:raise ValueError('Registered batch evidence requires an active evidence lease and bounded runtime')
        from media_job import job_name,job_pids
        if os.getpid() not in job_pids(job_name(binding['root'],binding['batch_id'],media_token)):
            raise ValueError('Evidence generator is outside its reserved Windows Job')
        mutate(binding['root'],binding['batch_id'],owner_pid,'verify-evidence',binding['case_id'],workspace,media_token,runtime_pid=runtime_pid)
    if workspace not in output.parents:raise ValueError('Controlled video evidence must be inside the case workspace')
    proof=read_json(recording)
    if proof.get('sha256')!=digest(video) or proof.get('passed') is not True:raise ValueError('Current successful recording hash required')
    tools={name:os.environ.get('SCB_PRO_'+name.upper()) for name in ('ffmpeg','ffprobe')}
    if not all(tools.values()):raise ValueError('Load Enter-Environment.ps1 first')
    report=core_generate(video,output,sample_fps=5,min_seconds=55,max_seconds=75,tool_paths=tools)
    frames=[]
    for i,event in enumerate(proof.get('events',[])):
        for kind,target in (('before',max(0,float(event['started'])-.2)),('after',min(report['duration']-1/report['fps'],float(event['completed'])+.2))):
            number=min(report['source_frame_count']-1,max(0,int(target*report['fps'])))
            frame=output/'frames'/f'event-{i+1:02d}-{kind}.jpg'
            frames.append({'file':str(frame),'seconds':number/report['fps'],'target_seconds':target,
                'source_frame_index':number,'type':'interaction_'+kind,'event_index':i,'action':event['action']})
    if not frames:raise ValueError('Actual operation events required for interaction frames')
    # One full decode extracts every requested source frame; duplicate targets
    # retain separate event paths without decoding the clip once per event.
    numbers=sorted({f['source_frame_index'] for f in frames})
    selected=output/'interaction-selected';selected.mkdir()
    expression='+'.join(f'eq(n\\,{n})' for n in numbers)
    command(['ffmpeg','-v','error','-i',str(video),'-vf','select='+expression,'-fps_mode','vfr','-q:v','2',str(selected/'frame-%06d.jpg')],tools)
    extracted=sorted(selected.glob('frame-*.jpg'))
    if len(extracted)!=len(numbers):raise ValueError('Missing requested interaction source frame')
    lookup=dict(zip(numbers,extracted))
    for frame in frames:
        shutil.copyfile(lookup[frame['source_frame_index']],frame['file']);frame['sha256']=digest(frame['file'])
    report.update({'interaction_frames':frames,'recording_receipt':{'path':str(recording),'sha256':digest(recording)},
                  'generator':{'core_sha256':digest(Path(__file__).with_name('_video_evidence_core.py')),
                               'wrapper_sha256':digest(Path(__file__))},'visual_review_status':'pending_independent_review'})
    write_json(output/'timeline.json',report)
    validate(workspace,output/'timeline.json',video)
    return {'timeline':str(output/'timeline.json'),'sha256':digest(output/'timeline.json'),
            'sample_frames':len(report['frames']),'contact_sheets':len(report['contact_sheets']),'interaction_frames':len(frames)}

def validate(workspace,timeline_path,video,recording_path=None):
    workspace=no_links(workspace);timeline_path=no_links(timeline_path)
    if workspace not in timeline_path.parents:raise ValueError('Video timeline escaped case workspace')
    report=read_json(timeline_path)
    if (report.get('video_sha256')!=digest(video) or report.get('sample_fps')!=5 or not report.get('decode_ok')
            or not report.get('duration_in_requested_range') or not 55<=report.get('duration',0)<=75):
        raise ValueError('Current complete video decode and 5fps timeline required')
    frames=report.get('frames',[]);uniform=[f for f in frames if f.get('type')=='uniform_sample']
    if len(uniform)!=max(1,int(round(report['duration']*5))) or not {'uniform_sample','first','last'}.issubset({f.get('type') for f in frames}):
        raise ValueError('Complete samples and original first/last frames required')
    first=[f for f in frames if f.get('type')=='first'];last=[f for f in frames if f.get('type')=='last']
    if (len(first)!=1 or len(last)!=1 or first[0].get('source_frame_index')!=0 or first[0].get('seconds')!=0
            or last[0].get('source_frame_index')!=report.get('source_frame_count',0)-1
            or abs(last[0].get('seconds',-1)-(report['duration']-1/report['fps']))>.001):
        raise ValueError('First/last evidence must be the actual first and last source frames')
    if len({f['file'] for f in frames})!=len(frames):raise ValueError('Timeline original frame paths must be unique')
    if any(abs(f['seconds']-i/5)>.001 for i,f in enumerate(uniform)):
        raise ValueError('Uniform samples must cover the ordered actual 5fps timeline without gaps or duplicates')
    mapped=[path for sheet in report.get('contact_sheets',[]) for path in sheet.get('frame_files',[])]
    if mapped!=[f['file'] for f in frames]:raise ValueError('Contact sheets must map every original timeline frame in order')
    interactions=report.get('interaction_frames',[])
    if not interactions or {f.get('type') for f in interactions}!={'interaction_before','interaction_after'}:
        raise ValueError('Interaction before/after original frames required')
    binding=report.get('recording_receipt',{});receipt=no_links(binding.get('path',''))
    if recording_path is not None and receipt!=no_links(recording_path):raise ValueError('Timeline must bind the actual current or explicitly inherited operation receipt')
    if not receipt.is_file() or digest(receipt)!=binding.get('sha256'):raise ValueError('Original operation recording receipt hash changed')
    actual=read_json(receipt);events=actual.get('events',[])
    if actual.get('passed') is not True or actual.get('sha256')!=digest(video) or not events or len(interactions)!=2*len(events):
        raise ValueError('Every actual recording operation must have two original interaction frames')
    if len({f['file'] for f in interactions})!=len(interactions):raise ValueError('Interaction original frame paths must be unique')
    for index,event in enumerate(events):
        pair=[f for f in interactions if f.get('event_index')==index]
        if len(pair)!=2 or {f['type'] for f in pair}!={'interaction_before','interaction_after'}:
            raise ValueError('Missing/duplicate interaction pair for actual operation')
        for frame in pair:
            target=max(0,float(event['started'])-.2) if frame['type']=='interaction_before' else min(report['duration']-1/report['fps'],float(event['completed'])+.2)
            if frame.get('action')!=event['action'] or abs(frame['target_seconds']-target)>.001 or abs(frame['seconds']-target)>1/report['fps']+.001:
                raise ValueError('Interaction original frame time/action differs from the actual event ±0.2s')
    for item in frames+report['contact_sheets']+interactions:
        path=no_links(item['file'])
        if workspace not in path.parents or not path.is_file() or digest(path)!=item['sha256']:
            raise ValueError('Controlled video frame hash/path changed')
    return {'timeline_sha256':digest(timeline_path),'frames':len(frames),'contact_sheets':len(report['contact_sheets']),'interaction_frames':len(interactions)}

if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('action',choices=['generate','validate']);p.add_argument('--workspace',required=True);p.add_argument('--video',required=True);p.add_argument('--recording');p.add_argument('--output');p.add_argument('--timeline');p.add_argument('--media-token');p.add_argument('--owner-pid',type=int);p.add_argument('--runtime-pid',type=int);a=p.parse_args()
    result=generate(a.workspace,a.video,a.recording,a.output,a.media_token,a.owner_pid,a.runtime_pid) if a.action=='generate' else validate(a.workspace,a.timeline,a.video)
    print(json.dumps(result,ensure_ascii=False,indent=2))
