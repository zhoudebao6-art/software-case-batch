"""Real process contention; media is an isolated fixture, never a recording."""
from contextlib import redirect_stdout
from concurrent.futures import ThreadPoolExecutor
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
import batch_control as batch
import progress_driver as progress
from common import digest,read_json,write_json


PROCESS=r'''
import json,os,sys,time
from pathlib import Path
sys.path.insert(0,sys.argv[1])
import batch_control as batch
import progress_driver as progress
from common import digest,read_json,write_json
mode,root,owner,case_id=sys.argv[2:6];root=Path(root);owner=int(owner)
if mode=='hold':
    with batch.transaction(root):
        print('LOCKED',flush=True);time.sleep(float(sys.argv[6]))
elif mode in {'queue','acquire'}:
    batch.memory_available_mb=lambda:24000
    batch.cpu_snapshot=lambda:{'logical_processors':32,'cpu_load_percent':20}
    result=(batch.mutate(root,'b',owner,'queue',case_id,stage='record') if mode=='queue'
            else batch.mutate(root,'b',owner,'acquire',token=sys.argv[6]))
    print(json.dumps(result),flush=True)
elif mode=='drive':
    import media_job
    media_job.job_pids=lambda name:[]
    batch.memory_available_mb=lambda:24000
    batch.cpu_snapshot=lambda:{'logical_processors':32,'cpu_load_percent':20}
    _,manifest=batch.batch(root,'b');work=Path(next(c for c in manifest['cases'] if c['case_id']==case_id)['workspace'])
    events=root/'fixture-media-events.txt'
    def execute(work,phase,lease,plan,log,timeout):
        with events.open('a',encoding='utf-8') as stream:stream.write(phase+'\n')
        log.write_text('isolated fixture only')
        if phase=='capture':
            print('CAPTURE_FIXTURE_ENTERED',flush=True);time.sleep(.6)
            raw=work/'.product-v2/raw.webm';raw.write_bytes(b'original fixture capture')
            receipt=work/'.product-v2/capture.json';run=read_json(work/'.product-v2/run.json')
            write_json(receipt,{'status':'captured','workspace':str(work),'run_id':run['run_id'],'rawPath':str(raw),'errors':[]})
            write_json(work/'.product-v2/capture-pending.json',{'path':str(receipt),'sha256':digest(receipt)})
        else:
            video=work/'video.mp4';video.write_bytes(b'fixture media')
            run=read_json(work/'.product-v2/run.json');run['video']=str(video);write_json(work/'.product-v2/run.json',run)
            receipt=work/'.product-v2/recording.json';write_json(receipt,{'passed':True,'sha256':digest(video)})
            timeline=work/'.product-v2/timeline.json'
            write_json(timeline,{'decode_ok':True,'sample_fps':5,'video_sha256':digest(video),'recording_receipt':{'path':str(receipt),'sha256':digest(receipt)}})
            write_json(work/'.product-v2/controlled-video.json',{'timeline':str(timeline),'sha256':digest(timeline)})
        return 0
    progress.execute=execute
    try:result=progress.drive(root,'b',owner,case_id,work/'.product-v2/record-plan.json')
    except ValueError as error:result={'status':'rejected','reason':str(error)}
    print(json.dumps(result),flush=True)
'''


