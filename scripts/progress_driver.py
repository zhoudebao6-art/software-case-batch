"""Bounded, explicit owner-operated capture -> evidence continuation. No model calls."""
import argparse
from contextlib import contextmanager
from concurrent.futures import ThreadPoolExecutor
import json
import os
from pathlib import Path
import subprocess
import sys
import time
import threading
import uuid
import batch_control as batch
from common import digest,no_links,read_json,write_json

_CONTROL_LOCK=threading.RLock()


def mutate(*args,**kwargs):
    # One helper can supervise several distinct cases. Serialize only its short
    # control transactions; media runs outside this lock and keeps the real Job.
    with _CONTROL_LOCK:return batch.mutate(*args,**kwargs)


@contextmanager
def invocation(root,target,pid,case_id):
    """Serialize only this case; reclaim a dead helper, never a live media Job."""
    path=target/'progress'/f'{case_id}.lock.json';nonce=uuid.uuid4().hex
    with _CONTROL_LOCK,batch.transaction(root,wait_seconds=3):
        batch.owner_check(target,pid)
        if path.exists():
            old=read_json(path)
            if batch.identity(old['identity']['pid'])==old['identity']:
                raise ValueError('This case already has a live progress invocation')
        write_json(path,{'identity':batch.identity(os.getpid()),'owner':batch.identity(pid),'nonce':nonce})
    try:yield
    finally:
        with _CONTROL_LOCK,batch.transaction(root,wait_seconds=3):
            if path.exists() and read_json(path).get('nonce')==nonce:path.unlink()


def capture_ready(workspace,run):
    path=workspace/'.product-v2/capture-pending.json'
    if not path.exists():return None
    pending=read_json(path)
    if not pending.get('sha256'):return None
    capture=no_links(pending['path'])
    if workspace not in capture.parents or digest(capture)!=pending['sha256']:raise ValueError('Capture receipt changed; retain original and repair evidence')
    value=read_json(capture)
    if value.get('status')!='captured' or value.get('workspace')!=str(workspace) or value.get('run_id')!=run['run_id'] or value.get('errors'):
        raise ValueError('Capture does not belong to this successful current run')
    raw=no_links(value['rawPath'])
    if workspace not in raw.parents or not raw.is_file() or not raw.stat().st_size:raise ValueError('Original capture missing; explicit repair required')
    # The existing evidence entry performs full raw/input hashes and all media
    # checks once admitted. This pointer inspection never claims technical pass.
    return {'path':str(capture),'sha256':pending['sha256']}


def retained_captures(workspace,run,saved):
    """Find current-run capture identity when its pending pointer was lost.

    These short receipts are recovery facts, never evidence approval. Discovery
    uses this case's control dir and prior references; never hash/decode raw.
    """
    control=workspace/'.product-v2'
    paths=set(control.glob('*capture*.json'))|set(control.glob('recordings/*/capture.json'))
    for reference in (saved.get('capture'),read_json(control/'capture-pending.json') if (control/'capture-pending.json').exists() else None):
        if isinstance(reference,dict) and reference.get('path'):paths.add(Path(reference['path']))
    found=[]
    for candidate in sorted(paths):
        path=no_links(candidate)
        if workspace not in path.parents:raise ValueError('Capture receipt escaped its registered workspace')
        if not path.is_file():continue
        try:value=read_json(path)
        except (ValueError,OSError):continue
        if isinstance(value,dict) and value.get('status')=='captured' and value.get('workspace')==str(workspace) and value.get('run_id')==run['run_id']:
            found.append({'path':str(path),'sha256':digest(path)})
    return found


def receipt_refs(workspace):
    paths=[workspace/'.product-v2/recording.json',workspace/'.product-v2/controlled-video.json']
    return [{'path':str(path),'sha256':digest(path)} for path in paths]


