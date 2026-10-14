"""Actual-shaped session fixtures for owner-scoped same-model overload retries."""
import json
from pathlib import Path
import sys
import uuid
import unittest
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parent))
from test_progress_driver import ProgressTests as Fixture
from common import read_json,write_json
import batch_control as batch


class CapacityTests(Fixture):
    # Inherit the isolated environment helpers, but discovery below uses only
    # methods defined here to avoid rerunning unrelated progress tests.
    def setUp(self):
        super().setUp();self.sessions=self.root/'sessions';self.sessions.mkdir()
        self.session_patch=patch('contracts.SESSION_ROOT',self.sessions);self.session_patch.start()
        self.meta_id=str(uuid.uuid4());self.path=self.sessions/('rollout-'+self.meta_id+'.jsonl')
        self.events=[{'type':'session_meta','payload':{'id':self.meta_id}}]
        self.call=0
    def tearDown(self):self.session_patch.stop();super().tearDown()
    def attempt(self,entry,child=False,live=False,wrong_model=False):
        self.call+=1;cid='call-'+str(self.call);model='gpt-6-astra' if wrong_model else 'gpt-6.1-sol'
        args={'model':model,'reasoning_effort':'high','fork_turns':'none','message':entry['token']+' '+str(self.work)}
        self.events.append({'type':'response_item','payload':{'type':'function_call','name':'collaboration.spawn_agent','call_id':cid,'arguments':json.dumps(args)}})
        output={'task_name':'/root/child-'+str(self.call)} if child else {'error':'Selected model is at capacity. Please try a different model.'}
        self.events.append({'type':'response_item','payload':{'type':'function_call_output','call_id':cid,'output':json.dumps(output)}})
        request={'session_log':str(self.path),'call_id':cid}
        if child:
            childid=str(uuid.uuid4());childpath=self.sessions/('rollout-'+childid+'.jsonl')
            source={'subagent':{'thread_spawn':{'parent_thread_id':self.meta_id,'agent_path':output['task_name']}}}
            child_events=[{'type':'session_meta','payload':{'id':childid,'source':source}},
                          {'type':'turn_context','payload':{'model':model,'effort':'high'}},
                          {'timestamp':'2026-10-15T00:01:00Z','type':'event_msg','payload':{'type':'task_complete','error':{'message':'Selected model is at capacity','codex_error_info':'server_overloaded'}}}]
            if live:child_events.append({'type':'event_msg','payload':{'type':'task_started'}})
            childpath.write_text(''.join(json.dumps(e)+'\n' for e in child_events),encoding='utf-8')
            request['child_session_log']=str(childpath)
            self.events.extend([{'type':'response_item','payload':{'type':'function_call','name':'collaboration.list_agents','call_id':'census-'+cid,'arguments':'{}'}},
                                {'timestamp':'2026-10-15T00:01:01Z','type':'response_item','payload':{'type':'function_call_output','call_id':'census-'+cid,'output':json.dumps({'agents':[{'agent_name':output['task_name'],'agent_status':{'errored':'Selected model is at capacity'}}]})}}])
        self.path.write_text(''.join(json.dumps(e)+'\n' for e in self.events),encoding='utf-8')
        path=self.root/('request-'+cid+'.json');write_json(path,request);return path
    def active(self):
        q=self.mutate('queue',case_id='c',stage='build')
        with patch('batch_control.model_ready'):return self.mutate('acquire',token=q['token'])
    def defer(self,q,path):return self.mutate('defer-capacity',case_id='c',token=q['token'],value=path)
    def test_atomic_single_requeue_duplicate_and_cooldown_skip(self):
        q=self.active();path=self.attempt(q);retry=self.defer(q,path)
        self.assertEqual(self.defer(q,path),retry);pool=read_json(self.pool/'queue.json')
        self.assertEqual([r['status'] for r in pool],['released','waiting']);self.assertEqual(retry['model'],'gpt-6.1-sol')
        self.assertEqual(retry['capacity_retry']['cooldown_seconds'],30)
        self.assertEqual(self.mutate('acquire',token=retry['token'])['reason'],'same-model capacity cooldown')
        self.assertEqual(batch.runnable_waiting(self.pool,pool),[])
        self.assertEqual(read_json(self.pool/'b/state.json')['cases']['c']['phase'],'prepared')
    def test_due_retry_retains_model_and_exponential_backoff_is_capped(self):
        q=self.active()
        for expected in (30,60,120,240,300,300):
            retry=self.defer(q,self.attempt(q));self.assertEqual(retry['capacity_retry']['cooldown_seconds'],expected)
            with patch('batch_control.time.time_ns',return_value=retry['capacity_retry']['not_before_ns']+1),patch('batch_control.model_ready'):
                q=self.mutate('acquire',token=retry['token']);self.assertEqual(q['status'],'active')
    def test_wrong_owner_case_and_model_cannot_release(self):
        q=self.active();path=self.attempt(q,wrong_model=True)
        with self.assertRaisesRegex(ValueError,'exact admitted'):self.defer(q,path)
        with self.assertRaises(ValueError):batch.mutate(self.pool,'b',202,'defer-capacity','c',path,q['token'])
        with self.assertRaises(ValueError):self.mutate('defer-capacity',case_id='other',value=path,token=q['token'])
        self.assertEqual(read_json(self.pool/'queue.json')[0]['status'],'active')
    def test_terminal_child_with_actual_latest_census_can_defer(self):
        q=self.active();path=self.attempt(q,child=True);retry=self.defer(q,path)
        self.assertIsNotNone(retry['capacity_retry']['proof']['child_terminal']);self.assertEqual(retry['status'],'waiting')
    def test_restarted_child_retains_active_even_with_old_errored_census(self):
        q=self.active();path=self.attempt(q,child=True,live=True)
        with self.assertRaisesRegex(ValueError,'live, resumed'):self.defer(q,path)
        self.assertEqual(read_json(self.pool/'queue.json')[0]['status'],'active')
    def test_terminal_child_without_real_census_and_later_continuation_reject(self):
        q=self.active();path=self.attempt(q,child=True)
        events=self.events[:-2];self.path.write_text(''.join(json.dumps(e)+'\n' for e in events),encoding='utf-8')
        with self.assertRaisesRegex(ValueError,'agent census'):self.defer(q,path)
        self.events.append({'type':'response_item','payload':{'type':'function_call','name':'collaboration.followup_task','call_id':'resume','arguments':json.dumps({'target':'/root/child-1','message':'resume'})}})
        self.path.write_text(''.join(json.dumps(e)+'\n' for e in self.events),encoding='utf-8')
        with self.assertRaisesRegex(ValueError,'later continuation'):self.defer(q,path)
    def test_cooldown_does_not_block_other_batch_ready_models(self):
        q=self.active();retry=self.defer(q,self.attempt(q));self.create('other')
        other=batch.mutate(self.pool,'other',101,'queue','c',stage='build')
        with patch('batch_control.model_ready'):
            self.assertEqual(batch.mutate(self.pool,'other',101,'acquire',token=other['token'])['status'],'active')
        self.assertEqual(self.mutate('acquire',token=retry['token'])['reason'],'same-model capacity cooldown')
    def test_queue_write_failure_is_all_or_nothing_and_crash_after_commit_idempotent(self):
        q=self.active();path=self.attempt(q);before=read_json(self.pool/'queue.json')
        with patch('batch_control.write_json',side_effect=OSError('fixture disk')):
            with self.assertRaises(OSError):self.defer(q,path)
        self.assertEqual(read_json(self.pool/'queue.json'),before)
        retry=self.defer(q,path);self.assertEqual(self.defer(q,path)['token'],retry['token'])


def load_tests(loader,tests,pattern):
    return unittest.TestSuite(CapacityTests(name) for name in CapacityTests.__dict__ if name.startswith('test_'))


if __name__=='__main__':unittest.main()
