"""Explicit Astra/low routing without waiting for the Sol/ultra slot."""
import threading
import time
import unittest
from pathlib import Path
from unittest.mock import patch
import test_caseflow as fixtures
from test_caseflow import flow, FakeExecutor


class ExpeditedReviewTests(unittest.TestCase):
    tearDown=fixtures.CaseflowTests.tearDown
    make_source=fixtures.CaseflowTests.make_source
    run_fake=fixtures.CaseflowTests.run_fake

    def setUp(self):
        fixtures.CaseflowTests.setUp(self)
        self.cfg['runner']['review_mode']='combined_final'
        self.cfg['execution']={'fair_queue':True,'case_concurrency':8,'review_concurrency':1,'expedited_review_concurrency':1}
        self.make_source()
        self.m=flow.plan(self.cfg,self.source)
        self.folder=flow.batch_folder(self.cfg,self.m)
        self.cid=self.m['cases'][0]['case_id']

    def expedite(self):
        return flow.control_batch(self.cfg,self.m['batch_id'],'expedite',case_id=self.cid)

    def test_exact_cli_routes_and_read_only_sandbox(self):
        self.expedite()
        commands=flow.run_batch(self.cfg,self.m['batch_id'],dry_run=True)['cases'][0]['commands']
        self.assertIn('gpt-6-astra',commands['review_final'])
        self.assertIn('model_reasoning_effort=low',commands['review_final'])
        self.assertIn('read-only',commands['review_final'])
        self.assertIn('gpt-6-sol',commands['build'])
        self.assertIn('model_reasoning_effort=high',commands['build'])
        self.assertEqual(self.cfg['models']['reviewer']['model'],'gpt-6-sol')

    def test_case_scope_and_priority_alone_do_not_switch_other_cases(self):
        self.expedite()
        self.assertEqual(flow.selected_review_route(self.folder,self.cid)['profile'],'expedited')
        self.assertEqual(flow.selected_review_route(self.folder,'another')['profile'],'standard')
        flow.control_batch(self.cfg,self.m['batch_id'],'priority',value=10)
        self.assertEqual(flow.selected_review_route(self.folder,'another')['profile'],'standard')

    def test_repair_stays_sol_high_and_recheck_stays_astra_low(self):
        self.expedite();fake=FakeExecutor(revise_visual=True)
        state=self.run_fake(fake)['cases'][0]
        self.assertEqual(state['stage'],'delivered',state.get('reason'))
        reviews=[c for c in state['calls'] if c['stage'].startswith('review_')]
        repairs=[c for c in state['calls'] if c['stage']=='repair_final']
        self.assertEqual(len(reviews),2)
        self.assertEqual([(c['model'],c['reasoning_effort']) for c in reviews],[('gpt-6-astra','low')]*2)
        self.assertEqual([(c['model'],c['reasoning_effort']) for c in repairs],[('gpt-6-sol','high')])
        self.assertTrue(flow.review_record_allowed(state['final_review'],state))
        self.assertFalse(flow.review_record_allowed(state['final_review'],{**state,'review_authorizations':{}}))
        count=len(fake.stages)
        self.assertEqual(self.run_fake(fake)['cases'][0]['stage'],'delivered')
        self.assertEqual(len(fake.stages),count)

    def test_delivered_standard_case_keeps_its_valid_review_after_batch_expedited(self):
        fake=FakeExecutor();first=self.run_fake(fake)['cases'][0]
        before=first['delivery_sha256'];count=len(fake.stages)
        flow.control_batch(self.cfg,self.m['batch_id'],'expedite')
        second=self.run_fake(fake)['cases'][0]
        self.assertEqual(second['stage'],'delivered')
        self.assertEqual(second['delivery_sha256'],before)
        self.assertEqual(len(fake.stages),count)
        self.assertEqual(second['final_review']['model'],'gpt-6-sol')

    def test_live_waiting_review_moves_to_astra_without_waiting_for_sol_slot(self):
        result=[];errors=[];done=threading.Event()
        def run():
            try:result.append(self.run_fake(FakeExecutor()))
            except Exception as exc:errors.append(exc)
            finally:done.set()
        root=self.cfg['_root']/'.runtime/slots/review/0';root.mkdir(parents=True)
        with flow.BatchLock(root):
            worker=threading.Thread(target=run);worker.start()
            deadline=time.monotonic()+10
            path=flow.state_at(self.folder,self.cid)
            while time.monotonic()<deadline:
                if path.exists() and flow.read_json(path).get('waiting_stage')=='review_final':break
                time.sleep(.02)
            self.assertTrue(path.exists())
            self.expedite()
            completed_while_sol_locked=done.wait(10)
        worker.join(15)
        self.assertFalse(errors,errors)
        self.assertTrue(completed_while_sol_locked,'Expedited review waited for the ordinary Sol slot')
        state=result[0]['cases'][0]
        self.assertEqual(state['stage'],'delivered',state.get('reason'))
        self.assertEqual(state['review_calls_started'],1)
        self.assertEqual(state['final_review']['model'],'gpt-6-astra')
        self.assertEqual(list((root.parent/'queue').glob('*.json')),[])

    def test_wrong_model_or_thinking_does_not_silently_pass(self):
        self.expedite();fake=FakeExecutor()
        def wrong(cfg,case,stage,context,output=None):
            result=fake(cfg,case,stage,context,output)
            if stage.startswith('review_'):result['reasoning_effort']='high'
            return result
        state=self.run_fake(wrong)['cases'][0]
        self.assertEqual(state['stage'],'blocked')
        self.assertIn('explicitly selected route',state['reason'])
        self.assertFalse(Path(self.m['output_root']).exists())

    def test_configuration_rejects_expedited_model_substitution(self):
        config=flow.read_json(self.config_path)
        config['models']['expedited_reviewer']={'model':'gpt-6-sol','reasoning_effort':'low'}
        flow.atomic_json(self.config_path,config)
        with self.assertRaises(flow.Blocked):flow.config_at(self.config_path)

    def test_scoped_run_leaves_unselected_state_and_delivery_untouched(self):
        self.source=self.root/'scoped-input';self.source.mkdir()
        fixtures.docx(self.source/'selected.docx');fixtures.docx(self.source/'untouched.docx')
        m=flow.plan(self.cfg,self.source);folder=flow.batch_folder(self.cfg,m)
        entries={e['case_name']:e for e in m['cases']}
        selected=entries['selected']['case_id'];other=entries['untouched']['case_id']
        state_path=flow.state_at(folder,other)
        flow.atomic_json(state_path,{'case_id':other,'stage':'blocked','reason':'Existing delivery discrepancy; do not revisit in this scoped run','calls':[]})
        before=state_path.read_bytes()
        fake=FakeExecutor();result=self.run_fake(fake,case_ids=[selected])
        self.assertEqual(result['status'],'complete')
        self.assertEqual(result['scope'],'selected_cases')
        self.assertEqual(result['selected_case_ids'],[selected])
        self.assertEqual(result['unselected_case_count'],1)
        self.assertEqual(state_path.read_bytes(),before)
        self.assertFalse(flow.case_workspace(folder,entries['untouched']).exists())
        self.assertEqual({name for name,_ in fake.stages},{'selected'})
        for invalid in [[],[selected,selected],['unknown']]:
            with self.assertRaises(flow.Blocked):flow.run_batch(self.cfg,m['batch_id'],dry_run=True,case_ids=invalid)
