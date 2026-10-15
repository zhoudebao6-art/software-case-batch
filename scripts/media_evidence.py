"""Controlled full 5fps timeline and interaction original frames for product-v2."""
import argparse
import json
import math
import os
from pathlib import Path
from common import digest,inside,no_links,read_json,write_json,state,delivery_paths
from _video_evidence_core import generate as core_generate

LEGACY_POLICY='legacy-fixed-v1'
FLOW_POLICY='flow-complete-v1'


def frozen_video(workspace,video):
    """Prepared deliveries use their frozen path; standalone media stays generic."""
    video=no_links(video)
    if (workspace/'.product-v2/run.json').is_file():
        _,output,run=state(workspace)
        if video!=delivery_paths(run,output)['video']:
            raise ValueError('Video path differs from the frozen delivery layout')
    return video

def validate_recording_duration(proof,run_policy=None,duration=None):
    """Validate measured media and completion facts against its frozen policy.

    Missing policy is the historical fixed contract only. New runs must pass
    their frozen policy to prevent a legacy receipt satisfying a new contract.
    """
    version=proof.get('recording_policy_version',LEGACY_POLICY)
    if version not in {LEGACY_POLICY,FLOW_POLICY}:raise ValueError('Unknown recording policy')
    if run_policy is not None:
        if run_policy not in {LEGACY_POLICY,FLOW_POLICY} or version!=run_policy:raise ValueError('Recording policy differs from frozen run')
    def finite(value):return isinstance(value,(int,float)) and not isinstance(value,bool) and math.isfinite(value)
    seconds=proof.get('duration') if duration is None else duration
    if not finite(seconds) or (not 55<=seconds<=75 if version==LEGACY_POLICY else seconds<=60):
        raise ValueError('Video duration violates frozen recording policy')
    if duration is not None and (not finite(proof.get('duration')) or abs(seconds-proof['duration'])>.12):
        raise ValueError('Measured timeline duration differs from operation receipt')
    if version==FLOW_POLICY:
        estimate=proof.get('estimated_duration_seconds');timeout=proof.get('timeout_seconds')
        events=proof.get('events',[]);end=proof.get('final_result_completion',{})
        count=proof.get('planned_step_count')
        if (not finite(estimate) or estimate<=60 or not finite(timeout) or timeout<=estimate or seconds>timeout+.12 or
            not isinstance(count,int) or isinstance(count,bool) or count<6 or proof.get('completed_step_count')!=count or len(events)!=count or
            len({e.get('action') for e in events})<3):raise ValueError('Complete varied operation flow and separate runtime timeout required')
        last=0
        for event in events:
            start=event.get('started');complete=event.get('completed')
            if not finite(start) or not finite(complete) or start<last or complete<start or complete>seconds+.12:
                raise ValueError('Operation timing falls outside continuous capture')
            last=complete
            if event.get('reading_seconds',0):
                read=event['reading_seconds'];begin=event.get('reading_started');finish=event.get('reading_completed')
                if (not finite(read) or read<=0 or not finite(begin) or not finite(finish) or begin<complete or finish-begin<read-.12 or
                    finish>seconds+.12 or not isinstance(event.get('reading_reason'),str) or not event['reading_reason'].strip()):
                    raise ValueError('Meaningful observed operation reading evidence required')
                last=finish
        begin=end.get('observed_at');finish=end.get('completed_at');read=end.get('reading_seconds')
        if (end.get('completed') is not True or not end.get('selector') or not finite(begin) or begin<last or not finite(finish) or
            not finite(read) or read<=0 or finish-begin<read-.12 or abs(finish-seconds)>.12 or
            not isinstance(end.get('reading_reason'),str) or not end['reading_reason'].strip()):
            raise ValueError('Completed final business result and meaningful reading evidence required')
    return {'recording_policy_version':version,'duration':seconds,'flow_complete':version==FLOW_POLICY}

def generate(workspace,video,recording,output,media_token=None,owner_pid=None,runtime_pid=None):
    workspace=no_links(workspace);video=no_links(video);recording=no_links(recording);output=no_links(output)
    video=frozen_video(workspace,video)
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
    policy=validate_recording_duration(proof)
    tools={name:os.environ.get('SCB_PRO_'+name.upper()) for name in ('ffmpeg','ffprobe')}
    if not all(tools.values()):raise ValueError('Load Enter-Environment.ps1 first')
    flexible=policy['recording_policy_version']==FLOW_POLICY
    report=core_generate(video,output,sample_fps=5,min_seconds=60 if flexible else 55,max_seconds=None if flexible else 75,
                         tool_paths=tools,interaction_events=proof.get('events',[]))
    validate_recording_duration(proof,duration=report['duration'])
    frames=report.get('interaction_frames',[])
    if not frames:raise ValueError('Actual operation events required for interaction frames')
    report.update({'interaction_frames':frames,'recording_receipt':{'path':str(recording),'sha256':digest(recording)},
                  'recording_policy_version':policy['recording_policy_version'],
                  'generator':{'core_sha256':digest(Path(__file__).with_name('_video_evidence_core.py')),
                               'wrapper_sha256':digest(Path(__file__))},'visual_review_status':'pending_independent_review'})
    write_json(output/'timeline.json',report)
    validate(workspace,output/'timeline.json',video)
    return {'timeline':str(output/'timeline.json'),'sha256':digest(output/'timeline.json'),
            'sample_frames':len(report['frames']),'contact_sheets':len(report['contact_sheets']),'interaction_frames':len(frames)}

def validate(workspace,timeline_path,video,recording_path=None):
    workspace=no_links(workspace);timeline_path=no_links(timeline_path)
    video=frozen_video(workspace,video)
    if workspace not in timeline_path.parents:raise ValueError('Video timeline escaped case workspace')
    report=read_json(timeline_path)
    if (report.get('video_sha256')!=digest(video) or report.get('sample_fps')!=5 or not report.get('decode_ok')
            or not report.get('duration_in_requested_range')):
        raise ValueError('Current complete video decode and 5fps timeline required')
    frames=report.get('frames',[]);uniform=[f for f in frames if f.get('type')=='uniform_sample']
    expected=max(1,math.ceil(report['duration']*5-1e-7)) if report.get('sampling_rounding')=='up-v1' else max(1,int(round(report['duration']*5)))
    if len(uniform)!=expected or not {'uniform_sample','first','last'}.issubset({f.get('type') for f in frames}):
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
    validate_recording_duration(actual,run_policy=report.get('recording_policy_version',LEGACY_POLICY),duration=report.get('duration'))
    if ('width' in actual or 'height' in actual) and (actual.get('width')!=1920 or actual.get('height')!=1080 or
            report.get('width')!=actual['width'] or report.get('height')!=actual['height']):
        raise ValueError('Current encoded video geometry differs from the operation receipt')
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
    result=generate(a.workspace,a.video,a.recording,a.output,a.media_token,a.owner_pid,a.runtime_pid) if a.action=='generate' else validate(a.workspace,a.timeline,a.video,a.recording)
    print(json.dumps(result,ensure_ascii=False,indent=2))
