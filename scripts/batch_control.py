"""Small parent-operated batch state/locks/queues; never dispatch models itself."""
import argparse
from contextlib import contextmanager
import ctypes
import json
import os
from pathlib import Path
import time
import uuid
from copy import deepcopy
from common import digest,inside,no_links,read_json,write_json

CAPACITIES={'build':8,'review':3,'record':2,'evidence':1,'expedited':1}
GLOBAL_RECORDING_LIMIT=4
MODEL_STAGES={'build','review','expedited'}
MODELS={'build':['gpt-6.1-sol','high'],'repair':['gpt-6.1-sol','ultra'],
        'review':['gpt-6.1-sol','ultra'],'expedited':['gpt-6-astra','low']}
REVIEW_ADMISSION_CONTRACT='frozen-review-route-v1'

def authorization_scope_names(manifest,case):
    if manifest.get('review_admission_contract')==REVIEW_ADMISSION_CONTRACT:
        return case.get('authorization_scope_names',[str(case['case_id']),manifest['batch_id'],manifest['batch_id']+'/'+str(case['case_id'])])
    # Historical manifests lack a frozen alias map. New controls can use their
    # registered IDs or prepared name; historical saved grants remain compatible.
    names={str(case['case_id']),manifest['batch_id']}
    run_path=no_links(case['workspace'])/'.product-v2/run.json'
    if run_path.is_file():
        run=read_json(run_path)
        if run.get('workspace')==case['workspace'] and isinstance(run.get('title'),str) and run['title'].strip():names.add(run['title'])
    return sorted(names)

def check_authorization_scope(manifest,case,record):
    if record.get('scope_name') not in authorization_scope_names(manifest,case):
        raise ValueError('Expedited authorization must name its registered case/batch or unique frozen case alias')
    context=record.get('scope_context')
    if context:
        if not isinstance(context,dict):raise ValueError('Implicit batch expedite requires a frozen registered batch context')
        context_root=no_links(context.get('root',''));path=context_root/manifest['batch_id']/'manifest.json'
        if (context.get('batch_id')!=manifest['batch_id'] or record.get('scope_name')!=manifest['batch_id'] or
            context.get('manifest_sha256')!=digest(path) or read_json(path)!=manifest):
            raise ValueError('Implicit batch expedite requires this frozen registered batch context')
        if manifest.get('review_admission_contract')==REVIEW_ADMISSION_CONTRACT:
            binding=media_binding(case['workspace'])
            if not binding or binding['root']!=str(context_root) or binding['batch_id']!=manifest['batch_id']:
                raise ValueError('Implicit batch context belongs to a different registered root')

def review_route(manifest,state,case_id):
    """Resolve a scoped route before admission; never downgrade invalid consent."""
    case=next(c for c in manifest['cases'] if c['case_id']==case_id)
    saved=state['cases'][case_id].get('expedited_authorization')
    if not saved:return {'stage':'review','mode':'ordinary','model':MODELS['review'][0],'effort':MODELS['review'][1],'authorization':None}
    path=no_links(saved['path'])
    if digest(path)!=saved['sha256']:raise ValueError('Scoped expedited authorization changed before model admission')
    from contracts import expedited_authorization
    record=read_json(path)
    if manifest.get('review_admission_contract')==REVIEW_ADMISSION_CONTRACT or saved.get('scope_names'):
        check_authorization_scope(manifest,case,record)
    verified=expedited_authorization(no_links(case['workspace']),record)
    if verified!=saved['verified']:raise ValueError('Scoped expedited authorization identity changed')
    return {'stage':'expedited','mode':'original-expedited','model':MODELS['expedited'][0],'effort':MODELS['expedited'][1],
            'authorization':deepcopy(saved)}

def model_ready(manifest,state,case_id):
    case=next(c for c in manifest['cases'] if c['case_id']==case_id)
    if digest(no_links(case['source_docx']))!=case['source_sha256']:raise ValueError('Registered case source changed before dispatch')
    env=state.get('environment_preflight')
    if not env or digest(no_links(env['path']))!=env['sha256']:raise ValueError('Current zero-model preflight evidence must be registered before model stage acquisition')

def prepared_review_run(case):
    workspace=no_links(case['workspace']);run=read_json(workspace/'.product-v2/run.json')
    if run.get('workspace')!=str(workspace) or not run.get('run_id'):raise ValueError('Prepared run identity required for review admission')
    return run

def ready_model_tickets(root,runnable):
    """Invalid consent/source/preflight candidates cannot hold shared capacity."""
    ready=[];batches={}
    for ticket in runnable:
        if ticket['stage'] not in MODEL_STAGES:continue
        try:
            if ticket['batch_id'] not in batches:
                target,manifest=batch(root,ticket['batch_id']);batches[ticket['batch_id']]=(manifest,read_json(target/'state.json'))
            manifest,state=batches[ticket['batch_id']];model_ready(manifest,state,ticket['case_id'])
            candidate=deepcopy(ticket)
            if state['cases'][ticket['case_id']].get('expedited_authorization') and ticket['stage']=='build':
                review_route(manifest,state,ticket['case_id'])
            if ticket['stage'] in {'review','expedited'}:
                route=review_route(manifest,state,ticket['case_id'])
                if ticket['stage']=='expedited' and route['stage']!='expedited':continue
                candidate['stage']=route['stage']
                if manifest.get('review_admission_contract')==REVIEW_ADMISSION_CONTRACT:
                    prepared_review_run(next(c for c in manifest['cases'] if c['case_id']==ticket['case_id']))
            ready.append(candidate)
        except (ValueError,OSError,KeyError,TypeError):continue
    return ready

def new_json(path,value):
    """Create immutable internal proof; never replace an admitted attempt."""
    path=no_links(path);path.parent.mkdir(parents=True,exist_ok=True);created=False
    try:
        with path.open('x',encoding='utf-8') as stream:
            created=True;json.dump(value,stream,ensure_ascii=False,indent=2);stream.write('\n');stream.flush();os.fsync(stream.fileno())
    except BaseException:
        if created:path.unlink(missing_ok=True)
        raise

def freeze_review_admission(root,target,manifest,state,entry,route):
    case=next(c for c in manifest['cases'] if c['case_id']==entry['case_id']);workspace=no_links(case['workspace'])
    run=prepared_review_run(case)
    directory=target/'review-admissions';path=directory/(entry['token']+'.json');created=[]
    admission={'schema_version':1,'contract':REVIEW_ADMISSION_CONTRACT,'root':str(no_links(root)),
        'batch_id':manifest['batch_id'],'case_id':entry['case_id'],'workspace':str(workspace),'run_id':run['run_id'],
        'token':entry['token'],'stage':route['stage'],'mode':route['mode'],'model':route['model'],'effort':route['effort'],
        'read_only':True,'owner':deepcopy(entry['owner']),'acquired_ns':entry['acquired_ns'],
        'manifest_sha256':digest(target/'manifest.json'),'source_sha256':case['source_sha256'],
        'preflight':deepcopy(state['environment_preflight']),'authorization':None}
    try:
        if route['authorization']:
            saved=route['authorization'];original=no_links(saved['path']);raw=original.read_bytes()
            if digest(original)!=saved['sha256']:raise ValueError('Expedited authorization changed while freezing admission')
            snapshot=directory/(entry['token']+'-authorization.json');snapshot.parent.mkdir(parents=True,exist_ok=True)
            with snapshot.open('xb') as stream:
                created.append(snapshot);stream.write(raw);stream.flush();os.fsync(stream.fileno())
            if digest(snapshot)!=saved['sha256']:raise ValueError('Expedited authorization changed during immutable snapshot')
            admission['authorization']={'path':str(snapshot),'sha256':digest(snapshot),'original_path':str(original),
                'original_sha256':saved['sha256'],'verified':deepcopy(saved['verified'])}
        new_json(path,admission);created.append(path)
        return {'path':str(path),'sha256':digest(path)},created
    except BaseException:
        for item in reversed(created):item.unlink(missing_ok=True)
        raise