def execute(workspace,phase,lease,plan,log,timeout):
    record_args=['--workspace',str(workspace),'--phase',phase,
                 '--batch-root',lease['root'],'--batch-id',lease['batchId'],
                 '--case-id',lease['caseId'],'--media-token',lease['token'],'--owner-pid',str(lease['ownerPid'])]
    if plan:record_args+=['--plan',str(plan)]
    command=[os.environ['SCB_PRO_PYTHON'],'-B',str(Path(__file__).with_name('media_job.py')),
             '--workspace',str(workspace),'--phase',phase,'--lease',json.dumps(lease),'--',*record_args]
    # Only this invocation's supervisor is subject to this timeout. Its existing
    # kill-on-close Job owns the recording descendants. No process census/kills.
    with log.open('xb') as stream:
        try:return subprocess.run(command,stdout=stream,stderr=subprocess.STDOUT,timeout=timeout,
                                  creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0)).returncode
        except subprocess.TimeoutExpired:return 124


def drive(root,batch_id,pid,case_id,plan=None,timeout=1800,retry_capture=False):
    if type(timeout) is not int or not 30<=timeout<=3600:raise ValueError('Media invocation timeout must be 30..3600 seconds')
    root=no_links(root);target,manifest=batch.batch(root,batch_id);batch.owner_check(target,pid)
    case=next((c for c in manifest['cases'] if c['case_id']==case_id),None)
    if not case:raise ValueError('Progress is restricted to this registered case')
    # IDs are used in private checkpoint filenames; do not interpret path syntax.
    if not case_id or not all(c.isalnum() or c in '-_' for c in case_id):raise ValueError('Unsafe progress case ID')
    workspace=no_links(case['workspace']);binding=batch.media_binding(workspace)
    if digest(no_links(case['source_docx']))!=case['source_sha256']:raise ValueError('Registered source changed')
    if not binding or binding['root']!=str(root) or binding['batch_id']!=batch_id or binding['case_id']!=case_id:
        raise ValueError('Progress requires the existing frozen Windows Job media binding')
    run=read_json(workspace/'.product-v2/run.json')
    if run.get('workspace')!=str(workspace) or not run.get('run_id'):raise ValueError('Current prepared run required')
    if plan:plan=no_links(plan)
    checkpoint=target/'progress'/f'{case_id}.json'
    with invocation(root,target,pid,case_id):
        saved=read_json(checkpoint) if checkpoint.exists() else {}
        if saved and saved.get('run_id')!=run['run_id']:raise ValueError('Progress checkpoint belongs to another run')
        if saved.get('status')=='technical_evidence_ready':
            if saved.get('receipts')!=receipt_refs(workspace):raise ValueError('Completed media receipts changed; explicit evidence repair required')
            return {**saved,'reused_checkpoint':True,'next_action':'independent_review'}
        def save(status,**extra):
            nonlocal saved
            value={'contract':'owner-media-progress-v1','run_id':run['run_id'],'batch_id':batch_id,'case_id':case_id,
                   'owner':batch.identity(pid),'updated_ns':time.time_ns(),'status':status,
                   **{key:saved[key] for key in ('phase','capture') if key in saved},**extra}
            write_json(checkpoint,value);saved=value;return value
        def owned_tickets():
            pool=read_json(root/'queue.json') if (root/'queue.json').exists() else []
            found=[q for q in pool if q['batch_id']==batch_id and q['case_id']==case_id and q['status'] in {'active','waiting'}]
            if len(found)>1:raise ValueError('Multiple current case tickets; preserve and reconcile explicitly')
            if found and found[0]['owner']!=batch.identity(pid):raise ValueError('Case ticket belongs to another owner')
            return found
        # Adopt the original completed-recording fact for r16/earlier runs that
        # have no helper checkpoint. This hashes video/short timeline only; the
        # established helper neither decodes nor reads all frame files.
        recording=workspace/'.product-v2/recording.json';controlled=workspace/'.product-v2/controlled-video.json'
        if recording.exists() and controlled.exists():
            try:
                from proflow import completed_recording
                completed_recording(workspace,read_json(recording),no_links(run['video']))
            except (ValueError,OSError,KeyError,TypeError):pass # Missing/damaged evidence follows original recovery below.
            else:
                tickets=owned_tickets()
                if tickets:
                    entry=tickets[0]
                    if entry['stage'] not in {'record','evidence'}:
                        return save('waiting',next_action='finish_current_model_stage',ticket=entry)
                    if entry['status']=='active':
                        runtime=entry.get('media_runtime')
                        from media_job import job_name,job_pids
                        if not runtime or batch.identity(runtime['pid'])==runtime['identity'] or job_pids(job_name(root,batch_id,entry['token'])):
                            return save('running',next_action='wait_for_existing_media_exit_then_resume',ticket=entry)
                    mutate(root,batch_id,pid,'release-slot',token=entry['token'])
                return save('technical_evidence_ready',receipts=receipt_refs(workspace),adopted_completed_recording=True,
                            next_action='independent_review',visual_review_required=True)
        # At most capture and evidence once each. Never poll a queue, dispatch a
        # model, execute another owner's selected ticket, or re-record on crash.
        for _ in range(2):
            state=read_json(target/'state.json');item=state['cases'][case_id]
            if state['drain'] or item.get('phase') in {'blocked','delivered'}:
                return save('paused',next_action='owner_resume_after_actual_recovery',reason='batch drain or case blocked/delivered')
            capture=capture_ready(workspace,run);tickets=owned_tickets();entry=tickets[0] if tickets else None
            if entry and entry['stage'] not in {'record','evidence'}:
                return save('waiting',next_action='finish_current_model_stage',ticket=entry)
            if entry and entry['status']=='active' and entry.get('media_runtime'):
                runtime=entry['media_runtime']
                from media_job import job_name,job_pids
                if batch.identity(runtime['pid'])==runtime['identity'] or job_pids(job_name(root,batch_id,entry['token'])):
                    return save('running',phase='evidence' if entry['stage']=='evidence' else 'capture',
                                next_action='wait_for_existing_media_exit_then_resume',ticket=entry)
            if not capture:
                retained=retained_captures(workspace,run,saved)
                evidence_pending=(saved.get('phase')=='evidence' or saved.get('status')=='capture_complete' or
                                  bool(saved.get('capture')) or (entry and entry['stage']=='evidence'))
                if evidence_pending or retained:
                    return save('failed',phase='evidence',next_action='repair_capture_pointer_then_resume_evidence',
                                reason='Prior capture/evidence context retained; restore the original capture pointer before continuing',
                                ticket=entry,capture_receipts=retained)
            if entry and entry['status']=='active' and entry.get('media_runtime'):
                mutate(root,batch_id,pid,'release-slot',token=entry['token'])
                entry=None
                if not capture:return save('failed',phase='capture',next_action='repair_capture_then_resume_with_retry_capture',reason='Exited capture has no successful receipt')
            stage='evidence' if capture else 'record';phase='evidence' if capture else 'capture'
            if stage=='record' and recording.exists():
                return save('failed',next_action='repair_existing_recording_or_evidence',reason='Original recording exists but completed facts are invalid; no automatic business replay')
            if stage=='record' and not retry_capture and (saved.get('phase')=='capture' or (workspace/'.product-v2/capture-pending.json').exists()):
                return save('failed',phase='capture',ticket=entry,next_action='repair_capture_then_resume_with_retry_capture',reason='Unfinished original capture retained; repair and explicit retry required')
            if entry and entry['stage']!=stage:
                mutate(root,batch_id,pid,'release-slot',token=entry['token'])
                entry=None
            if stage=='record' and not plan:return save('waiting',next_action='provide_current_record_plan',capture=capture)
            if not entry:entry=mutate(root,batch_id,pid,'queue',case_id,stage=stage)
            if entry['status']=='waiting':
                admitted=mutate(root,batch_id,pid,'acquire',token=entry['token'])
                if admitted.get('status')!='active':
                    return save('waiting',**({'phase':'evidence'} if phase=='evidence' else {}),
                                next_action='resume_after_resource_or_selected_owner_progress',ticket=entry,admission=admitted)
                entry=admitted
            log=target/'progress'/f'{case_id}-{phase}-{uuid.uuid4().hex}.log';log.parent.mkdir(parents=True,exist_ok=True)
            save('running',ticket=entry,phase=phase,capture=capture,log=str(log))
            lease={'root':str(root),'batchId':batch_id,'caseId':case_id,'ownerPid':pid,'token':entry['token']}
            code=None;failure=None
            try:code=execute(workspace,phase,lease,plan,log,timeout)
            except (ValueError,OSError) as error:failure=str(error)
            finally:
                # Existing release verifies Job members, runtime identity and
                # exact stale lock. If exit is unproven the reservation stays.
                try:mutate(root,batch_id,pid,'release-slot',token=entry['token'])
                except (ValueError,OSError) as error:
                    return save('cleanup_pending',ticket=entry,exit_code=code,reason=str(error),log=str(log),next_action='verify_existing_media_exit_then_resume')
            if failure or code!=0:
                return save('failed',phase=phase,exit_code=code,reason=failure or 'Media command failed; original receipts retained',log=str(log),
                            next_action='repair_evidence_then_resume' if phase=='evidence' else 'repair_capture_then_resume_with_retry_capture')
            if phase=='capture':
                captured=capture_ready(workspace,run)
                if not captured:return save('failed',phase='capture',next_action='repair_capture_then_resume_with_retry_capture',reason='Capture exited without its successful receipt',log=str(log))
                save('capture_complete',phase='evidence',capture=captured,log=str(log),next_action='evidence')
            else:
                return save('technical_evidence_ready',receipts=receipt_refs(workspace),log=str(log),next_action='independent_review',visual_review_required=True)
        raise ValueError('Bounded media continuation exhausted without a result')


