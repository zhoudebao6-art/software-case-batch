"""Adversarial isolated continuation tests; actual admission, no real recording."""
from pathlib import Path
import os
import sys
import tempfile
import unittest
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
import batch_control as batch
import progress_driver as progress
from common import digest,read_json,write_json


class ProgressTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name);self.pool=self.root/'pool'
        self.patches=[patch('batch_control.identity',side_effect=lambda pid:{'pid':pid,'created_ticks':pid+1000}),
                      patch('batch_control.memory_available_mb',return_value=24000),
                      patch('batch_control.cpu_snapshot',return_value={'logical_processors':32,'cpu_load_percent':20}),
                      patch('media_job.job_pids',return_value=[])]
        for p in self.patches:p.start()
        self.manifest=self.create('b');self.work=Path(self.manifest['cases'][0]['workspace']);self.calls=[]
    def tearDown(self):
        for p in reversed(self.patches):p.stop()
        self.temp.cleanup()
    def create(self,name):
        work=self.root/name;work.mkdir();source=work/'source.docx';source.write_bytes(b'fixture')
        write_json(work/'.product-v2/run.json',{'workspace':str(work),'run_id':name+'-run'})
        cases=self.root/(name+'.json');write_json(cases,{'cases':[{'case_id':'c','workspace':str(work),'source_docx':str(source),'source_sha256':digest(source)}]})
        result=batch.register(self.pool,name,cases,'isolated fixture',4,4);batch.claim(self.pool,name,101);return result
    def mutate(self,action,**kw):return batch.mutate(self.pool,'b',101,action,**kw)
    def capture(self):
        raw=self.work/'.product-v2/raw.webm';raw.write_bytes(b'original recording')
        path=self.work/'.product-v2/capture.json'
        write_json(path,{'status':'captured','workspace':str(self.work),'run_id':'b-run','rawPath':str(raw),'errors':[]})
        write_json(self.work/'.product-v2/capture-pending.json',{'path':str(path),'sha256':digest(path)})
    def execute(self,workspace,phase,lease,plan,log,timeout):
        self.calls.append(phase);log.write_text('isolated admitted command')
        if phase=='capture':self.capture()
        else:self.completed()
        return 0
    def drive(self,**kw):
        with patch('progress_driver.execute',side_effect=self.execute):return progress.drive(self.pool,'b',101,'c',self.root/'plan.json',**kw)
    def test_capture_release_evidence_release_and_duplicate_does_no_work(self):
        self.assertEqual(self.drive()['status'],'technical_evidence_ready');self.assertEqual(self.calls,['capture','evidence'])
        self.assertTrue(all(q['status']=='released' for q in read_json(self.pool/'queue.json')))
        self.assertTrue(self.drive()['reused_checkpoint']);self.assertEqual(self.calls,['capture','evidence'])
    def test_r16_successful_capture_is_reused_without_rerecording(self):
        self.capture();self.assertEqual(self.drive()['status'],'technical_evidence_ready');self.assertEqual(self.calls,['evidence'])
    def completed(self):
        video=self.root/'video.mp4';video.write_bytes(b'original completed video')
        run=read_json(self.work/'.product-v2/run.json');run['video']=str(video);write_json(self.work/'.product-v2/run.json',run)
        receipt=self.work/'.product-v2/recording.json';write_json(receipt,{'passed':True,'sha256':digest(video)})
        timeline=self.work/'.product-v2/timeline.json'
        write_json(timeline,{'decode_ok':True,'sample_fps':5,'video_sha256':digest(video),'recording_receipt':{'path':str(receipt),'sha256':digest(receipt)}})
        write_json(self.work/'.product-v2/controlled-video.json',{'timeline':str(timeline),'sha256':digest(timeline)})
    def test_old_completed_media_without_raw_or_checkpoint_runs_no_media_stage(self):
        self.completed()
        with patch('subprocess.run',side_effect=AssertionError('No media command/decoder allowed')):
            result=self.drive()
        self.assertTrue(result['adopted_completed_recording']);self.assertEqual(self.calls,[])
        self.assertFalse((self.pool/'queue.json').exists())
    def test_old_completed_media_with_capture_pointer_runs_no_evidence(self):
        self.completed();self.capture()
        result=self.drive();self.assertEqual(result['status'],'technical_evidence_ready');self.assertEqual(self.calls,[])
    def test_repeated_completed_checkpoint_hashes_short_receipts_without_rechecking_video(self):
        self.completed();self.assertTrue(self.drive()['adopted_completed_recording'])
        allowed={Path(self.manifest['cases'][0]['source_docx']),
                 self.work/'.product-v2/recording.json',self.work/'.product-v2/controlled-video.json'}
        hashed=[]
        def short_digest(path):
            path=Path(path)
            self.assertIn(path,allowed,'Completed checkpoint must not hash media or timeline again')
            hashed.append(path);return digest(path)
        with patch('progress_driver.digest',side_effect=short_digest),patch('proflow.completed_recording',side_effect=AssertionError('Original media already adopted')):
            for _ in range(2):
                result=self.drive();self.assertTrue(result['reused_checkpoint'])
                self.assertEqual(result['next_action'],'independent_review')
        self.assertEqual(len(hashed),6);self.assertEqual(set(hashed),allowed);self.assertEqual(self.calls,[])
    def test_old_completed_media_does_not_release_live_r16_job(self):
        self.completed();q=self.mutate('queue',case_id='c',stage='evidence');self.mutate('acquire',token=q['token'])
        pool=read_json(self.pool/'queue.json');pool[0]['media_runtime']={'pid':202,'identity':batch.identity(202)};write_json(self.pool/'queue.json',pool)
        self.assertEqual(self.drive()['status'],'running');self.assertEqual(read_json(self.pool/'queue.json'),pool);self.assertEqual(self.calls,[])
    def test_corrupted_completed_without_raw_does_not_replay_business(self):
        self.completed();(self.root/'video.mp4').write_bytes(b'damaged')
        self.assertEqual(self.drive()['next_action'],'repair_existing_recording_or_evidence');self.assertEqual(self.calls,[])
    def test_inflight_r16_runtime_is_preserved(self):
        q=self.mutate('queue',case_id='c',stage='record');self.mutate('acquire',token=q['token'])
        pool=read_json(self.pool/'queue.json');pool[0]['media_runtime']={'pid':202,'identity':batch.identity(202)};write_json(self.pool/'queue.json',pool)
        self.assertEqual(self.drive()['status'],'running');self.assertEqual(self.calls,[])
        self.assertEqual(read_json(self.pool/'queue.json'),pool)
    def test_dead_runtime_releases_old_ticket_and_resumes_successful_capture(self):
        q=self.mutate('queue',case_id='c',stage='record');self.mutate('acquire',token=q['token']);self.capture()
        pool=read_json(self.pool/'queue.json');pool[0]['media_runtime']={'pid':202,'identity':{'pid':202,'created_ticks':1}};write_json(self.pool/'queue.json',pool)
        self.assertEqual(self.drive()['status'],'technical_evidence_ready');self.assertEqual(self.calls,['evidence'])
        self.assertTrue(all(q['status']=='released' for q in read_json(self.pool/'queue.json')))
    def test_child_job_members_retain_active_even_if_runtime_dead(self):
        q=self.mutate('queue',case_id='c',stage='record');self.mutate('acquire',token=q['token'])
        pool=read_json(self.pool/'queue.json');pool[0]['media_runtime']={'pid':202,'identity':{'pid':202,'created_ticks':1}};write_json(self.pool/'queue.json',pool)
        with patch('media_job.job_pids',return_value=[303]):self.assertEqual(self.drive()['status'],'running')
        self.assertEqual(read_json(self.pool/'queue.json'),pool);self.assertEqual(self.calls,[])
    def test_selected_other_batch_returns_pointer_without_mutation_or_busy_poll(self):
        self.create('other');first=batch.mutate(self.pool,'other',101,'queue','c',stage='evidence')
        before=read_json(self.pool/'queue.json')[0]
        result=self.drive();self.assertEqual(result['status'],'waiting');self.assertEqual(result['admission']['selected']['token'],first['token'])
        self.assertEqual(read_json(self.pool/'queue.json')[0],before);self.assertEqual(self.calls,[])
        self.assertEqual(len(read_json(self.pool/'queue.json')),2)
    def test_waiting_own_ticket_is_reused_across_invocations(self):
        with patch('batch_control.recording_resources',return_value={'acquired':False,'reason':'memory_exhausted','available_mb':1,'required_mb':4096}):
            first=self.drive();second=self.drive()
        self.assertEqual(first['ticket']['token'],second['ticket']['token']);self.assertEqual(len(read_json(self.pool/'queue.json')),1)
    def test_live_helper_lock_rejects_duplicate_and_wrong_owner_is_rejected(self):
        path=self.pool/'b/progress/c.lock.json';write_json(path,{'identity':batch.identity(os.getpid()),'nonce':'original'})
        with self.assertRaisesRegex(ValueError,'live progress'):self.drive()
        self.assertEqual(read_json(path)['nonce'],'original')
        with self.assertRaises(ValueError):progress.drive(self.pool,'b',202,'c')
    def test_dead_helper_crash_checkpoint_recovers_capture_without_recapture(self):
        self.capture();write_json(self.pool/'b/progress/c.lock.json',{'identity':{'pid':202,'created_ticks':1},'nonce':'dead'})
        write_json(self.pool/'b/progress/c.json',{'run_id':'b-run','status':'running','phase':'capture'})
        self.assertEqual(self.drive()['status'],'technical_evidence_ready');self.assertEqual(self.calls,['evidence'])
    def test_failed_capture_is_not_blindly_retried(self):
        write_json(self.work/'.product-v2/capture-pending.json',{'status':'capturing','sha256':None})
        self.assertEqual(self.drive()['status'],'failed');self.assertEqual(self.calls,[])
        self.assertEqual(self.drive(retry_capture=True)['status'],'technical_evidence_ready')
    def test_lost_pointer_preserves_evidence_ticket_and_original_until_repaired(self):
        self.capture();pointer=self.work/'.product-v2/capture-pending.json';original=read_json(pointer);pointer.unlink()
        ticket=self.mutate('queue',case_id='c',stage='evidence');queue_hash=digest(self.pool/'queue.json')
        raw=self.work/'.product-v2/raw.webm';raw_hash=digest(raw);receipt_hash=digest(Path(original['path']))
        for retry in (False,True,False):
            result=self.drive(retry_capture=retry)
            self.assertEqual(result['next_action'],'repair_capture_pointer_then_resume_evidence')
            self.assertEqual(result['phase'],'evidence');self.assertEqual(result['ticket']['token'],ticket['token'])
            self.assertEqual(result['capture_receipts'],[original]);self.assertEqual(self.calls,[])
            self.assertEqual(digest(self.pool/'queue.json'),queue_hash)
            self.assertEqual(digest(raw),raw_hash);self.assertEqual(digest(Path(original['path'])),receipt_hash)
        write_json(pointer,original)
        self.assertEqual(self.drive(retry_capture=True)['status'],'technical_evidence_ready')
        self.assertEqual(self.calls,['evidence'])
        rows=read_json(self.pool/'queue.json');self.assertEqual(len(rows),1)
        self.assertEqual(rows[0]['token'],ticket['token']);self.assertEqual(rows[0]['status'],'released')
    def test_lost_pointer_keeps_exited_active_evidence_reservation_for_repair(self):
        self.capture();(self.work/'.product-v2/capture-pending.json').unlink()
        q=self.mutate('queue',case_id='c',stage='evidence');self.mutate('acquire',token=q['token'])
        pool=read_json(self.pool/'queue.json');pool[0]['media_runtime']={'pid':202,'identity':{'pid':202,'created_ticks':1}}
        write_json(self.pool/'queue.json',pool);before=digest(self.pool/'queue.json')
        result=self.drive(retry_capture=True)
        self.assertEqual(result['next_action'],'repair_capture_pointer_then_resume_evidence')
        self.assertEqual(digest(self.pool/'queue.json'),before);self.assertEqual(self.calls,[])
    def test_old_evidence_checkpoints_cannot_be_downgraded_even_with_retry(self):
        checkpoint=self.pool/'b/progress/c.json'
        for state in ({'status':'capture_complete','next_action':'evidence'},
                      {'status':'running','phase':'evidence'}, {'status':'failed','phase':'evidence'}):
            with self.subTest(state=state):
                write_json(checkpoint,dict(state,run_id='b-run'))
                for retry in (False,True):
                    result=self.drive(retry_capture=retry)
                    self.assertEqual(result['next_action'],'repair_capture_pointer_then_resume_evidence')
                    self.assertEqual(result['phase'],'evidence');self.assertEqual(self.calls,[])
                    self.assertFalse((self.pool/'queue.json').exists())
    def test_capture_checkpoints_keep_waiting_record_ticket_until_explicit_retry(self):
        ticket=self.mutate('queue',case_id='c',stage='record');before=digest(self.pool/'queue.json')
        for status in ('running','failed'):
            with self.subTest(status=status):
                write_json(self.pool/'b/progress/c.json',{'run_id':'b-run','status':status,'phase':'capture'})
                for _ in range(2):
                    result=self.drive()
                    self.assertEqual(result['next_action'],'repair_capture_then_resume_with_retry_capture')
                    self.assertEqual(result['ticket']['token'],ticket['token'])
                    self.assertEqual(digest(self.pool/'queue.json'),before);self.assertEqual(self.calls,[])
        self.assertEqual(self.drive(retry_capture=True)['status'],'technical_evidence_ready')
        self.assertEqual(self.calls,['capture','evidence'])
        self.assertEqual(read_json(self.pool/'queue.json')[0]['token'],ticket['token'])
    def test_retained_current_run_receipt_blocks_capture_without_ticket_or_checkpoint(self):
        raw=self.work/'.product-v2/recordings/original/raw.webm';raw.parent.mkdir(parents=True);raw.write_bytes(b'prior capture')
        receipt=raw.with_name('capture.json')
        write_json(receipt,{'status':'captured','workspace':str(self.work),'run_id':'b-run','rawPath':str(raw),'errors':[]})
        before=(digest(raw),digest(receipt))
        result=self.drive(retry_capture=True)
        self.assertEqual(result['next_action'],'repair_capture_pointer_then_resume_evidence')
        self.assertEqual(result['capture_receipts'],[{'path':str(receipt),'sha256':digest(receipt)}])
        self.assertEqual((digest(raw),digest(receipt)),before);self.assertEqual(self.calls,[])
        self.assertFalse((self.pool/'queue.json').exists())
    def test_saved_receipt_identity_survives_pointer_loss_for_nonstandard_receipt_name(self):
        self.capture();pointer=self.work/'.product-v2/capture-pending.json';original=read_json(pointer);pointer.unlink()
        prior=Path(original['path']);renamed=prior.with_name('original-result.json');prior.rename(renamed)
        reference={'path':str(renamed),'sha256':digest(renamed)}
        write_json(self.pool/'b/progress/c.json',{'run_id':'b-run','status':'running','phase':'evidence','capture':reference})
        result=self.drive(retry_capture=True)
        self.assertEqual(result['next_action'],'repair_capture_pointer_then_resume_evidence')
        self.assertEqual(result['capture_receipts'],[reference]);self.assertEqual(result['capture'],reference)
        self.assertEqual(self.calls,[]);self.assertFalse((self.pool/'queue.json').exists())
    def test_valid_capture_is_reused_even_when_retry_was_requested(self):
        self.capture();result=self.drive(retry_capture=True)
        self.assertEqual(result['status'],'technical_evidence_ready');self.assertEqual(self.calls,['evidence'])
    def test_unrelated_run_receipt_does_not_block_current_first_capture(self):
        receipt=self.work/'.product-v2/old-capture.json'
        write_json(receipt,{'status':'captured','workspace':str(self.work),'run_id':'old-run','rawPath':'old-raw.webm','errors':[]})
        before=digest(receipt)
        self.assertEqual(self.drive()['status'],'technical_evidence_ready');self.assertEqual(self.calls,['capture','evidence'])
        self.assertEqual(digest(receipt),before)
    def test_failure_always_releases_proven_exited_lease(self):
        with patch('progress_driver.execute',return_value=2):result=progress.drive(self.pool,'b',101,'c',self.root/'plan.json')
        self.assertEqual(result['status'],'failed');self.assertEqual(read_json(self.pool/'queue.json')[0]['status'],'released')
    def test_exit_unproven_keeps_reservation_and_precise_cleanup_action(self):
        with patch('media_job.job_pids',return_value=[303]):result=self.drive()
        self.assertEqual(result['status'],'cleanup_pending');self.assertEqual(read_json(self.pool/'queue.json')[0]['status'],'active')
        self.assertEqual(self.calls,['capture'])
    def test_frozen_binding_and_completed_receipt_mutations_fail_closed(self):
        self.drive();write_json(self.work/'.product-v2/recording.json',{'passed':False})
        with self.assertRaisesRegex(ValueError,'receipts changed'):self.drive()
        value=read_json(self.work/'.product-v2/batch-binding.json');value['case_id']='other';write_json(self.work/'.product-v2/batch-binding.json',value)
        with self.assertRaisesRegex(ValueError,'binding changed'):self.drive()


if __name__=='__main__':unittest.main()