def load_review_admission(workspace,reference):
    """Read immutable acquired route for actual dispatch/final proof binding."""
    workspace=no_links(workspace);path=no_links(reference['path'])
    if digest(path)!=reference.get('sha256'):raise ValueError('Frozen review admission changed')
    admission=read_json(path);target,manifest=batch(admission['root'],admission['batch_id'])
    case=next(c for c in manifest['cases'] if c['case_id']==admission['case_id'])
    if (admission.get('contract')!=REVIEW_ADMISSION_CONTRACT or path!=target/'review-admissions'/(admission['token']+'.json') or
        digest(target/'manifest.json')!=admission['manifest_sha256'] or case['workspace']!=str(workspace) or
        admission.get('workspace')!=str(workspace) or admission.get('run_id')!=read_json(workspace/'.product-v2/run.json')['run_id'] or
        admission.get('read_only') is not True or admission.get('stage') not in {'review','expedited'}):
        raise ValueError('Review admission belongs to a different registered case/run')
    expected=MODELS[admission['stage']]
    if [admission.get('model'),admission.get('effort')]!=expected or admission.get('mode')!=('original-expedited' if admission['stage']=='expedited' else 'ordinary'):
        raise ValueError('Frozen review admission model/route mismatch')
    pool=read_json(no_links(admission['root'])/'queue.json')
    entry=next((q for q in pool if q['token']==admission['token'] and q['batch_id']==admission['batch_id']),None)
    if not entry or entry.get('review_admission')!=reference or entry['case_id']!=admission['case_id'] or entry['stage']!=admission['stage'] or entry['status'] not in {'active','released'}:
        raise ValueError('Actual acquired review ticket must bind the immutable admission')
    if admission['source_sha256']!=case['source_sha256'] or digest(no_links(case['source_docx']))!=admission['source_sha256']:
        raise ValueError('Admitted review source changed')
    if admission['stage']=='expedited':
        auth=admission.get('authorization') or {};auth_path=no_links(auth['path'])
        if auth_path!=target/'review-admissions'/(admission['token']+'-authorization.json') or digest(auth_path)!=auth.get('sha256') or auth.get('sha256')!=auth.get('original_sha256'):
            raise ValueError('Frozen expedited admission authorization changed')
        from contracts import expedited_authorization
        record=read_json(auth_path);check_authorization_scope(manifest,case,record)
        if expedited_authorization(workspace,record)!=auth.get('verified'):raise ValueError('Frozen expedited admission consent mismatch')
    elif admission.get('authorization') is not None:raise ValueError('Ordinary admission cannot claim expedited consent')
    return admission

def load_review_dispatch_permit(workspace,admission_reference,reference):
    admission=load_review_admission(workspace,admission_reference);target,_=batch(admission['root'],admission['batch_id'])
    path=no_links(reference['path'])
    if path!=target/'review-admissions'/(admission['token']+'-dispatch.json') or digest(path)!=reference.get('sha256'):
        raise ValueError('Immutable review dispatch permit changed')
    permit=read_json(path);pool=read_json(no_links(admission['root'])/'queue.json')
    entry=next(q for q in pool if q['token']==admission['token'] and q['batch_id']==admission['batch_id'])
    if (permit.get('review_admission')!=admission_reference or entry.get('review_dispatch_permit')!=reference or
        permit.get('token')!=admission['token'] or permit.get('workspace')!=admission['workspace'] or
        permit.get('run_id')!=admission['run_id'] or permit.get('model')!=admission['model'] or permit.get('effort')!=admission['effort'] or
        not isinstance(permit.get('dispatch_nonce'),str) or len(permit['dispatch_nonce'])!=32):
        raise ValueError('Actual review dispatch permit must bind the admitted route and attempt')
    return permit

def identity(pid):
    if os.name!='nt': raise ValueError('Batch ownership identity requires Windows')
    from ctypes import wintypes
    kernel=ctypes.WinDLL('kernel32',use_last_error=True)
    kernel.OpenProcess.argtypes=[wintypes.DWORD,wintypes.BOOL,wintypes.DWORD]
    kernel.OpenProcess.restype=wintypes.HANDLE
    kernel.GetProcessTimes.argtypes=[wintypes.HANDLE]+[ctypes.POINTER(wintypes.FILETIME)]*4
    kernel.WaitForSingleObject.argtypes=[wintypes.HANDLE,wintypes.DWORD]
    kernel.WaitForSingleObject.restype=wintypes.DWORD
    kernel.CloseHandle.argtypes=[wintypes.HANDLE]
    handle=kernel.OpenProcess(0x1000|0x100000,False,int(pid))
    if not handle:
        error=ctypes.get_last_error()
        if error==87:return None # An absent PID, rather than a permission failure.
        raise ValueError('Process identity unavailable; exit is not proven (Windows error '+str(error)+')')
    try:
        waited=kernel.WaitForSingleObject(handle,0)
        if waited==0:return None
        if waited!=258:raise ValueError('Process liveness query failed; exit is not proven')
        times=[wintypes.FILETIME() for _ in range(4)]
        if not kernel.GetProcessTimes(handle,*[ctypes.byref(x) for x in times]):raise ValueError('Process creation query failed; exit is not proven')
        return {'pid':int(pid),'created_ticks':(times[0].dwHighDateTime<<32)|times[0].dwLowDateTime}
    finally:kernel.CloseHandle(handle)

@contextmanager
def transaction(root,wait_seconds=0):
    root=no_links(root);root.mkdir(parents=True,exist_ok=True);lock=root/'mutation.lock'
    deadline=time.monotonic()+wait_seconds
    while True:
        try:fd=os.open(lock,os.O_CREAT|os.O_EXCL|os.O_WRONLY);break
        except FileExistsError:
            if time.monotonic()>=deadline:raise ValueError('Batch state busy; retry after the short parent mutation completes, never delete a live lock')
            time.sleep(.03+(os.getpid()%7)*.005)
    try:os.write(fd,str(os.getpid()).encode());os.close(fd);yield
    finally:lock.unlink()

def batch(root,batch_id):
    if not batch_id or not all(c.isalnum() or c in '-_' for c in batch_id):raise ValueError('Unsafe batch ID')
    path=no_links(Path(root)/batch_id)
    return path,read_json(inside(path,'manifest.json'))

def media_binding(workspace):
    path=no_links(workspace)/'.product-v2/batch-binding.json'
    if not path.exists():return None
    binding=read_json(path);target,manifest=batch(binding['root'],binding['batch_id'])
    case=next((c for c in manifest['cases'] if c['case_id']==binding['case_id']),None)
    if (binding.get('contract')!='windows-job-v1' or manifest.get('media_lease_contract')!='windows-job-v1' or
        digest(target/'manifest.json')!=binding.get('manifest_sha256') or not case or
        str(no_links(workspace)).casefold()!=case['workspace'].casefold()):
        raise ValueError('Frozen batch/workspace media binding changed')
    return binding

