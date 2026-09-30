"""Isolated scheduling regression tests; no model calls or real case mutation."""
import os
import threading
import time
import unittest
from unittest.mock import patch
import test_caseflow as fixtures
from test_caseflow import flow, FakeExecutor
from case_queue import process_token


def until(condition, timeout=10):
    deadline=time.monotonic()+timeout
    while not condition():
        if time.monotonic()>deadline:
            raise AssertionError('Timed out waiting for fixture condition')
        time.sleep(.02)


class PipelineControls(unittest.TestCase):
    setUp=fixtures.CaseflowTests.setUp
    tearDown=fixtures.CaseflowTests.tearDown
    make_source=fixtures.CaseflowTests.make_source
    run_fake=fixtures.CaseflowTests.run_fake

    def test_priority_fifo_legacy_lock_and_dead_ticket_cleanup(self):
        self.cfg['execution']={'fair_queue':True,'recording_concurrency':1}
        root=self.cfg['_root']/'.runtime/slots/recording'
        (root/'0').mkdir(parents=True)
        flow.atomic_json(root/'queue/dead.json',{'pid':2147483647,'process_token':'dead','queued_ns':0,'token':'dead'})
        self.assertTrue(process_token(os.getpid()))
        order=[];errors=[]
        def worker(name,priority):
            try:
                with flow.stage_slot(self.cfg,'recording',owner={'case_id':name,'priority':priority}):
                    order.append(name)
                    time.sleep(.04)
            except Exception as exc:
                errors.append(exc)
        threads=[]
        def ticket_visible(name):
            for path in (root/'queue').glob('*.json'):
                # Match production's published-ticket view, not atomic staging files.
                if path.name.startswith('.'):
                    continue
                try:
                    if flow.read_json(path).get('case_id') == name:
                        return True
                except FileNotFoundError:
                    continue
            return False
        try:
            with flow.BatchLock(root/'0'):
                for name,priority in [('first',0),('second',0),('urgent',10)]:
                    thread=threading.Thread(target=worker,args=(name,priority));thread.start();threads.append(thread)
                    until(lambda:ticket_visible(name))
                self.assertEqual(order,[])
        finally:
            for thread in threads:thread.join(10)
        self.assertFalse(errors,errors)
        self.assertEqual(order,['urgent','first','second'])
        self.assertFalse(list((root/'queue').glob('*.json')))

    def test_drain_finishes_active_call_then_preserves_build_checkpoint(self):
        self.make_source();m=flow.plan(self.cfg,self.source)
        fake=FakeExecutor()
        def execute(cfg,case,stage,context,output=None):
            rec=fake(cfg,case,stage,context,output)
            if stage=='build':flow.control_batch(self.cfg,m['batch_id'],'drain')
            return rec
        result=self.run_fake(execute)
        self.assertEqual(result['status'],'drained')
        self.assertEqual(result['cases'][0]['stage'],'built')
        self.assertEqual([s for _,s in fake.stages],['build'])
        flow.control_batch(self.cfg,m['batch_id'],'continue')
        resumed=self.run_fake(fake)
        self.assertEqual(resumed['status'],'complete')
        self.assertEqual([s for _,s in fake.stages].count('build'),1)

    def test_resume_one_failed_case_while_other_case_keeps_running(self):
        self.make_source('first.docx');self.make_source('slow.docx')
        m=flow.plan(self.cfg,self.source);folder=flow.batch_folder(self.cfg,m)
        ids={e['case_name']:e['case_id'] for e in m['cases']}
        count={'first':0,'slow':0};released=threading.Event();errors=[]
        def worker(cfg,manifest,batch,entry,executor=None):
            name=entry['case_name'];count[name]+=1
            if name=='slow':
                if not released.wait(10):raise RuntimeError('Fixture resume did not run')
            elif count[name]==2:released.set()
            state={'case_id':entry['case_id'],'stage':'blocked' if name=='first' and count[name]==1 else 'delivered','calls':[]}
            flow.atomic_json(flow.state_at(batch,entry['case_id']),state)
            return state
        def request():
            try:
                until(lambda:flow.state_at(folder,ids['first']).exists())
                time.sleep(.2)
                flow.control_batch(self.cfg,m['batch_id'],'resume-case',case_id=ids['first'])
            except Exception as exc:errors.append(exc);released.set()
        helper=threading.Thread(target=request);helper.start()
        try:
            with patch.object(flow,'run_case',worker):result=flow.run_batch(self.cfg,m['batch_id'],executor=FakeExecutor())
        finally:released.set();helper.join(10)
        self.assertFalse(errors,errors)
        self.assertEqual(result['status'],'complete')
        self.assertEqual(count,{'first':2,'slow':1})
        self.assertEqual(flow.read_json(folder/'control-acks.json')[ids['first']]['outcome'],'resumed')

    def test_waiting_slot_drain_cleans_ticket_and_preserves_lock(self):
        self.cfg['execution']={'fair_queue':True}
        with self.assertRaises(flow.Drained):
            with flow.stage_slot(self.cfg,'recording',checkpoint=lambda:(_ for _ in ()).throw(flow.Drained('fixture'))):pass
        root=self.cfg['_root']/'.runtime/slots/recording'
        self.assertEqual(list((root/'queue').glob('*.json')),[])
        with flow.stage_slot(self.cfg,'recording'):pass

    def test_pipeline_profile_is_frozen_and_identity_compatible(self):
        self.make_source();legacy=flow.plan(self.cfg,self.source)
        self.cfg['runner']['pipeline_profile']='efficient-v1'
        self.assertEqual(flow.plan(self.cfg,self.source)['pipeline_profile'],'legacy')
        self.assertEqual(flow.batch_identity(legacy),flow.batch_identity({**legacy,'pipeline_profile':'efficient-v1'}))
        other=self.root/'new-source';other.mkdir();fixtures.docx(other/'new.docx')
        self.assertEqual(flow.plan(self.cfg,other)['pipeline_profile'],'efficient-v1')

    def test_new_delivery_only_word_and_video_preserves_working_evidence(self):
        self.cfg['runner']['delivery_profile']='word-video'
        source=self.make_source();before=flow.sha256(source)
        m=flow.plan(self.cfg,self.source)
        fake=FakeExecutor()
        def execute(cfg,case,stage,context,output=None):
            rec=fake(cfg,case,stage,context,output)
            if stage=='build':
                (case/'README.md').write_text('Fixture provenance remains in the workspace.',encoding='utf-8')
                path=case/'evidence/artifact-manifest.json'
                manifest=flow.read_json(path);manifest['readme']='README.md';flow.atomic_json(path,manifest)
            return rec
        state=self.run_fake(execute)['cases'][0]
        self.assertEqual(state['stage'],'delivered',state.get('reason'))
        from pathlib import Path
        dest=Path(state['delivery']);case=flow.case_workspace(flow.batch_folder(self.cfg,m),m['cases'][0])
        self.assertEqual({p.name for p in dest.iterdir()},{source.name,'模拟系统'})
        self.assertEqual(flow.sha256(source),before)
        self.assertTrue(list((case/'source').glob('*.docx')))
        self.assertTrue((case/'exports/fig.png').is_file())
        self.assertTrue((case/'README.md').is_file())
        self.assertEqual(len(state['delivery_sha256']),2)
        self.assertEqual(self.run_fake(FakeExecutor())['cases'][0]['stage'],'delivered')

    def test_existing_batch_delivery_profile_is_not_changed_by_new_default(self):
        self.make_source();m=flow.plan(self.cfg,self.source)
        self.cfg['runner']['delivery_profile']='word-video'
        self.assertEqual(flow.plan(self.cfg,self.source)['delivery_profile'],'full')
        state=self.run_fake(FakeExecutor())['cases'][0]
        from pathlib import Path
        self.assertTrue((Path(state['delivery'])/'原始文件').is_dir())

    def test_new_dry_run_reports_script_capture_and_high_preparation(self):
        self.cfg['runner']['pipeline_profile']='efficient-v1'
        self.make_source();m=flow.plan(self.cfg,self.source)
        commands=flow.run_batch(self.cfg,m['batch_id'],dry_run=True)['cases'][0]['commands']
        self.assertNotIn('video',commands)
        self.assertIsNone(commands['capture_video']['model'])
        self.assertIn('model_reasoning_effort=high',commands['prepare_video'])

    def test_eight_builders_can_overlap_under_fair_queue(self):
        self.cfg['execution']={'fair_queue':True,'case_concurrency':8}
        barrier=threading.Barrier(8,timeout=15);active=0;peak=0;mutex=threading.Lock();errors=[]
        def work():
            nonlocal active,peak
            try:
                with flow.stage_slot(self.cfg,'build'):
                    with mutex:active+=1;peak=max(active,peak)
                    barrier.wait()
                    with mutex:active-=1
            except Exception:
                import traceback
                errors.append(traceback.format_exc())
        threads=[threading.Thread(target=work) for _ in range(8)]
        for thread in threads:thread.start()
        for thread in threads:thread.join(20)
        self.assertFalse(errors,errors)
        self.assertEqual(peak,8)

    def test_script_capture_dispatch_has_no_video_model_call(self):
        # The recorder itself has a separate real-browser fixture. Here verify
        # parent dispatch/accounting and Ultra routing with isolated artifacts.
        from types import SimpleNamespace
        import json
        from pathlib import Path
        root=Path(__file__).resolve().parents[1]
        from test_caseflow import fake_runtime
        self.cfg['runtime']=fake_runtime(self.root)
        self.cfg['runner'].update(pipeline_profile='efficient-v1',review_mode='combined_final')
        self.make_source();m=flow.plan(self.cfg,self.source)
        fake=FakeExecutor();contexts={}
        def execute(cfg,case,stage,context,output=None):
            contexts[str(case)]=context
            return fake(cfg,case,stage,context,output)
        def scripted(cfg,case,cid,resources):
            fake(cfg,case,'video',contexts[str(case)])
            return {'video_sha256':flow.current_video_hash(case),'duration_seconds':.01,'mode':'record','raw_video':'fixture-only.webm'}
        def process(args,**kwargs):
            value={'files':{},'manifest_fields':{}} if any('controlled_evidence.py' in str(a) for a in args) else {'format':{'duration':'8.0'},'streams':[{'codec_name':'h264','width':1920,'height':1080,'avg_frame_rate':'30/1'}]}
            return SimpleNamespace(returncode=0,stdout=json.dumps(value),stderr='')
        with patch.object(flow,'invoke',execute),patch.object(flow,'native_codex'),patch.object(flow.subprocess,'run',side_effect=process),patch('capture_runner.validate_plan',return_value={}),patch('capture_runner.service_ready',return_value={}),patch('capture_runner.capture',side_effect=scripted):
            result=flow.run_batch(self.cfg,m['batch_id'],executor=execute)
        state=result['cases'][0]
        self.assertEqual(state['stage'],'delivered',state.get('reason'))
        self.assertNotIn('video',[call['stage'] for call in state['calls']])
        self.assertEqual([call['stage'] for call in state['script_calls']],['capture_video'])
        self.assertIsNone(state['script_calls'][0]['model'])
        review=[call for call in state['calls'] if call['stage']=='review_final'][0]
        self.assertEqual((review['model'],review['reasoning_effort']),('gpt-6-sol','ultra'))