@unittest.skipUnless(os.name=='nt','Real ownership identity requires Windows')
class QueueContinuationTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name);self.pool=self.root/'pool';self.pid=os.getpid()
        self.addCleanup(self.temp.cleanup)
        self.patches=[patch('batch_control.memory_available_mb',return_value=24000),
                      patch('batch_control.cpu_snapshot',return_value={'logical_processors':32,'cpu_load_percent':20}),
                      patch('media_job.job_pids',return_value=[])]
        for item in self.patches:item.start();self.addCleanup(item.stop)
        cases=[]
        for cid in ('c','c2','c3','c4'):
            work=self.root/cid;work.mkdir();source=work/'source.docx';source.write_bytes(b'fixture')
            write_json(work/'.product-v2/run.json',{'workspace':str(work),'run_id':'original-'+cid})
            write_json(work/'.product-v2/record-plan.json',{'original_plan':True,'timeout_seconds':120})
            cases.append({'case_id':cid,'workspace':str(work),'source_docx':str(source),'source_sha256':digest(source)})
        manifest=self.root/'cases.json';write_json(manifest,{'cases':cases})
        batch.register(self.pool,'b',manifest,'isolated fixture',4,4);batch.claim(self.pool,'b',self.pid)
        self.work=self.root/'c';self.plan=self.work/'.product-v2/record-plan.json'
    def start(self,mode,case_id='c',extra=''):
        process=subprocess.Popen([sys.executable,'-B','-c',PROCESS,str(Path(batch.__file__).parent),mode,str(self.pool),str(self.pid),case_id,str(extra)],
                                 stdout=subprocess.PIPE,stderr=subprocess.STDOUT,text=True,encoding='utf-8',
                                 creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
        self.addCleanup(self.finish,process);return process
    def finish(self,process):
        if process.poll() is None:process.communicate(timeout=20)
        if process.stdout and not process.stdout.closed:process.stdout.close()
    def hold(self,seconds):
        process=self.start('hold',extra=seconds)
        self.assertEqual(process.stdout.readline().strip(),'LOCKED');return process
    def result(self,process):
        output=process.communicate(timeout=20)[0];self.assertEqual(process.returncode,0,output)
        return json.loads(output.strip().splitlines()[-1])
    def mutate(self,action,**kwargs):return batch.mutate(self.pool,'b',self.pid,action,**kwargs)
    def test_short_external_competition_preserves_ticket_and_owner(self):
        ticket=self.mutate('queue',case_id='c',stage='record');owner=digest(self.pool/'b/owner.json')
        holder=self.hold(.25);started=time.monotonic();result=self.mutate('acquire',token=ticket['token'])
        self.assertGreater(time.monotonic()-started,.15);self.assertEqual(result['status'],'active')
        self.assertEqual(result['token'],ticket['token']);self.assertEqual(result['submitted_ns'],ticket['submitted_ns'])
        self.assertEqual(digest(self.pool/'b/owner.json'),owner);self.assertEqual(len(read_json(self.pool/'queue.json')),1)
        holder.wait(timeout=5)
    def test_old_three_second_window_expires_but_default_ten_recovers(self):
        holder=self.hold(3.7);lock=self.pool/'mutation.lock';original=lock.read_bytes();started=time.monotonic()
        with self.assertRaises(batch.BatchStateBusy) as raised:
            with batch.transaction(self.pool,wait_seconds=3):self.fail('Unacquired transaction body ran')
        old_elapsed=time.monotonic()-started;self.assertEqual(raised.exception.wait_seconds,3)
        self.assertEqual(lock.read_bytes(),original)
        result=self.mutate('queue',case_id='c',stage='record');elapsed=time.monotonic()-started
        self.assertEqual(result['status'],'waiting');self.assertGreater(elapsed,3.4);holder.wait(timeout=5)
        print(json.dumps({'check':'real_3s_vs_10s','old_timeout_elapsed':old_elapsed,'recovered_elapsed':elapsed,'new_wait_seconds':batch.CONTROL_WAIT_SECONDS}))
    def test_default_ten_second_timeout_keeps_live_lock_owner_and_ticket(self):
        ticket=self.mutate('queue',case_id='c',stage='record')
        paths=[self.pool/'queue.json',self.pool/'b/owner.json',self.plan,self.work/'.product-v2/run.json']
        before=[digest(p) for p in paths];holder=self.hold(12);lock=self.pool/'mutation.lock';original=lock.read_bytes()
        output=io.StringIO();started=time.monotonic()
        with patch.object(sys,'argv',['progress_driver.py','--root',str(self.pool),'--batch-id','b','--pid',str(self.pid),'--case-id','c','--plan',str(self.plan)]),patch('progress_driver.execute') as execute,redirect_stdout(output):
            code=progress.main()
        elapsed=time.monotonic()-started;result=json.loads(output.getvalue())
        self.assertEqual(code,0);self.assertEqual(result['status'],'waiting');execute.assert_not_called()
        self.assertFalse(result['control_wait']['transaction_started']);self.assertEqual(result['control_wait']['wait_seconds'],10)
        self.assertGreaterEqual(elapsed,10);self.assertLess(elapsed,11.5)
        self.assertEqual(lock.read_bytes(),original);self.assertIsNone(holder.poll())
        self.assertEqual([digest(p) for p in paths],before);self.assertEqual(read_json(paths[0])[0]['token'],ticket['token'])
        holder.wait(timeout=5)
        print(json.dumps({'check':'live_lock_timeout','elapsed':elapsed,'waiting':result['status'],'lock_owner_ticket_plan_run_preserved':True}))
    def test_acquire_timeout_before_launch_returns_waiting_with_original_ticket(self):
        ticket=self.mutate('queue',case_id='c',stage='record');before=digest(self.pool/'queue.json');original=progress.mutate;holder=[]
        def contend(*args,**kwargs):
            if args[3]=='acquire':holder.append(self.hold(.3))
            return original(*args,**kwargs)
        with patch('batch_control.CONTROL_WAIT_SECONDS',.2),patch('progress_driver.mutate',side_effect=contend),patch('progress_driver.execute') as execute:
            result=progress.drive(self.pool,'b',self.pid,'c',self.plan)
        self.assertEqual(result['status'],'waiting');self.assertEqual(result['ticket']['token'],ticket['token'])
        self.assertIn('control_wait',result);self.assertNotIn('phase',result);execute.assert_not_called()
        self.assertEqual(digest(self.pool/'queue.json'),before);holder[0].wait(timeout=5)
        # No running/failed capture checkpoint was invented: original ticket is still usable.
        result=self.result(self.start('drive'));self.assertEqual(result['status'],'technical_evidence_ready')
        self.assertEqual(read_json(self.pool/'queue.json')[0]['token'],ticket['token'])
    def test_lock_body_error_with_busy_wording_is_not_waiting_or_retried(self):
        self.mutate('queue',case_id='c',stage='record');before=digest(self.pool/'queue.json')
        message='Batch state busy; retry after the short parent mutation completes, never delete a live lock'
        with patch('batch_control.runnable_waiting',side_effect=ValueError(message)) as failing,patch('progress_driver.execute') as execute:
            with self.assertRaises(ValueError) as raised:progress.drive(self.pool,'b',self.pid,'c',self.plan)
        self.assertNotIsInstance(raised.exception,batch.BatchStateBusy);self.assertEqual(failing.call_count,1);execute.assert_not_called()
        self.assertEqual(digest(self.pool/'queue.json'),before);self.assertFalse((self.pool/'mutation.lock').exists())
    def test_media_busy_text_never_replays_capture(self):
        calls=[]
        def failed(work,phase,lease,plan,log,timeout):
            calls.append(phase);log.write_text('ERROR: Batch state busy; capture may already have side effects');return 2
        with patch('progress_driver.execute',side_effect=failed):
            first=progress.drive(self.pool,'b',self.pid,'c',self.plan)
            second=progress.drive(self.pool,'b',self.pid,'c',self.plan)
        self.assertEqual(first['status'],'failed');self.assertEqual(second['status'],'failed');self.assertEqual(calls,['capture'])
        self.assertEqual(second['next_action'],'repair_capture_then_resume_with_retry_capture')
    def test_private_lock_cleanup_preserves_body_error_and_shared_live_lock(self):
        target,_=batch.batch(self.pool,'b');holder=[]
        with patch('batch_control.CONTROL_WAIT_SECONDS',.1):
            with self.assertRaisesRegex(ValueError,'actual policy refusal'):
                with progress.invocation(self.pool,target,self.pid,'c'):
                    holder.append(self.hold(.6));raise ValueError('actual policy refusal')
        self.assertIsNone(holder[0].poll());self.assertTrue((self.pool/'mutation.lock').exists())
        self.assertFalse((target/'progress/c.lock.json').exists());holder[0].wait(timeout=5)
    def test_private_lock_cleanup_cannot_remove_a_different_nonce(self):
        target,_=batch.batch(self.pool,'b');path=target/'progress/c.lock.json'
        with progress.invocation(self.pool,target,self.pid,'c'):
            # Even an out-of-protocol replacement is retained by this helper.
            write_json(path,{'identity':batch.identity(self.pid),'nonce':'different'})
        self.assertEqual(read_json(path)['nonce'],'different')
    def test_same_process_helper_and_reused_pid_cannot_replace_live_identity(self):
        target,_=batch.batch(self.pool,'b');path=target/'progress/c.lock.json'
        def duplicate():
            with progress.invocation(self.pool,target,self.pid,'c'):self.fail('Live helper was replaced')
        with progress.invocation(self.pool,target,self.pid,'c'):
            original=read_json(path)
            with ThreadPoolExecutor(max_workers=1) as executor:
                with self.assertRaisesRegex(ValueError,'live progress invocation'):executor.submit(duplicate).result(timeout=5)
            self.assertEqual(read_json(path),original)
        old=batch.identity(self.pid);old['created_ticks']-=1
        write_json(path,{'identity':old,'nonce':'prior-process-with-reused-pid'})
        with progress.invocation(self.pool,target,self.pid,'c'):
            self.assertEqual(read_json(path)['identity'],batch.identity(self.pid))
            self.assertNotEqual(read_json(path)['nonce'],'prior-process-with-reused-pid')
        self.assertFalse(path.exists())
    def test_followup_snapshot_busy_keeps_first_wave_failures_and_unstarted_cases(self):
        for cid in ('c','c2'):self.mutate('queue',case_id=cid,stage='record')
        for failed_status in ('failed','cleanup_pending'):
            with self.subTest(failed_status=failed_status):
                original=batch.transaction;calls=[]
                from contextlib import contextmanager
                @contextmanager
                def transaction(*args,**kwargs):
                    calls.append(1)
                    if len(calls)==3:raise batch.BatchStateBusy(self.pool/'mutation.lock',10)
                    with original(*args,**kwargs):yield
                outcome={'status':failed_status,'phase':'capture','reason':'original first-wave actual failure'}
                output=io.StringIO()
                with patch('batch_control.transaction',side_effect=transaction),patch('batch_control.GLOBAL_RECORDING_LIMIT',1),patch('progress_driver.drive',return_value=outcome) as drive,patch.object(sys,'argv',['progress_driver.py','--root',str(self.pool),'--batch-id','b','--pid',str(self.pid),'--ready']),redirect_stdout(output):
                    code=progress.main()
                result=json.loads(output.getvalue());self.assertEqual(code,2);self.assertEqual(result['status'],'failed')
                self.assertEqual(result['cases']['c']['status'],failed_status)
                self.assertEqual(result['cases']['c']['reason'],'original first-wave actual failure')
                self.assertEqual(result['cases']['c2']['status'],'waiting');self.assertEqual(drive.call_count,1)
                self.assertFalse(result['continuation_wait']['control_wait']['transaction_started'])
                self.assertIsNone(result['selected'])
    def test_four_process_queue_and_acquire_do_not_lose_or_duplicate_tickets(self):
        holder=self.hold(.4);ids=['c','c2','c3','c4'];queued=[self.start('queue',cid) for cid in ids]
        rows=[self.result(process) for process in queued];holder.wait(timeout=5)
        pool=read_json(self.pool/'queue.json');self.assertEqual(len(pool),4);self.assertEqual(len({q['token'] for q in pool}),4)
        self.assertEqual(len({q['submitted_ns'] for q in pool}),4);self.assertEqual({q['case_id'] for q in pool},set(ids))
        acquired=[self.start('acquire',q['case_id'],q['token']) for q in rows]
        outcomes=[self.result(process) for process in acquired]
        pool=read_json(self.pool/'queue.json');self.assertEqual(len(pool),4)
        # FIFO is unchanged; requests arriving before the selected head do not steal it.
        active=[q for q in pool if q['status']=='active'];self.assertGreaterEqual(len(active),1)
        self.assertEqual(active[0]['token'],min(rows,key=lambda q:q['submitted_ns'])['token'])
        self.assertEqual(len(active),sum(q.get('status')=='active' for q in outcomes))
    def test_two_processes_same_case_execute_capture_only_once(self):
        original_plan=digest(self.plan);first=self.start('drive')
        self.assertEqual(first.stdout.readline().strip(),'CAPTURE_FIXTURE_ENTERED')
        second=self.start('drive');rejected=self.result(second);completed=self.result(first)
        self.assertEqual(rejected['status'],'rejected');self.assertIn('live progress invocation',rejected['reason'])
        self.assertEqual(completed['status'],'technical_evidence_ready')
        self.assertEqual((self.pool/'fixture-media-events.txt').read_text().splitlines(),['capture','evidence'])
        self.assertEqual(digest(self.plan),original_plan);self.assertEqual(read_json(self.work/'.product-v2/run.json')['run_id'],'original-c')
        before=digest(self.pool/'queue.json');again=self.result(self.start('drive'))
        self.assertTrue(again['reused_checkpoint']);self.assertEqual(digest(self.pool/'queue.json'),before)
        self.assertEqual((self.pool/'fixture-media-events.txt').read_text().splitlines(),['capture','evidence'])


if __name__=='__main__':unittest.main()