def legacy_media_exit_proof(case,entry,value):
    """Explicit recovery for historical media tickets that predate Jobs.

    Require the existing exact process guard's completed cleanup, a registered
    dedicated recording runtime, and a fresh census. Never infer child exit
    solely from the parent owner PID or delete an unverified stale lock.
    """
    from process_guard import inventory,same,command_owned
    workspace=no_links(case['workspace']);binding_path=no_links(value or '')
    if workspace not in binding_path.parents or not binding_path.is_file():raise ValueError('Recovered legacy media requires a current workspace process cleanup binding')
    binding=read_json(binding_path)
    proof=workspace/'.product-v2/cleanup.json';registry_path=workspace/'.product-v2/processes.json'
    if (binding.get('workspace')!=str(workspace) or binding.get('batch_id')!=entry['batch_id'] or binding.get('token')!=entry['token'] or
        binding.get('cleanup')!={'path':str(proof),'sha256':digest(proof)} or
        binding.get('registry')!={'path':str(registry_path),'sha256':digest(registry_path)}):
        raise ValueError('Legacy cleanup must bind this exact workspace/token and unchanged cleanup/registry hashes')
    recovery_ns=entry.get('owner_recoveries',[{'at_ns':entry['acquired_ns']}])[-1]['at_ns']
    if proof.stat().st_mtime_ns<recovery_ns or binding_path.stat().st_mtime_ns<recovery_ns:
        raise ValueError('Legacy cleanup predates the current owner recovery; verify cleanup again')
    cleanup=read_json(proof);registry=read_json(registry_path)
    saved=registry.get('processes',[])
    runtimes=[row for row in saved if row.get('name','').casefold()=='node.exe' and command_owned(workspace,row.get('command','')) and
              'record.cjs' in row.get('command','').casefold() and row.get('created_ticks') and row.get('command_sha256')]
    if cleanup.get('status')!='stopped' or cleanup.get('workspace')!=str(workspace) or registry.get('workspace')!=str(workspace) or not runtimes or cleanup.get('remaining') or cleanup.get('ports_still_listening'):
        raise ValueError('Dedicated legacy media runtime and fully verified process cleanup required')
    results={row['pid']:row['status'] for row in cleanup.get('processes',[])}
    if any(results.get(row['pid']) not in {'stopped','original_exited'} for row in saved):raise ValueError('Legacy registered process cleanup is incomplete')
    rows=inventory()
    if any(same(row,current) for row in saved for current in rows) or any(command_owned(workspace,row.get('command','')) and row.get('name','').casefold() in {'node.exe','ffmpeg.exe','chrome.exe','chromium.exe'} for row in rows):
        raise ValueError('Legacy dedicated media still alive; retain reservation')
    lookup={row['pid']:row for row in rows};registered={row['pid']:row for row in saved}
    for row in rows:
        child=row;parent=child.get('parent_pid');visited=set()
        while parent and parent not in visited:
            original=registered.get(parent);current=lookup.get(parent)
            born=child.get('created_ticks',0)
            if original:
                original_born=original.get('created_ticks',0)
                # A child predating the saved process cannot belong to it. A
                # child born after a known replacement belongs to that new PID
                # lifetime. Earlier or unknown children retain the reservation.
                if not born or not original_born or born>=original_born:
                    replacement_born=current.get('created_ticks',0) if current else 0
                    if (not born or not original_born or not replacement_born or
                        replacement_born<=original_born or born<replacement_born):
                        raise ValueError('Legacy registered media descendant still alive or unproven; retain reservation')
            visited.add(parent)
            if not current:break
            parent_born=current.get('created_ticks',0)
            if born and parent_born and born<parent_born:
                # Its original parent exited before this replacement existed;
                # do not follow the unrelated replacement's current ancestry.
                break
            child=current;parent=child.get('parent_pid')
    lock=workspace/'.product-v2/recording-stage.lock'
    if lock.exists():
        original=read_json(lock)
        if original.get('pid') not in {row['pid'] for row in runtimes} or identity(original['pid']) is not None:raise ValueError('Legacy recording lock lacks an exited exact registered runtime')
        lock.unlink()
    return {'binding_sha256':digest(binding_path),'batch_id':entry['batch_id'],'token':entry['token'],
            'cleanup_sha256':digest(proof),'registry_sha256':digest(registry_path),'verified_ns':time.time_ns()}