def drive_ready(root,batch_id,pid,plans=None,timeout=1800):
    """Drain only the original owner's already queued media, on completion events.

    No daemon, sleep/retry loop, new case registration or automatic capture retry.
    The ordinary drive/acquire/Job path remains the sole execution authority.
    """
    if type(timeout) is not int or not 30<=timeout<=3600:raise ValueError('Media invocation timeout must be 30..3600 seconds')
    root=no_links(root);target,manifest=batch.batch(root,batch_id)
    cases={c['case_id']:c for c in manifest['cases']}
    identity=batch.identity(pid)
    if not identity:raise ValueError('Original live owner required')
    def snapshot():
        with _CONTROL_LOCK,batch.transaction(root,wait_seconds=3):
            batch.owner_check(target,pid)
            state=read_json(target/'state.json')
            pool=read_json(root/'queue.json') if (root/'queue.json').exists() else []
            ready=batch.runnable_waiting(root,pool)
            return state,pool,ready
    state,pool,ready=snapshot()
    initial=[q for q in pool if q['batch_id']==batch_id and q['owner']==identity
             and q['stage'] in {'record','evidence'} and q['status'] in {'waiting','active'}
             and state['cases'][q['case_id']].get('phase') not in {'blocked','delivered'}]
    pending={q['case_id'] for q in initial}
    if len(pending)!=len(initial):raise ValueError('Multiple current media tickets for one case')
    plans={} if plans is None else plans
    if not isinstance(plans,dict) or set(plans)-pending:raise ValueError('Plans must map only initially queued owned cases')
    runs={c:read_json(no_links(cases[c]['workspace'])/'.product-v2/run.json')['run_id'] for c in pending}
    results={};attempted=set();selected=None
    def invoke(case_id):
        try:
            workspace=no_links(cases[case_id]['workspace'])
            if read_json(workspace/'.product-v2/run.json')['run_id']!=runs[case_id]:raise ValueError('Queued case run changed during ready-media continuation')
            plan=plans.get(case_id)
            if plan is not None:
                plan=no_links(plan)
                if workspace not in plan.parents:raise ValueError('Recording plan must remain in its registered case workspace')
            else:
                plan=workspace/'.product-v2/record-plan.json'
                if not plan.is_file():plan=None
            return drive(root,batch_id,pid,case_id,plan,timeout,retry_capture=False)
        except (ValueError,OSError,KeyError,TypeError) as exc:
            return {'status':'failed','next_action':'repair_reported_case_only','reason':str(exc)}
    for _ in range(2*len(initial)+1):
        if not pending:break
        state,pool,ready=snapshot()
        if state['drain']:break
        active=[q for q in pool if q['stage'] in {'record','evidence'} and q['status']=='active']
        # Only local progress can cause another attempt. Other batches changing
        # the shared queue must not turn a resource wait into a polling loop.
        fingerprint=tuple(sorted((q['token'],q['stage'],q['status'],json.dumps(q['owner'],sort_keys=True))
                                 for q in pool if q['batch_id']==batch_id and q['case_id'] in runs
                                 and q['stage'] in {'record','evidence'} and q['status'] in {'waiting','active'}))
        current=[q for q in active if q['batch_id']==batch_id and q['owner']==identity and q['case_id'] in pending]
        order=lambda q:(-q['priority'],q['submitted_ns'],q['token'])
        if not current:
            evidence=sorted((q for q in active+ready if q['stage']=='evidence'),key=lambda q:(q['status']!='active',*order(q)))
            current=evidence[:1] if evidence else sorted((q for q in ready if q['stage']=='record'),key=order)[:batch.GLOBAL_RECORDING_LIMIT]
        wave=[]
        for ticket in current:
            selected={k:ticket[k] for k in ('token','batch_id','case_id','stage','owner')}
            case_id=ticket['case_id'];key=(case_id,fingerprint)
            if (ticket['batch_id']!=batch_id or ticket['owner']!=identity or case_id not in pending
                    or state['cases'][case_id].get('phase') in {'blocked','delivered'} or key in attempted):break
            attempted.add(key);wave.append(case_id)
        if not wave:break
        # Existing admission still enforces actual memory, global capture count,
        # evidence exclusion and FIFO. No additional model slot is acquired.
        with ThreadPoolExecutor(max_workers=len(wave)) as executor:
            outcomes=list(executor.map(invoke,wave))
        for case_id,outcome in zip(wave,outcomes):
            results[case_id]=outcome
            if outcome.get('admission',{}).get('selected'):selected=outcome['admission']['selected']
            if outcome['status']!='waiting':pending.discard(case_id)
        # The next iteration is caused by this finite wave completing. It may
        # join retained captures to their evidence without another parent turn.
    failed=any(v['status'] in {'failed','cleanup_pending'} for v in results.values())
    status=('failed' if failed else 'paused' if state['drain'] else
            'technical_evidence_ready' if initial and len(results)==len(initial) and
             all(v['status']=='technical_evidence_ready' for v in results.values()) else 'waiting' if initial else 'idle')
    return {'status':status,'batch_id':batch_id,'owner':identity,'case_ids':sorted(runs),
            'cases':{c:dict({k:v[k] for k in ('status','next_action','phase','reason') if k in v},
                           **({'admission_reason':v['admission']['reason']} if v.get('admission',{}).get('reason') else {}))
                     for c,v in sorted(results.items())},
            'selected':selected if status in {'waiting','failed'} else None,
            'progress_directory':str(target/'progress'),'visual_review_required':True,
            'scope':'Initially queued owned media only; no model dispatch, visual approval or publication.'}


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root',required=True);parser.add_argument('--batch-id',required=True)
    parser.add_argument('--pid',type=int,required=True)
    selection=parser.add_mutually_exclusive_group(required=True)
    selection.add_argument('--case-id');selection.add_argument('--ready',action='store_true')
    parser.add_argument('--plans',help='Optional existing JSON mapping owned case IDs to their custom plan paths')
    parser.add_argument('--plan');parser.add_argument('--timeout',type=int,default=1800)
    parser.add_argument('--retry-capture',action='store_true',help='Explicit retry only after repairing a failed/unfinished capture; valid captures always reused')
    args=parser.parse_args()
    try:
        if args.ready:
            if args.plan or args.retry_capture:raise ValueError('--ready never retries failed captures; use the original explicit case command after repair')
            result=drive_ready(args.root,args.batch_id,args.pid,read_json(args.plans) if args.plans else None,args.timeout)
        else:
            if args.plans:raise ValueError('--plans is only for --ready')
            result=drive(args.root,args.batch_id,args.pid,args.case_id,args.plan,args.timeout,args.retry_capture)
        print(json.dumps(result,ensure_ascii=False,indent=2));return 2 if result['status'] in {'failed','cleanup_pending'} else 0
    except (ValueError,OSError,KeyError,TypeError) as error:print('ERROR: '+str(error),file=sys.stderr);return 2


if __name__=='__main__':raise SystemExit(main())
