"""Owned ready-media continuation: real admission and isolated fake media only."""
from pathlib import Path
import sys
import tempfile
import threading
import time
import unittest
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
import batch_control as batch
import progress_driver as progress
from common import digest,read_json,write_json


class ReadyTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name);self.pool=self.root/'pool'
        self.patches=[patch('batch_control.identity',side_effect=lambda pid:{'pid':pid,'created_ticks':pid+1000}),
                      patch('batch_control.memory_available_mb',return_value=24000),
                      patch('batch_control.cpu_snapshot',return_value={'logical_processors':32,'cpu_load_percent':20}),
                      patch('media_job.job_pids',return_value=[])]
        for p in self.patches:p.start()
        self.calls=[];self.lock=threading.Lock();self.captures=0;self.max_captures=0
        self.cases=self.register('b',['c1','c2','c3'])
    def tearDown(self):
        for p in reversed(self.patches):p.stop()
        self.temp.cleanup()
    def register(self,name,ids):
        cases=[]
        for cid in ids:
            work=self.root/name/cid;work.mkdir(parents=True);source=work/'source.docx';source.write_bytes(b'fixture')
            write_json(work/'.product-v2/run.json',{'workspace':str(work),'run_id':name+'-'+cid})
            write_json(work/'.product-v2/record-plan.json',{'fixture':True})
            cases.append({'case_id':cid,'workspace':str(work),'source_docx':str(source),'source_sha256':digest(source)})
        manifest=self.root/(name+'.json');write_json(manifest,{'cases':cases})
        batch.register(self.pool,name,manifest,'isolated fixture',4,4);batch.claim(self.pool,name,101)
        return {c['case_id']:Path(c['workspace']) for c in cases}
    def queue(self,cid='c1',stage='record',name='b'):
        return batch.mutate(self.pool,name,101,'queue',cid,stage=stage)
    def capture(self,work):
        raw=work/'.product-v2/raw.webm';raw.write_bytes(b'original capture')
        receipt=work/'.product-v2/capture.json';run=read_json(work/'.product-v2/run.json')
        write_json(receipt,{'status':'captured','workspace':str(work),'run_id':run['run_id'],'rawPath':str(raw),'errors':[]})
        write_json(work/'.product-v2/capture-pending.json',{'path':str(receipt),'sha256':digest(receipt)})
    def execute(self,work,phase,lease,plan,log,timeout):
        with self.lock:
            self.calls.append((work.name,phase))
            if phase=='capture':
                self.captures+=1;self.max_captures=max(self.max_captures,self.captures)
            else:self.assertEqual(self.captures,0,'Evidence must retain actual capture exclusion')
        log.write_text('fixture command')
        if phase=='capture':
            time.sleep(.03);self.capture(work)
            with self.lock:self.captures-=1
        else:
            video=work/'video.mp4';video.write_bytes(b'completed media')
            run=read_json(work/'.product-v2/run.json');run['video']=str(video);write_json(work/'.product-v2/run.json',run)
            receipt=work/'.product-v2/recording.json';write_json(receipt,{'passed':True,'sha256':digest(video)})
            timeline=work/'.product-v2/timeline.json'
            write_json(timeline,{'decode_ok':True,'sample_fps':5,'video_sha256':digest(video),'recording_receipt':{'path':str(receipt),'sha256':digest(receipt)}})
            write_json(work/'.product-v2/controlled-video.json',{'timeline':str(timeline),'sha256':digest(timeline)})
        return 0
    def ready(self,**kw):
        with patch('progress_driver.execute',side_effect=self.execute):return progress.drive_ready(self.pool,'b',101,**kw)
    def test_queued_cases_finish_without_parent_handoffs_and_do_not_repeat(self):
        original=[self.queue(c)['token'] for c in self.cases]
        result=self.ready();self.assertEqual(result['status'],'technical_evidence_ready',result)
        self.assertCountEqual(self.calls,[(c,p) for c in self.cases for p in ('capture','evidence')])
        rows=read_json(self.pool/'queue.json');self.assertTrue(all(q['status']=='released' for q in rows))
        self.assertTrue(set(original).issubset({q['token'] for q in rows}))
        self.assertTrue(result['visual_review_required']);self.assertNotIn('decision',result)
        before=list(self.calls);self.assertEqual(self.ready()['status'],'idle');self.assertEqual(self.calls,before)
    def test_foreign_selected_is_returned_without_claim_or_requeue(self):
        self.register('other',['foreign']);first=self.queue('foreign','evidence','other');self.queue()
        before=read_json(self.pool/'queue.json');result=self.ready()
        self.assertEqual(result['status'],'waiting');self.assertEqual(result['selected']['token'],first['token'])
        self.assertEqual(read_json(self.pool/'queue.json'),before);self.assertEqual(self.calls,[])
    def test_resource_wait_is_bounded_and_retains_ticket(self):
        ticket=self.queue()
        with patch('batch_control.recording_resources',return_value={'acquired':False,'reason':'memory_exhausted','available_mb':1,'required_mb':4096}),patch('progress_driver.drive',wraps=progress.drive) as drive:
            result=self.ready()
        self.assertEqual(result['status'],'waiting');self.assertEqual(drive.call_count,1)
        self.assertEqual(result['selected']['token'],ticket['token'])
        queue=read_json(self.pool/'queue.json');self.assertEqual(len(queue),1)
        self.assertEqual(queue[0]['token'],ticket['token']);self.assertEqual(queue[0]['status'],'waiting')
        self.assertEqual(queue[0]['submitted_ns'],ticket['submitted_ns'])
        self.assertEqual(self.calls,[])
    def test_failed_capture_never_retries_or_cancels_head_to_skip_queue(self):
        self.queue();self.queue('c2')
        write_json(self.cases['c1']/'.product-v2/capture-pending.json',{'status':'capturing','sha256':None})
        result=self.ready();self.assertEqual(result['status'],'failed')
        self.assertFalse(any(c=='c1' for c,p in self.calls))
        self.assertTrue(all(q['status']=='waiting' for q in read_json(self.pool/'queue.json') if q['case_id']=='c1'))
        # Failed original head is retained, not cancelled to steal FIFO.
    def test_live_job_is_preserved(self):
        ticket=self.queue();batch.mutate(self.pool,'b',101,'acquire',token=ticket['token'])
        pool=read_json(self.pool/'queue.json');pool[0]['media_runtime']={'pid':202,'identity':batch.identity(202)};write_json(self.pool/'queue.json',pool)
        result=self.ready();self.assertEqual(result['cases']['c1']['status'],'running')
        self.assertEqual(read_json(self.pool/'queue.json'),pool);self.assertEqual(self.calls,[])
    def test_drain_and_wrong_owner_do_not_launch(self):
        self.queue();batch.mutate(self.pool,'b',101,'drain',authorization='explicit isolated fixture stop')
        self.assertEqual(self.ready()['status'],'paused');self.assertEqual(self.calls,[])
        with self.assertRaises(ValueError):progress.drive_ready(self.pool,'b',202)
    def test_plan_cannot_escape_case_or_refer_to_unqueued_case(self):
        self.queue();outside=self.root/'elsewhere.json';write_json(outside,{})
        self.assertEqual(self.ready(plans={'c1':str(outside)})['status'],'failed');self.assertEqual(self.calls,[])
        with self.assertRaises(ValueError):self.ready(plans={'c2':str(outside)})
    def test_new_case_added_during_invocation_is_left_for_owner(self):
        self.queue();original=self.execute
        def add(work,phase,*args):
            if phase=='evidence':self.queue('c2')
            return original(work,phase,*args)
        with patch('progress_driver.execute',side_effect=add):result=progress.drive_ready(self.pool,'b',101)
        self.assertEqual(result['status'],'technical_evidence_ready')
        self.assertEqual(result['case_ids'],['c1']);self.assertEqual(self.calls,[('c1','capture'),('c1','evidence')])
        self.assertEqual(read_json(self.pool/'queue.json')[-1]['case_id'],'c2')
        self.assertEqual(read_json(self.pool/'queue.json')[-1]['status'],'waiting')
    def test_other_batch_churn_does_not_retry_a_waiting_owned_ticket(self):
        self.queue();self.register('other',['foreign'])
        def waiting(*args,**kwargs):
            self.queue('foreign','record','other')
            return {'status':'waiting','next_action':'wait_for_resource_change'}
        with patch('progress_driver.drive',side_effect=waiting) as drive:
            result=self.ready()
        self.assertEqual(result['status'],'waiting');self.assertEqual(drive.call_count,1)

if __name__=='__main__':unittest.main()