def register(root,batch_id,case_list,authorization,host_slots=4,recording_limit=None):
    if not batch_id or not all(c.isalnum() or c in '-_' for c in batch_id):raise ValueError('Unsafe batch ID')
    if not authorization.strip():raise ValueError('Explicit confirmed-batch authorization reference required')
    if not isinstance(host_slots,int) or host_slots<2:raise ValueError('Host capacity includes parent and must leave one worker')
    if recording_limit is not None and str(recording_limit) not in {'2','3','4','auto'}:
        raise ValueError('New recording limit must be 2, 3, 4 or auto')
    profile={'capacities':dict(CAPACITIES),'host_total_slots':host_slots,'worker_capacity':host_slots-1,
             'recording_min_available_mb':4096,'recording_reserve_mb':2048}
    if recording_limit is not None:
        policy={'mode':str(recording_limit),'global_recording_limit':GLOBAL_RECORDING_LIMIT,
                'logical_processors_per_capture':4,'reserved_logical_processors':2,'max_cpu_load_percent':85}
        limit=int(recording_limit) if str(recording_limit)!='auto' else GLOBAL_RECORDING_LIMIT
        if str(recording_limit)=='auto':
            available=memory_available_mb();cpu=cpu_snapshot()
            limit=max(1,min(limit,1+max(0,available-4096)//2048,
                            max(1,(cpu['logical_processors']-2)//4)))
            policy['registration_resources']={'available_mb':available,**cpu}
        profile.update(resource_accounting='separate-model-media-v1',recording_policy=policy)
        profile['capacities']['record']=limit
    case_list=read_json(case_list)['cases'];seen=set();records=[]
    for case in case_list:
        case_id=case['case_id'];work=no_links(case['workspace']);source=no_links(case['source_docx'])
        if case_id in seen or not work.is_dir() or source.suffix.lower()!='.docx' or digest(source)!=case['source_sha256']:
            raise ValueError('Duplicate, invalid or changed registered case')
        seen.add(case_id);records.append(dict(case,workspace=str(work),source_docx=str(source)))
    if not records:raise ValueError('Confirmed case list must not be empty')
    if recording_limit is not None:
        aliases=[];counts={};reserved_ids={str(c['case_id']) for c in records}
        for case in records:
            supplied=case.get('authorization_scope_names',[])
            if not isinstance(supplied,list) or any(not isinstance(name,str) or not name.strip() for name in supplied):
                raise ValueError('Explicit authorization aliases must be nonempty names')
            names=set(supplied)
            for key in ('title','case_name'):
                if isinstance(case.get(key),str) and case[key].strip():names.add(case[key])
            run_path=no_links(case['workspace'])/'.product-v2/run.json'
            if run_path.is_file():
                run=read_json(run_path)
                if run.get('workspace')==case['workspace'] and isinstance(run.get('title'),str) and run['title'].strip():names.add(run['title'])
            aliases.append(names)
            for name in names:counts[name]=counts.get(name,0)+1
        for case,names in zip(records,aliases):
            unique={name for name in names if counts[name]==1 and (name not in reserved_ids or name==str(case['case_id'])) and
                    (name==batch_id or not (all(c.isalnum() or c in '-_' for c in name) and (no_links(no_links(root)/name)/'manifest.json').is_file()))}
            case['authorization_scope_names']=sorted({str(case['case_id']),batch_id,batch_id+'/'+str(case['case_id'])}|unique)
    with transaction(root):
        target=no_links(Path(root)/batch_id)
        if target.exists():raise ValueError('Batch manifest frozen; resume the original batch instead')
        if recording_limit is not None:
            for case in records:
                if (no_links(case['workspace'])/'.product-v2/batch-binding.json').exists():
                    raise ValueError('Workspace already has a frozen media batch binding; use a new case workspace')
        target.mkdir()
        manifest={'schema_version':2 if recording_limit is not None else 1,'batch_id':batch_id,'authorization':authorization,'cases':records,
                  'execution_profile':profile,
                  'models':MODELS,'profile':'product-v2','created_ns':time.time_ns()}
        if recording_limit is not None:
            manifest['media_lease_contract']='windows-job-v1';manifest['review_admission_contract']=REVIEW_ADMISSION_CONTRACT
        bindings=[]
        try:
            write_json(target/'manifest.json',manifest)
            write_json(target/'state.json',{'cases':{c['case_id']:{'phase':'prepared','calls':[],'usage':[],'pending':[]} for c in records},'drain':False})
            if recording_limit is not None:
                for case in records:
                    path=no_links(case['workspace'])/'.product-v2/batch-binding.json';path.parent.mkdir(parents=True,exist_ok=True)
                    binding={'contract':'windows-job-v1','root':str(no_links(root)),'batch_id':batch_id,
                             'case_id':case['case_id'],'manifest_sha256':digest(target/'manifest.json')}
                    # Cross-root concurrent registration must not replace a binding.
                    with path.open('x',encoding='utf-8') as stream:
                        bindings.append(path);json.dump(binding,stream,ensure_ascii=False,indent=2);stream.flush();os.fsync(stream.fileno())
        except BaseException:
            for path in reversed(bindings):path.unlink()
            # Only files created in this transaction's new target are removed.
            for name in ('manifest.json','state.json','manifest.json.new','state.json.new'):
                (target/name).unlink(missing_ok=True)
            target.rmdir();raise
    return manifest

def claim(root,batch_id,pid,recover=False):
    with transaction(root):
        target,_=batch(root,batch_id);owner=identity(pid)
        if not owner:raise ValueError('Live parent process identity required')
        path=target/'owner.json'
        if path.exists():
            previous=read_json(path)
            if previous!=owner and identity(previous['pid'])==previous:raise ValueError('Another live parent owns this batch; do not duplicate it')
            if previous!=owner:
                if not recover:raise ValueError('Stale owner retained; verify state then explicitly recover-owner before reclaiming')
                queue=Path(root)/'queue.json';pool=read_json(queue) if queue.exists() else []
                for ticket in pool:
                    if ticket['batch_id']==batch_id and ticket['owner']==previous and ticket['status'] in {'waiting','active'}:
                        if ticket['status']=='waiting':
                            ticket['status']='orphaned';ticket['orphaned_ns']=time.time_ns()
                        else:
                            ticket.setdefault('owner_recoveries',[]).append({'prior':previous,'new':owner,'at_ns':time.time_ns()})
                            ticket['owner']=owner
                            # Parent death never proves Node/Chromium/FFmpeg exit.
                            # Keep this exact reservation and runtime until release.
                            ticket['recovered_active']=True
                write_json(queue,pool)
                state=read_json(target/'state.json');state.setdefault('owner_recoveries',[]).append({'prior':previous,'new':owner,'at_ns':time.time_ns()});write_json(target/'state.json',state)
        write_json(path,owner);return owner

def owner_check(target,pid):
    owner=read_json(target/'owner.json')
    if owner.get('pid')!=pid or identity(pid)!=owner:raise ValueError('Only the current verified parent may mutate batch state')

def memory_available_mb():
    if os.name!='nt':raise ValueError('Recording admission requires actual physical and commit memory')
    class Memory(ctypes.Structure):
        _fields_=[('length',ctypes.c_ulong),('load',ctypes.c_ulong)]+[(name,ctypes.c_ulonglong) for name in ('total_phys','avail_phys','total_page','avail_page','total_virtual','avail_virtual','avail_extended')]
    value=Memory();value.length=ctypes.sizeof(value)
    if not ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(value)):raise ValueError('Memory query failed')
    return min(value.avail_phys,value.avail_page)//(1024*1024)

def cpu_snapshot():
    """Bounded host measurement; no external processes, service changes or busy polling."""
    if os.name!='nt':raise ValueError('Recording CPU admission requires Windows host measurements')
    from ctypes import wintypes
    def sample():
        values=[wintypes.FILETIME() for _ in range(3)]
        if not ctypes.windll.kernel32.GetSystemTimes(*[ctypes.byref(v) for v in values]):
            raise ValueError('CPU query failed')
        return [(v.dwHighDateTime<<32)|v.dwLowDateTime for v in values]
    before=sample();time.sleep(.2);after=sample()
    idle,kernel,user=[b-a for a,b in zip(before,after)];total=kernel+user
    if total<=0:raise ValueError('CPU sample has no elapsed ticks')
    return {'logical_processors':os.cpu_count() or 1,'cpu_load_percent':round(100*(total-idle)/total,2),
            'sample_seconds':.2,'measured_ns':time.time_ns()}

def active_profiles(root,manifest,active):
    """Active reservations always count, including drained or unowned batches."""
    profiles={manifest['batch_id']:manifest['execution_profile']}
    for ticket in active:
        if ticket['batch_id'] not in profiles:profiles[ticket['batch_id']]=batch(root,ticket['batch_id'])[1]['execution_profile']
    return list(profiles.values())

def admission_limits(root,manifest,active,stage):
    profiles=active_profiles(root,manifest,active)
    limit=min([GLOBAL_RECORDING_LIMIT if stage=='record' else CAPACITIES[stage]]+
              [p['capacities'][stage] for p in profiles])
    legacy=[p for p in profiles if p.get('resource_accounting')!='separate-model-media-v1']
    if legacy and len(active)>=min(p['worker_capacity'] for p in legacy):
        return limit,False
    if stage in MODEL_STAGES:
        workers=min(p['worker_capacity'] for p in profiles)
        if sum(q['stage'] in MODEL_STAGES for q in active)>=workers:return limit,False
    return limit,True

def recording_resources(profile,count):
    required=4096+2048*(count-1);available=memory_available_mb()
    result={'available_mb':available,'required_mb':required,'capture_count':count}
    if available<required:return {'acquired':False,'reason':'memory_exhausted',**result}
    policy=profile.get('recording_policy')
    if policy:
        cpu=cpu_snapshot();result.update(cpu)
        processors=policy['reserved_logical_processors']+policy['logical_processors_per_capture']*count
        result['required_logical_processors']=processors
        if cpu['logical_processors']<processors:return {'acquired':False,'reason':'cpu_capacity',**result}
        if cpu['cpu_load_percent']>policy['max_cpu_load_percent']:return {'acquired':False,'reason':'cpu_busy',**result}
    return {'acquired':True,**result}

def runnable_waiting(root,pool):
    """Paused/unowned waiting tickets retain history without blocking other batches."""
    batches={};result=[]
    for ticket in pool:
        if ticket['status']!='waiting':continue
        if ticket.get('capacity_retry',{}).get('not_before_ns',0)>time.time_ns():continue
        batch_id=ticket['batch_id']
        if batch_id not in batches:
            target,_=batch(root,batch_id);state=read_json(target/'state.json')
            owner_path=target/'owner.json';owner=read_json(owner_path) if owner_path.exists() else None
            if owner and identity(owner['pid'])!=owner:owner=None
            batches[batch_id]=(state,owner)
        state,owner=batches[batch_id];case=state['cases'].get(ticket['case_id'])
        if not state['drain'] and case and case.get('phase') not in {'blocked','delivered'} and owner and ticket['owner']==owner:
            result.append(ticket)
    return result

def capacity_failure(entry,manifest,state,value):
    """A real failed spawn or a proven terminal child may release a model slot."""
    from contracts import SESSION_ROOT
    request=read_json(no_links(value));path=no_links(request['session_log'])
    if no_links(SESSION_ROOT) not in path.parents or path.suffix!='.jsonl':
        raise ValueError('Capacity defer requires actual Codex session JSONL')
    call_id=request['call_id'];calls=[];outputs=[];meta=[];events=[]
    with path.open('rb') as stream:
        for raw in stream:
            try:event=json.loads(raw)
            except (ValueError,UnicodeDecodeError):continue
            payload=event.get('payload',{})
            events.append(event)
            if event.get('type')=='session_meta':meta.append(payload)
            if event.get('type')!='response_item' or payload.get('call_id')!=call_id:continue
            if payload.get('type')=='function_call':calls.append((payload,raw))
            if payload.get('type')=='function_call_output':outputs.append((payload,raw))
    if len(meta)!=1 or len(calls)!=1 or len(outputs)!=1:raise ValueError('One actual failed model dispatch call/output required')
    if not path.name.endswith('-'+str(meta[0].get('id'))+'.jsonl'):raise ValueError('Capacity session filename identity mismatch')
    call,raw_call=calls[0];output,raw_output=outputs[0];args=json.loads(call.get('arguments','{}'))
    kind=entry.get('model_kind') or ('repair' if entry['stage']=='build' and state['cases'][entry['case_id']].get('phase')=='repairing' else entry['stage'])
    model,effort=MODELS[kind]
    if (call.get('name','').split('.')[-1]!='spawn_agent' or args.get('fork_turns')!='none' or
        [args.get('model'),args.get('reasoning_effort')]!=[model,effort]):
        raise ValueError('Capacity failure must retain the exact admitted model/effort')
    case=next(c for c in manifest['cases'] if c['case_id']==entry['case_id'])
    message=args.get('message','')
    if not isinstance(message,str) or entry['token'] not in message or str(case['workspace']).casefold() not in message.casefold():
        raise ValueError('Capacity dispatch must name this exact token and workspace')
    result=output.get('output');text=result if isinstance(result,str) else json.dumps(result)
    try:parsed=json.loads(text)
    except ValueError:parsed=None
    child_proof=None
    if isinstance(parsed,dict) and parsed.get('task_name'):
        # A spawned child may terminate immediately or midway. Its last actual
        # lifecycle and the parent's latest actual agent census must BOTH prove
        # the same terminal overload; a message or caller's status is not proof.
        child=no_links(request['child_session_log']);child_events=[]
        if no_links(SESSION_ROOT) not in child.parents or child.suffix!='.jsonl':raise ValueError('Actual child session JSONL required')
        with child.open('rb') as stream:
            for raw in stream:
                try:child_events.append(json.loads(raw))
                except (ValueError,UnicodeDecodeError):continue
        child_meta=[e['payload'] for e in child_events if e.get('type')=='session_meta']
        if len(child_meta)!=1 or not child.name.endswith('-'+str(child_meta[0].get('id'))+'.jsonl'):raise ValueError('Child session identity mismatch')
        spawn=child_meta[0].get('source',{}).get('subagent',{}).get('thread_spawn',{})
        if spawn.get('agent_path')!=parsed['task_name'] or spawn.get('parent_thread_id')!=meta[0]['id']:raise ValueError('Capacity child belongs to another parent/dispatch')
        lifecycle=[e for e in child_events if e.get('type')=='event_msg' and e.get('payload',{}).get('type') in {'task_started','task_complete'}]
        terminal=lifecycle[-1] if lifecycle else {}
        error=terminal.get('payload',{}).get('error') or {}
        if terminal.get('payload',{}).get('type')!='task_complete' or error.get('codex_error_info')!='server_overloaded' or 'Selected model is at capacity' not in error.get('message',''):
            raise ValueError('Child is live, resumed, or has no terminal capacity error')
        contexts=[e['payload'] for e in child_events if e.get('type')=='turn_context']
        if not contexts or [contexts[-1].get('model'),contexts[-1].get('effort')]!=[model,effort]:raise ValueError('Child terminal model differs from admitted route')
        pending={};census=None;census_index=-1
        for index,event in enumerate(events):
            p=event.get('payload',{})
            if event.get('type')!='response_item':continue
            if p.get('type')=='function_call':pending[p['call_id']]=p
            if p.get('type')!='function_call_output':continue
            actual=pending.get(p.get('call_id'),{})
            if actual.get('name','').split('.')[-1]!='list_agents':continue
            try:rows=json.loads(p['output']) if isinstance(p['output'],str) else p['output']
            except ValueError:continue
            census=(rows,event);census_index=index
        rows,census_event=census if census else ({}, {})
        found=[row for row in rows.get('agents',[]) if row.get('agent_name')==parsed['task_name']]
        if len(found)!=1 or not isinstance(found[0].get('agent_status'),dict) or 'Selected model is at capacity' not in found[0]['agent_status'].get('errored','') or census_event.get('timestamp','')<terminal.get('timestamp',''):
            raise ValueError('Latest real agent census must prove this child terminal capacity error')
        for event in events[census_index+1:]:
            p=event.get('payload',{})
            if p.get('type')!='function_call' or p.get('name','').split('.')[-1] not in {'followup_task','send_message'}:continue
            try:resumed=json.loads(p.get('arguments','{}'))
            except ValueError:continue
            if resumed.get('target') in {parsed['task_name'],parsed['task_name'].rsplit('/',1)[-1]}:raise ValueError('Child received a later continuation; preserve its reservation')
        child_proof={'session_log':str(child),'terminal':terminal,'census':census_event}
    elif (isinstance(parsed,dict) and any(parsed.get(key) for key in ('agent_id','thread_id'))) or 'Selected model is at capacity' not in text:
        raise ValueError('Only actual capacity failure can defer; preserve spawned child reservations')
    import hashlib
    return {'session_log':str(path),'call_id':call_id,'model':model,'effort':effort,
            'events_sha256':hashlib.sha256(raw_call+raw_output).hexdigest(),'child_terminal':child_proof}

def defer_capacity(root,target,manifest,state,pool,entry,pid,value):
    """One atomic queue replacement; repeat calls return the same waiting ticket."""
    proof=capacity_failure(entry,manifest,state,value)
    existing=next((q for q in pool if q.get('capacity_retry',{}).get('failed_token')==entry['token']),None)
    if existing:
        old=existing['capacity_retry']['proof']
        if any(old[key]!=proof[key] for key in ('session_log','call_id','model','effort','events_sha256')):raise ValueError('Different capacity failure cannot reuse an already deferred attempt')
        return existing
    if entry['status']!='active' or entry['stage'] not in MODEL_STAGES or entry['owner']!=identity(pid):
        raise ValueError('Current own active model slot required for capacity defer')
    if any(q['batch_id']==entry['batch_id'] and q['case_id']==entry['case_id'] and q['status'] in {'active','waiting'} and q['token']!=entry['token'] for q in pool):
        raise ValueError('Case already has another current attempt')
    attempts=1+entry.get('capacity_retry',{}).get('attempts',0);seconds=min(300,30*2**min(attempts-1,4));now=time.time_ns()
    retry={'failed_token':entry['token'],'attempts':attempts,'not_before_ns':now+seconds*1_000_000_000,
           'cooldown_seconds':seconds,'proof':proof}
    waiting={'token':uuid.uuid4().hex,'batch_id':entry['batch_id'],'case_id':entry['case_id'],'stage':entry['stage'],
             'status':'waiting','priority':entry['priority'],'submitted_ns':max(now,1+max(q['submitted_ns'] for q in pool)),
             'owner':identity(pid),'capacity_retry':retry,'model':proof['model'],'effort':proof['effort']}
    if entry.get('model_kind'):waiting['model_kind']=entry['model_kind']
    if entry.get('authorization'):waiting['authorization']=deepcopy(entry['authorization'])
    entry.update(status='released',released_ns=now,release_reason='model_capacity',capacity_failure=proof)
    pool.append(waiting)
    # Queue is the authoritative retry journal: one atomic replace makes release
    # and requeue inseparable, including if the process dies before returning.
    write_json(no_links(root)/'queue.json',pool)
    return waiting

def mutate(root,batch_id,pid,action,case_id=None,value=None,token=None,stage=None,authorization=None,runtime_pid=None):
    # Concurrent Node captures can perform launch checks together. Wait only for
    # this exact short-lived lock contention, never remove or steal a live lock.
    with transaction(root,wait_seconds=3 if action in {'verify-record','verify-evidence','bind-media-runtime','verify-review','release-slot','defer-capacity'} else 0):
        target,manifest=batch(root,batch_id);owner_check(target,pid);state=read_json(target/'state.json')
        if case_id is not None and case_id not in state['cases']:raise ValueError('Control is restricted to this batch registered cases')
        if action in {'configure-scheduler','bind-controller','bind-repair'}:
            from scheduler_policy import control
            pool=read_json(Path(root)/'queue.json') if (Path(root)/'queue.json').exists() else []
            return control(root,target,manifest,pid,action,value,authorization,pool,case_id)
        elif action=='preflight':
            path=no_links(value);proof=read_json(path);checks=proof.get('checks',[])
            if proof.get('status')!='ready' or proof.get('zero_model_calls')!=0 or not {'workspace_write','read_only','browser','word_render'}.issubset({c.get('kind') for c in checks}):
                raise ValueError('Real zero-model constrained execution/browser/Word checks required')
            for check in checks:
                log=no_links(check['log'])
                if check.get('exit_code')!=0 or not check.get('command') or not log.is_file() or not log.stat().st_size or digest(log)!=check.get('sha256'):
                    raise ValueError('Actual preflight command/log/hash required')
            state.setdefault('preflight_history',[]).append(state.get('environment_preflight'))
            state['environment_preflight']={'path':str(path),'sha256':digest(path),'registered_ns':time.time_ns()}
        elif action=='release-owner':
            pool=read_json(Path(root)/'queue.json') if (Path(root)/'queue.json').exists() else []
            if any(q['batch_id']==batch_id and q['status']=='active' for q in pool):raise ValueError('Release stage slots first')
            (target/'owner.json').unlink();return {'released':True}
        elif action in {'drain','continue'}:
            if not authorization:raise ValueError('Drain/continue require the existing explicit user pause or maintenance request reference')
            state['drain']=action=='drain';state['control_authorization']=authorization
        elif action in {'priority','resume-case','expedite','update'}:
            if not case_id:raise ValueError('Use explicit case_id; loop the confirmed list for batch-wide controls')
            item=state['cases'][case_id]
            if action=='priority':
                item['priority']=int(value)
                queue=Path(root)/'queue.json';pool=read_json(queue) if queue.exists() else []
                for ticket in pool:
                    if ticket['batch_id']==batch_id and ticket['case_id']==case_id and ticket['status']=='waiting':ticket['priority']=item['priority']
                write_json(queue,pool)
            elif action=='expedite':
                if not authorization:raise ValueError('Explicit original expedited-mode authorization required; speed alone is insufficient')
                path=no_links(authorization);record=read_json(path)
                from contracts import expedited_authorization
                case=next(c for c in manifest['cases'] if c['case_id']==case_id)
                check_authorization_scope(manifest,case,record)
                verified=expedited_authorization(no_links(case['workspace']),record)
                item['expedited_authorization']={'path':str(path),'sha256':digest(path),'verified':verified,
                                               'scope_names':authorization_scope_names(manifest,case)}
                item['priority']=10
                queue=Path(root)/'queue.json';pool=read_json(queue) if queue.exists() else []
                for ticket in pool:
                    if ticket['batch_id']==batch_id and ticket['case_id']==case_id and ticket['status']=='waiting':
                        ticket['priority']=10
                        if ticket['stage'] in {'review','expedited'}:
                            ticket['stage']='expedited';ticket['route_changed_ns']=time.time_ns();ticket['authorization']=deepcopy(item['expedited_authorization'])
                write_json(queue,pool)
            elif action=='resume-case':
                evidence=no_links(value);ready=read_json(evidence)
                if ready.get('status')!='ready' or not ready.get('recovery_evidence') or ready.get('blocked_fingerprint')!=item.get('blocked_fingerprint'):
                    raise ValueError('New actual recovery evidence tied to the current blocker required')
                recovery=ready['recovery_evidence']
                if not isinstance(recovery,list) or not recovery:raise ValueError('Recovery evidence needs actual path/hash records')
                for proof in recovery:
                    path=no_links(proof['path'])
                    if not path.is_file() or not path.stat().st_size or digest(path)!=proof.get('sha256'):
                        raise ValueError('Actual new recovery evidence hash/path changed or missing')
                item['recovery']={'path':str(evidence),'sha256':digest(evidence)};item['phase']='prepared'
            else:
                update=read_json(value)
                if update.get('phase') not in {'prepared','building','repairing','waiting_record','recording','waiting_review','reviewing','blocked','delivered'}:
                    raise ValueError('Unknown case phase')
                if update['phase']=='delivered':
                    case=next(c for c in manifest['cases'] if c['case_id']==case_id)
                    receipt=read_json(inside(case['workspace'],'.product-v2/final-receipt.json'))
                    if receipt.get('status')!='complete':raise ValueError('Final current receipt required before delivered')
                    if receipt.get('delivery_state')=='verified-candidate':
                        published=read_json(inside(case['workspace'],'.product-v2/publish-receipt.json'))
                        if published.get('status')!='published' or published.get('files')!=receipt['files']:raise ValueError('Atomic publication receipt required before delivered')
                for key in ('calls','usage'):item.setdefault(key,[]).extend(update.pop(key,[]))
                item.update(update)
        elif action in {'queue','acquire','release-slot','defer-capacity','verify-record','verify-evidence','bind-media-runtime','verify-review'}:
            queue_path=Path(root)/'queue.json';pool=read_json(queue_path) if queue_path.exists() else []
            admission_files=[]
            if action=='queue':
                if stage not in CAPACITIES or not case_id:raise ValueError('Explicit stage and registered case required')
                route=None
                if stage in {'review','expedited'}:
                    route=review_route(manifest,state,case_id)
                    if stage=='expedited' and route['stage']!='expedited':raise ValueError('Unscoped expedited route refused')
                    stage=route['stage']
                owned=[q for q in pool if q['batch_id']==batch_id and q['case_id']==case_id and q['status'] in {'waiting','active'}]
                if owned:
                    raise ValueError('Case already owns or waits for a stage; release it before queueing the next capture/evidence phase')
                # Windows clocks can return the same tick (or move backwards).
                # Allocate a strictly increasing submission value under this
                # shared lock; never rewrite existing or recovered ticket order.
                submitted=max(time.time_ns(),1+max((q['submitted_ns'] for q in pool),default=0))
                entry={'token':uuid.uuid4().hex,'batch_id':batch_id,'case_id':case_id,'stage':stage,'status':'waiting',
                       'priority':state['cases'][case_id].get('priority',0),'submitted_ns':submitted,'owner':identity(pid)}
                if route and route['authorization']:entry['authorization']=deepcopy(route['authorization'])
                pool.append(entry);write_json(queue_path,pool);return entry
            matching=[q for q in pool if q['token']==token and q['batch_id']==batch_id]
            if len(matching)!=1:raise ValueError('Slot token does not belong to this batch')
            entry=matching[0]
            if action=='defer-capacity':
                if case_id!=entry['case_id']:raise ValueError('Capacity attempt belongs to a different registered case')
                return defer_capacity(root,target,manifest,state,pool,entry,pid,value)
            elif action=='verify-review':
                if entry['status']!='active' or entry['stage'] not in {'review','expedited'} or entry['owner']!=identity(pid):
                    raise ValueError('Current active review lease required immediately before actual model dispatch')
                if case_id!=entry['case_id']:raise ValueError('Review lease belongs to a different registered case')
                case=next(c for c in manifest['cases'] if c['case_id']==case_id)
                if str(no_links(value)).casefold()!=case['workspace'].casefold():raise ValueError('Review lease belongs to a different workspace')
                model_ready(manifest,state,case_id)
                if manifest.get('review_admission_contract')==REVIEW_ADMISSION_CONTRACT:
                    admission=load_review_admission(case['workspace'],entry['review_admission'])
                    if admission['stage']=='expedited':
                        auth=admission['authorization'];original=no_links(auth['original_path'])
                        if digest(original)!=auth['original_sha256']:raise ValueError('Expedited authorization changed before actual model dispatch')
                        from contracts import expedited_authorization
                        if expedited_authorization(no_links(case['workspace']),read_json(original))!=auth['verified']:raise ValueError('Expedited authorization changed before actual model dispatch')
                    if entry.get('review_dispatch_permit'):
                        permit=load_review_dispatch_permit(case['workspace'],entry['review_admission'],entry['review_dispatch_permit'])
                    else:
                        path=target/'review-admissions'/(token+'-dispatch.json')
                        permit={'schema_version':1,'review_admission':entry['review_admission'],'token':token,
                                'workspace':admission['workspace'],'run_id':admission['run_id'],'model':admission['model'],'effort':admission['effort'],
                                'dispatch_nonce':uuid.uuid4().hex,'issued_ns':time.time_ns(),'owner':identity(pid)}
                        new_json(path,permit);entry['review_dispatch_permit']={'path':str(path),'sha256':digest(path)}
                        try:write_json(queue_path,pool)
                        except BaseException:path.unlink(missing_ok=True);raise
                    return {'verified':True,'review_admission':entry['review_admission'],'review_dispatch_permit':entry['review_dispatch_permit'],
                            'dispatch_nonce':permit['dispatch_nonce'],'route':admission['mode'],'model':admission['model'],'effort':admission['effort'],'token':token}
                # Legacy manifests have no immutable admission proof. Revalidate
                # scoped consent without rewriting an already active route.
                if entry['stage']=='expedited':
                    route=review_route(manifest,state,case_id)
                    if route['stage']!='expedited':raise ValueError('Legacy expedited authorization unavailable')
                return {'verified':True,'legacy_admission':True,'model':MODELS[entry['stage']][0],'effort':MODELS[entry['stage']][1],'token':token}
            elif action in {'verify-record','verify-evidence','bind-media-runtime'}:
                required='record' if action=='verify-record' else ('evidence' if action=='verify-evidence' else stage)
                if required not in {'record','evidence'} or entry['status']!='active' or entry['stage']!=required or entry['owner']!=identity(pid):
                    raise ValueError('Current active '+str(required)+' lease required before media launch')
                case=next(c for c in manifest['cases'] if c['case_id']==entry['case_id'])
                runtime=read_json(value) if action=='bind-media-runtime' else None
                workspace=runtime['workspace'] if runtime else value
                if case_id!=entry['case_id'] or str(no_links(workspace)).casefold()!=case['workspace'].casefold():
                    raise ValueError('Media lease belongs to a different case/workspace')
                if manifest.get('media_lease_contract')=='windows-job-v1':
                    binding=media_binding(workspace)
                    if not binding or binding['root']!=str(no_links(root)) or binding['batch_id']!=batch_id or binding['case_id']!=case_id:
                        raise ValueError('Frozen media batch binding required')
                if digest(no_links(case['source_docx']))!=case['source_sha256']:raise ValueError('Registered case source changed before capture')
                active=[q for q in pool if q['status']=='active']
                if required=='record' and any(q['stage']=='evidence' for q in active):raise ValueError('Heavy evidence cannot overlap live capture')
                if required=='evidence' and (any(q['stage']=='record' for q in active) or sum(q['stage']=='evidence' for q in active)!=1):
                    raise ValueError('Active evidence lease requires global media exclusion')
                if action=='bind-media-runtime':
                    from media_job import job_name,job_pids,verify_runtime_command
                    if entry.get('media_runtime'):raise ValueError('Media lease already has a runtime; release it before retrying')
                    expected=job_name(root,batch_id,token)
                    if runtime.get('job_name')!=expected or identity(runtime['pid'])!=runtime.get('identity') or runtime['pid'] not in job_pids(expected):
                        raise ValueError('Exact live media runtime must belong to the reserved Windows Job')
                    runtime['command_proof']=verify_runtime_command(runtime)
                    entry['media_runtime']=runtime;write_json(queue_path,pool);return entry
                if runtime_pid is not None and manifest.get('media_lease_contract')=='windows-job-v1':
                    from media_job import verify_membership
                    verify_membership(workspace,token,runtime_pid)
                result=recording_resources(manifest['execution_profile'],sum(q['stage']=='record' for q in active)) if required=='record' else {'acquired':True}
                entry.setdefault('launch_checks',[]).append({'at_ns':time.time_ns(),**result});write_json(queue_path,pool)
                return {**result,'token':entry['token'],'case_id':entry['case_id'],'workspace':case['workspace']}
            elif action=='release-slot':
                if entry['status'] not in {'waiting','active'}:raise ValueError('Only a current waiting or active ticket can release')
                if entry['status']=='active' and entry['stage'] in {'record','evidence'}:
                    if manifest.get('media_lease_contract')=='windows-job-v1':
                        from media_job import job_name,job_pids
                        live=job_pids(job_name(root,batch_id,token))
                        runtime=entry.get('media_runtime')
                        if live or (runtime and identity(runtime['pid'])==runtime['identity']):
                            raise ValueError('Media runtime still alive; keep the active reservation until its Job exits')
                        lock=no_links(next(c for c in manifest['cases'] if c['case_id']==entry['case_id'])['workspace'])/'.product-v2/recording-stage.lock'
                        if lock.exists():
                            original=read_json(lock)
                            if not runtime or original.get('pid')!=runtime['pid'] or identity(runtime['pid']) is not None:
                                raise ValueError('Recording lock differs from the exited reserved runtime; preserve it')
                            entry['stale_recording_lock']={'sha256':digest(lock),'runtime_identity':runtime['identity'],'cleared_ns':time.time_ns()};lock.unlink()
                    elif entry.get('recovered_active'):
                        case=next(c for c in manifest['cases'] if c['case_id']==entry['case_id'])
                        entry['legacy_media_exit_proof']=legacy_media_exit_proof(case,entry,value)
                entry['status']='released';entry['released_ns']=time.time_ns()
            else:
                if state['drain']:return {'acquired':False,'reason':'authorized drain at stage boundary'}
                if entry['status']!='waiting':raise ValueError('Only waiting tickets can acquire')
                if entry.get('capacity_retry',{}).get('not_before_ns',0)>time.time_ns():
                    return {'acquired':False,'reason':'same-model capacity cooldown','token':token,
                            'retry':deepcopy(entry['capacity_retry']),'model':entry['model'],'effort':entry['effort']}
                case=next(c for c in manifest['cases'] if c['case_id']==entry['case_id'])
                if digest(no_links(case['source_docx']))!=case['source_sha256']:raise ValueError('Registered case source changed before dispatch')
                route=None
                if entry['stage'] in {'review','expedited'}:
                    route=review_route(manifest,state,entry['case_id'])
                    if entry['stage']=='expedited' and route['stage']!='expedited':raise ValueError('Unscoped expedited route refused')
                    if entry['stage']!=route['stage']:
                        entry['stage']=route['stage'];entry['route_changed_ns']=time.time_ns()
                    if route['authorization']:entry['authorization']=deepcopy(route['authorization'])
                    if manifest.get('review_admission_contract')==REVIEW_ADMISSION_CONTRACT:prepared_review_run(case)
                if entry['stage'] in MODEL_STAGES:
                    model_ready(manifest,state,entry['case_id'])
                    if entry['stage']=='build' and state['cases'][entry['case_id']].get('expedited_authorization'):
                        review_route(manifest,state,entry['case_id'])
                active=[q for q in pool if q['status']=='active'];runnable=runnable_waiting(root,pool)
                if entry not in runnable:return {'acquired':False,'reason':'waiting ticket has no runnable case or current owner'}
                ready_models=ready_model_tickets(root,runnable)
                eligible=ready_models if entry['stage'] in MODEL_STAGES else runnable
                waiting=sorted((q for q in eligible if q['stage']==entry['stage']),key=lambda q:(-q['priority'],q['submitted_ns'],q['token']))
                limit,host_available=admission_limits(root,manifest,active,entry['stage'])
                from scheduler_policy import config as scheduler_config,FAIR_MODES,ADAPTIVE_CONTRACT,choose as choose_model
                scheduling=scheduler_config(root);group=None;fair_models=entry['stage'] in MODEL_STAGES and scheduling.get('mode') in FAIR_MODES
                if entry['stage']=='evidence' and any(q['stage']=='record' for q in active):
                    return {'acquired':False,'reason':'live capture must finish before heavy media evidence'}
                if entry['stage']=='record' and any(q['stage']=='evidence' for q in active+runnable):
                    next_evidence=min((q for q in active+runnable if q['stage']=='evidence'),key=lambda q:(q['status']!='active',-q['priority'],q['submitted_ns'],q['token']))
                    return {'acquired':False,'reason':'queued evidence drains live capture group before new recording',
                            'selected':{key:next_evidence[key] for key in ('token','batch_id','case_id','stage','owner')}}
                if entry['stage']=='record':
                    for live in (q for q in active if q['stage']=='record'):
                        _,live_manifest=batch(root,live['batch_id'])
                        live_case=next(c for c in live_manifest['cases'] if c['case_id']==live['case_id'])
                        if (manifest['schema_version']>=2 or live_manifest['schema_version']>=2) and live_case['workspace'].lower()==case['workspace'].lower():
                            return {'acquired':False,'reason':'case_workspace_busy'}
                if fair_models:
                    chosen,group=choose_model(root,ready_models,active,pool,scheduling)
                    if not chosen or chosen['token']!=entry['token']:
                        selected=None
                        if chosen:
                            selected_model=MODELS[chosen.get('model_kind',chosen['stage'])]
                            selected={key:chosen[key] for key in ('token','batch_id','case_id','stage','owner')}
                            selected.update(work_kind=chosen.get('work_kind','build'),model=selected_model[0],effort=selected_model[1],reason='current eligible class, work kind, group and batch turn')
                            selected.update(model_kind=chosen.get('model_kind',chosen['stage']),
                                            lane=chosen.get('scheduler_lane',chosen.get('work_kind',chosen['stage'])),
                                            action='selected_owner_acquire_then_dispatch',
                                            requester_can_acquire=chosen['batch_id']==batch_id and chosen['owner']==identity(pid))
                        return {'acquired':False,'reason':'fair eligible model queue or controller/stage capacity',
                                'priority_token':chosen['token'] if chosen else None,'selected':selected}
                elif entry['stage'] in MODEL_STAGES:
                    for candidate in sorted((q for q in ready_models if q['priority']>entry['priority']),key=lambda q:(-q['priority'],q['submitted_ns'],q['token'])):
                        _,candidate_manifest=batch(root,candidate['batch_id'])
                        candidate_limit,candidate_host=admission_limits(root,candidate_manifest,active,candidate['stage'])
                        if candidate_host and sum(q['stage']==candidate['stage'] for q in active)<candidate_limit:
                            return {'acquired':False,'reason':'runnable higher-priority model stage has priority on shared model capacity','priority_token':candidate['token']}
                if not fair_models and (not host_available or sum(q['stage']==entry['stage'] for q in active)>=limit or not waiting or waiting[0]['token']!=entry['token']):
                    selected=None
                    if entry['stage'] in {'record','evidence'} and waiting:
                        selected={key:waiting[0][key] for key in ('token','batch_id','case_id','stage','owner')}
                    return {'acquired':False,'reason':'fair queue or host capacity','selected':selected}
                if entry['stage']=='record':
                    resources=recording_resources(manifest['execution_profile'],1+sum(q['stage']=='record' for q in active))
                    entry['memory_available_mb']=resources['available_mb'];entry['memory_required_mb']=resources['required_mb']
                    entry['admission_resources']={'at_ns':time.time_ns(),**resources}
                    if not resources['acquired']:
                        write_json(queue_path,pool);return resources
                entry['status']='active';entry['acquired_ns']=time.time_ns();entry['slot_wait_seconds']=(entry['acquired_ns']-entry['submitted_ns'])/1e9
                if entry['stage'] in MODEL_STAGES:
                    # Shared-lock sequence preserves adaptive fairness when the
                    # Windows wall clock repeats or moves backwards. Historical
                    # tickets are never rewritten, including after rollback.
                    entry['scheduler_turn']=1+max((q.get('scheduler_turn',0) for q in pool),default=0)
                if entry.get('capacity_retry'):
                    kind='repair' if entry['stage']=='build' and state['cases'][entry['case_id']].get('phase')=='repairing' else entry['stage']
                    if [entry['model'],entry['effort']]!=MODELS[kind]:raise ValueError('Capacity retry route changed; exact same model/effort required')
                if fair_models:
                    entry['scheduler_admission']={'contract':scheduling['mode'],'group':group,'capacities':deepcopy(scheduling['capacities']),
                                                  'work_kind':chosen.get('work_kind','build'),'repair_extra_capacity':scheduling.get('repair_extra_capacity',0)}
                    if scheduling['mode']==ADAPTIVE_CONTRACT:
                        entry['scheduler_admission'].update(lane=chosen['scheduler_lane'],aged=chosen['scheduler_aged'],
                                                            fixed_stage_quotas=False,repair_extra_budget_used=False)
                    if chosen.get('repair_binding'):
                        entry['scheduler_admission']['repair_binding']=deepcopy(chosen['repair_binding'])
                        entry['work_kind']='repair'
                    if chosen.get('model_kind')=='repair':
                        entry['model_kind']='repair';entry['model'],entry['effort']=MODELS['repair']
                if route and manifest.get('review_admission_contract')==REVIEW_ADMISSION_CONTRACT:
                    entry['review_admission'],admission_files=freeze_review_admission(root,target,manifest,state,entry,route)
            try:write_json(queue_path,pool)
            except BaseException:
                for path in reversed(admission_files):path.unlink(missing_ok=True)
                raise
            return entry
        else:raise ValueError('Unsupported mutation')
        write_json(target/'state.json',state);return state

def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('action',choices=['register','claim','recover-owner','status','preflight','release-owner','priority','resume-case','expedite','drain','continue','update','queue','acquire','release-slot','defer-capacity','verify-record','verify-evidence','bind-media-runtime','verify-review','configure-scheduler','bind-controller','bind-repair'],help='Scheduling controls require --value JSON and --authorization; bind-repair value names case_id and authenticates actual revise evidence; config affects future acquire only')
    p.add_argument('--root',required=True);p.add_argument('--batch-id',required=True);p.add_argument('--pid',type=int);p.add_argument('--cases');p.add_argument('--authorization');p.add_argument('--host-slots',type=int,default=4);p.add_argument('--recording-limit',choices=['2','3','4','auto'],default='auto');p.add_argument('--case-id');p.add_argument('--value');p.add_argument('--token');p.add_argument('--stage');p.add_argument('--runtime-pid',type=int)
    a=p.parse_args()
    try:
        if a.action=='register':result=register(a.root,a.batch_id,a.cases,a.authorization or '',a.host_slots,a.recording_limit)
        elif a.action in {'claim','recover-owner'}:result=claim(a.root,a.batch_id,a.pid,a.action=='recover-owner')
        elif a.action=='status':
            from scheduler_policy import config as scheduler_config,ADAPTIVE_CONTRACT,DEFAULT_AGING_SECONDS,model_pool_capacity,snapshot as scheduler_snapshot
            path,manifest=batch(a.root,a.batch_id);result={'manifest':manifest,'state':read_json(path/'state.json'),'scheduler':scheduler_config(a.root)}
            if result['scheduler'].get('mode')==ADAPTIVE_CONTRACT:
                result['scheduler_runtime_policy']={'sharing':'verified-live-parent-local',
                    'model_pool_capacity':model_pool_capacity(result['scheduler']),
                    'max_model_children_per_parent':'verified runtime capacity; legacy evidence fallback',
                    'fixed_group_quotas':False,'fixed_stage_quotas':False,'repair_extra_budget_used':False,
                    'lanes':['review','repair','build'],'aging_seconds':result['scheduler'].get('aging_seconds',DEFAULT_AGING_SECONDS),
                    'selection_action':'selected owner acquires original token and dispatches; no cross-owner acquisition',
                    'capacity_scope':'reservation ceilings only; actual model service availability remains external'}
            queue_path=no_links(a.root)/'queue.json';pool=read_json(queue_path) if queue_path.exists() else []
            if result['scheduler'].get('mode')==ADAPTIVE_CONTRACT:
                result['scheduler_reservations']=scheduler_snapshot(a.root,pool,result['scheduler'])
            result['current_tickets']=[q for q in pool if q['batch_id']==a.batch_id and q['status'] in {'waiting','active'}]
        else:result=mutate(a.root,a.batch_id,a.pid,a.action,a.case_id,a.value,a.token,a.stage,a.authorization,a.runtime_pid)
        print(json.dumps(result,ensure_ascii=False,indent=2));return 0
    except (ValueError,OSError,KeyError,TypeError) as e:print('ERROR: '+str(e));return 2

if __name__=='__main__':raise SystemExit(main())
