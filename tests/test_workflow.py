"""Meaningful resource/recovery and evidence invariants; all runs are fixtures."""
import copy
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
from common import digest,read_json,write_json
import batch_control as batch
from process_guard import owned_processes,background_entry_owned
from media_evidence import validate
from evidence_index import create,check,review_input
from audit_inheritance import validate as validate_audit,DECISIONS

class WorkflowTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name);self.pool=self.root/'batches'
        cases=[]
        for i in range(1,5):
            work=self.root/f'work{i}';work.mkdir();source=work/'source.docx';source.write_bytes(b'doc-fixture')
            cases.append({'case_id':f'c{i}','workspace':str(work),'source_docx':str(source),'source_sha256':digest(source)})
        self.cases=self.root/'cases.json';write_json(self.cases,{'cases':cases})
        batch.register(self.pool,'test-batch',self.cases,'explicit test fixture authorization',4)
        self.identity=patch('batch_control.identity',side_effect=lambda pid:{'pid':pid,'created_ticks':1000+pid});self.identity.start()
        batch.claim(self.pool,'test-batch',101)
    def tearDown(self):self.identity.stop();self.temp.cleanup()
    def mutate(self,action,case_id=None,**kwargs):return batch.mutate(self.pool,'test-batch',101,action,case_id,**kwargs)
    def second_batch(self):
        batch.register(self.pool,'second-batch',self.cases,'explicit second test fixture authorization',4)
        batch.claim(self.pool,'second-batch',102)
        return lambda action,case_id=None,**kwargs:batch.mutate(self.pool,'second-batch',102,action,case_id,**kwargs)
    def preflight(self):
        checks=[]
        for kind in ('workspace_write','read_only','browser','word_render'):
            log=self.root/(kind+'.log');log.write_text('actual fixture command output')
            checks.append({'kind':kind,'command':'fixture-command '+kind,'exit_code':0,'log':str(log),'sha256':digest(log)})
        proof=self.root/'preflight.json';write_json(proof,{'status':'ready','zero_model_calls':0,'checks':checks})
        return self.mutate('preflight',value=proof)
    def test_preflight_registration_reaches_model_slot_acquisition(self):
        ticket=self.mutate('queue','c1',stage='build')
        with self.assertRaisesRegex(ValueError,'zero-model'):self.mutate('acquire',token=ticket['token'])
        result=self.preflight();self.assertIn('environment_preflight',result)
        self.assertEqual(self.mutate('acquire',token=ticket['token'])['status'],'active')
    def test_frozen_manifest_and_host_capacity_preserve_original_models(self):
        self.preflight();manifest=read_json(self.pool/'test-batch/manifest.json');original=digest(self.pool/'test-batch/manifest.json')
        self.assertEqual(manifest['execution_profile']['capacities'],batch.CAPACITIES)
        self.assertEqual(manifest['models']['repair'],['gpt-6.1-sol','ultra'])
        tickets=[self.mutate('queue',f'c{i}',stage='build') for i in range(1,5)]
        for ticket in tickets[:3]:self.assertEqual(self.mutate('acquire',token=ticket['token'])['status'],'active')
        self.assertFalse(self.mutate('acquire',token=tickets[3]['token'])['acquired'])
        self.mutate('release-slot',token=tickets[0]['token']);self.assertEqual(self.mutate('acquire',token=tickets[3]['token'])['status'],'active')
        self.assertEqual(digest(self.pool/'test-batch/manifest.json'),original)
        with self.assertRaisesRegex(ValueError,'frozen'):batch.register(self.pool,'test-batch',self.cases,'authorization',4)
    def test_priority_updates_waiting_ticket_without_interrupting_active(self):
        self.preflight();first=self.mutate('queue','c1',stage='review');second=self.mutate('queue','c2',stage='review')
        self.assertFalse(self.mutate('acquire',token=second['token'])['acquired'])
        self.mutate('priority','c2',value=10)
        self.assertEqual(self.mutate('acquire',token=second['token'])['status'],'active')
        self.mutate('priority','c2',value=20)
        pool=read_json(self.pool/'queue.json');self.assertEqual(next(t for t in pool if t['token']==second['token'])['priority'],10)
    def test_same_or_backward_clock_keeps_fifo_across_batches_without_rewriting_history(self):
        self.preflight();other=self.second_batch();other('preflight',value=self.root/'preflight.json')
        with patch('batch_control.time.time_ns',return_value=1000000000):
            first=self.mutate('queue','c1',stage='build');second=other('queue','c2',stage='build')
        with patch('batch_control.time.time_ns',return_value=999999999):third=other('queue','c3',stage='build')
        submitted=[row['submitted_ns'] for row in (first,second,third)]
        self.assertEqual(submitted,[1000000000,1000000001,1000000002])
        self.assertFalse(other('acquire',token=second['token'])['acquired'])
        self.assertEqual(self.mutate('acquire',token=first['token'])['status'],'active')
        self.assertEqual(other('acquire',token=second['token'])['status'],'active')
        self.mutate('release-slot',token=first['token'])
        current={row['token']:row['submitted_ns'] for row in read_json(self.pool/'queue.json')}
        self.assertEqual([current[row['token']] for row in (first,second,third)],submitted)
    def test_expedite_scope_requeues_waiting_review_but_does_not_touch_active(self):
        self.preflight();waiting=self.mutate('queue','c1',stage='review')
        with self.assertRaises(ValueError):self.mutate('expedite','c1')
        def authorization(case_id):
            work=self.root/('work'+case_id[1:]);run_id='fixture-'+case_id;write_json(work/'.product-v2/run.json',{'workspace':str(work),'run_id':run_id})
            sessions=self.root/'sessions';sessions.mkdir(exist_ok=True);log=sessions/(case_id+'.jsonl');statement=case_id+' 使用原加急模式'
            message={'type':'response_item','payload':{'type':'message','role':'user','content':[{'type':'input_text','text':statement}]}}
            log.write_text(json.dumps(message)+'\n',encoding='utf8')
            proof=self.root/(case_id+'-authorization.json');write_json(proof,{'run_id':run_id,'workspace':str(work),'scope_name':case_id,'statement':statement,'session_log':str(log),'user_message_sha256':__import__('hashlib').sha256(statement.encode()).hexdigest()})
            return proof
        with patch('contracts.SESSION_ROOT',self.root/'sessions'):self.mutate('expedite','c1',authorization=authorization('c1'))
        pool=read_json(self.pool/'queue.json');self.assertEqual(pool[0]['stage'],'expedited')
        with patch('contracts.SESSION_ROOT',self.root/'sessions'):
            self.assertEqual(self.mutate('acquire',token=waiting['token'])['status'],'active')
        normal=self.mutate('queue','c2',stage='review');self.mutate('acquire',token=normal['token'])
        with patch('contracts.SESSION_ROOT',self.root/'sessions'):self.mutate('expedite','c2',authorization=authorization('c2'))
        self.assertEqual(next(t for t in read_json(self.pool/'queue.json') if t['token']==normal['token'])['stage'],'review')
        with self.assertRaisesRegex(ValueError,'registered'):self.mutate('expedite','other-batch-case',authorization='explicit fixture')
    def test_capture_releases_before_evidence_and_evidence_drains_record_group(self):
        record=self.mutate('queue','c1',stage='record')
        with patch('batch_control.memory_available_mb',return_value=10000):self.mutate('acquire',token=record['token'])
        with self.assertRaises(ValueError):self.mutate('queue','c1',stage='evidence')
        second=self.mutate('queue','c2',stage='record')
        with patch('batch_control.memory_available_mb',return_value=10000):self.assertEqual(self.mutate('acquire',token=second['token'])['status'],'active')
        self.mutate('release-slot',token=record['token']);evidence=self.mutate('queue','c1',stage='evidence')
        self.assertFalse(self.mutate('acquire',token=evidence['token'])['acquired'])
        third=self.mutate('queue','c3',stage='record')
        with patch('batch_control.memory_available_mb',return_value=10000):self.assertFalse(self.mutate('acquire',token=third['token'])['acquired'])
        self.mutate('release-slot',token=second['token']);self.assertEqual(self.mutate('acquire',token=evidence['token'])['status'],'active')
        other=self.mutate('queue','c2',stage='evidence');self.assertFalse(self.mutate('acquire',token=other['token'])['acquired'])
        self.mutate('release-slot',token=evidence['token']);self.assertEqual(self.mutate('acquire',token=other['token'])['status'],'active')
        self.mutate('release-slot',token=other['token'])
        with patch('batch_control.memory_available_mb',return_value=10000):self.assertEqual(self.mutate('acquire',token=third['token'])['status'],'active')
    def test_drained_waiting_evidence_does_not_block_other_batch_capture_or_evidence(self):
        other=self.second_batch();manifest=digest(self.pool/'test-batch/manifest.json')
        ticket=self.mutate('queue','c1',stage='evidence')
        self.mutate('drain',authorization='explicit pause fixture')
        self.assertFalse(self.mutate('acquire',token=ticket['token'])['acquired'])
        record=other('queue','c1',stage='record')
        with patch('batch_control.memory_available_mb',return_value=10000):self.assertEqual(other('acquire',token=record['token'])['status'],'active')
        other('release-slot',token=record['token']);evidence=other('queue','c1',stage='evidence')
        self.assertEqual(other('acquire',token=evidence['token'])['status'],'active')
        self.assertEqual(next(q for q in read_json(self.pool/'queue.json') if q['token']==ticket['token']),ticket)
        self.assertEqual(digest(self.pool/'test-batch/manifest.json'),manifest)
    def test_continue_restores_original_fifo_and_priority_after_active_capture_finishes(self):
        other=self.second_batch();first=self.mutate('queue','c1',stage='evidence')
        self.mutate('drain',authorization='explicit pause fixture')
        record=other('queue','c1',stage='record')
        with patch('batch_control.memory_available_mb',return_value=10000):self.assertEqual(other('acquire',token=record['token'])['status'],'active')
        later=other('queue','c2',stage='evidence');priority=other('queue','c3',stage='evidence')
        other('priority','c3',value=10);next_record=other('queue','c4',stage='record')
        self.mutate('continue',authorization='explicit resume fixture')
        self.assertFalse(self.mutate('acquire',token=first['token'])['acquired'])
        self.assertFalse(other('acquire',token=priority['token'])['acquired'])
        with patch('batch_control.memory_available_mb',return_value=10000):self.assertFalse(other('acquire',token=next_record['token'])['acquired'])
        other('release-slot',token=record['token'])
        self.assertFalse(self.mutate('acquire',token=first['token'])['acquired'])
        self.assertEqual(other('acquire',token=priority['token'])['status'],'active')
        other('release-slot',token=priority['token'])
        self.assertFalse(other('acquire',token=later['token'])['acquired'])
        acquired=self.mutate('acquire',token=first['token'])
        self.assertEqual(acquired['status'],'active');self.assertEqual(acquired['submitted_ns'],first['submitted_ns']);self.assertEqual(acquired['priority'],first['priority'])
        self.mutate('release-slot',token=first['token']);self.assertEqual(other('acquire',token=later['token'])['status'],'active')
        other('release-slot',token=later['token'])
        with patch('batch_control.memory_available_mb',return_value=10000):self.assertEqual(other('acquire',token=next_record['token'])['status'],'active')
    def test_draining_active_capture_keeps_other_batch_evidence_blocked_until_release(self):
        other=self.second_batch();record=self.mutate('queue','c1',stage='record')
        with patch('batch_control.memory_available_mb',return_value=10000):active=self.mutate('acquire',token=record['token'])
        self.mutate('drain',authorization='explicit pause fixture');evidence=other('queue','c1',stage='evidence')
        self.assertFalse(other('acquire',token=evidence['token'])['acquired'])
        self.assertEqual(next(q for q in read_json(self.pool/'queue.json') if q['token']==record['token']),active)
        self.mutate('release-slot',token=record['token']);self.assertEqual(other('acquire',token=evidence['token'])['status'],'active')
    def test_draining_active_evidence_keeps_other_batch_capture_blocked_until_release(self):
        other=self.second_batch();evidence=self.mutate('queue','c1',stage='evidence');active=self.mutate('acquire',token=evidence['token'])
        self.mutate('drain',authorization='explicit pause fixture');record=other('queue','c1',stage='record')
        with patch('batch_control.memory_available_mb',return_value=10000):self.assertFalse(other('acquire',token=record['token'])['acquired'])
        self.assertEqual(next(q for q in read_json(self.pool/'queue.json') if q['token']==evidence['token']),active)
        self.mutate('release-slot',token=evidence['token'])
        with patch('batch_control.memory_available_mb',return_value=10000):self.assertEqual(other('acquire',token=record['token'])['status'],'active')
    def test_blocked_case_waiting_evidence_resumes_original_ticket_with_recovery_history(self):
        other=self.second_batch();ticket=self.mutate('queue','c1',stage='evidence')
        update=self.root/'blocked-evidence.json';write_json(update,{'phase':'blocked','blocked_fingerprint':'media-failure','calls':['prior-call'],'usage':[{'tokens':20}]})
        self.mutate('update','c1',value=update)
        self.assertFalse(self.mutate('acquire',token=ticket['token'])['acquired'])
        record=other('queue','c1',stage='record')
        with patch('batch_control.memory_available_mb',return_value=10000):self.assertEqual(other('acquire',token=record['token'])['status'],'active')
        other('release-slot',token=record['token']);later=other('queue','c1',stage='evidence')
        self.assertEqual(other('acquire',token=later['token'])['status'],'active')
        log=self.root/'media-recovery.log';log.write_text('actual new media recovery fixture')
        proof=self.root/'media-ready.json';write_json(proof,{'status':'ready','blocked_fingerprint':'media-failure','recovery_evidence':[{'path':str(log),'sha256':digest(log)}]})
        state=self.mutate('resume-case','c1',value=proof)
        self.assertEqual(state['cases']['c1']['calls'],['prior-call']);self.assertEqual(state['cases']['c1']['usage'],[{'tokens':20}])
        self.assertFalse(self.mutate('acquire',token=ticket['token'])['acquired'])
        other('release-slot',token=later['token']);acquired=self.mutate('acquire',token=ticket['token'])
        self.assertEqual(acquired['status'],'active');self.assertEqual(acquired['submitted_ns'],ticket['submitted_ns'])
    def test_ownerless_waiting_evidence_cannot_block_other_batch_but_active_capture_stays_reserved(self):
        other=self.second_batch();waiting=self.mutate('queue','c1',stage='evidence');record=other('queue','c1',stage='record')
        with patch('batch_control.identity',side_effect=lambda pid:None if pid==101 else {'pid':pid,'created_ticks':1000+pid}),patch('batch_control.memory_available_mb',return_value=10000):
            self.assertEqual(other('acquire',token=record['token'])['status'],'active')
        self.assertEqual(next(q for q in read_json(self.pool/'queue.json') if q['token']==waiting['token']),waiting)
        other('release-slot',token=record['token']);self.assertEqual(self.mutate('acquire',token=waiting['token'])['status'],'active')
        self.mutate('release-slot',token=waiting['token']);capture=self.mutate('queue','c1',stage='record')
        with patch('batch_control.memory_available_mb',return_value=10000):self.mutate('acquire',token=capture['token'])
        evidence=other('queue','c2',stage='evidence')
        with patch('batch_control.identity',side_effect=lambda pid:None if pid==101 else {'pid':pid,'created_ticks':1000+pid}):
            self.assertFalse(other('acquire',token=evidence['token'])['acquired'])
        self.assertEqual(next(q for q in read_json(self.pool/'queue.json') if q['token']==capture['token'])['status'],'active')
    def test_missing_or_changed_current_owner_excludes_old_waiting_ticket_without_removing_history(self):
        other=self.second_batch();ticket=self.mutate('queue','c1',stage='evidence')
        self.mutate('release-owner');evidence=other('queue','c1',stage='evidence')
        self.assertEqual(other('acquire',token=evidence['token'])['status'],'active');other('release-slot',token=evidence['token'])
        batch.claim(self.pool,'test-batch',103);record=other('queue','c1',stage='record')
        with patch('batch_control.memory_available_mb',return_value=10000):self.assertEqual(other('acquire',token=record['token'])['status'],'active')
        self.assertEqual(next(q for q in read_json(self.pool/'queue.json') if q['token']==ticket['token']),ticket)
        self.assertFalse(batch.mutate(self.pool,'test-batch',103,'acquire',token=ticket['token'])['acquired'])
        other('release-slot',token=record['token']);batch.mutate(self.pool,'test-batch',103,'release-slot',token=ticket['token'])
        current=batch.mutate(self.pool,'test-batch',103,'queue','c1',stage='evidence')
        self.assertEqual(batch.mutate(self.pool,'test-batch',103,'acquire',token=current['token'])['status'],'active')
    def test_released_and_orphaned_waiting_tickets_and_failed_capture_release_do_not_block(self):
        other=self.second_batch();cancelled=self.mutate('queue','c1',stage='evidence')
        self.mutate('release-slot',token=cancelled['token']);orphan=self.mutate('queue','c2',stage='evidence')
        with patch('batch_control.identity',side_effect=lambda pid:None if pid==101 else {'pid':pid,'created_ticks':1000+pid}):batch.claim(self.pool,'test-batch',103,True)
        record=other('queue','c1',stage='record')
        with patch('batch_control.memory_available_mb',return_value=10000):self.assertEqual(other('acquire',token=record['token'])['status'],'active')
        with self.assertRaisesRegex(RuntimeError,'capture fixture failure'):
            try:raise RuntimeError('capture fixture failure')
            finally:other('release-slot',token=record['token'])
        evidence=other('queue','c1',stage='evidence');self.assertEqual(other('acquire',token=evidence['token'])['status'],'active')
        pool={q['token']:q for q in read_json(self.pool/'queue.json')}
        self.assertEqual(pool[cancelled['token']]['status'],'released');self.assertEqual(pool[orphan['token']]['status'],'orphaned')
        self.assertEqual(pool[record['token']]['status'],'released')
    def test_recording_memory_admission_uses_lowest_actual_memory(self):
        ticket=self.mutate('queue','c1',stage='record')
        with patch('batch_control.memory_available_mb',return_value=4095):self.assertEqual(self.mutate('acquire',token=ticket['token'])['reason'],'memory_exhausted')
        with patch('batch_control.memory_available_mb',return_value=4096):self.assertEqual(self.mutate('acquire',token=ticket['token'])['status'],'active')
        second=self.mutate('queue','c2',stage='record')
        with patch('batch_control.memory_available_mb',return_value=6143):self.assertFalse(self.mutate('acquire',token=second['token'])['acquired'])
    def test_case_cannot_double_occupy_and_drain_requires_authorization(self):
        self.preflight();ticket=self.mutate('queue','c1',stage='build')
        with self.assertRaisesRegex(ValueError,'already'):self.mutate('queue','c1',stage='review')
        with self.assertRaises(ValueError):self.mutate('drain')
        self.mutate('drain',authorization='explicit pause fixture')
        self.assertFalse(self.mutate('acquire',token=ticket['token'])['acquired'])
        self.mutate('continue',authorization='explicit resume fixture')
        self.assertEqual(self.mutate('acquire',token=ticket['token'])['status'],'active')
    def test_resume_preserves_calls_and_requires_current_recovery_log_hash(self):
        update=self.root/'blocked.json';write_json(update,{'phase':'blocked','blocked_fingerprint':'failure-123','calls':['old-call'],'usage':[{'tokens':20}]})
        self.mutate('update','c1',value=update)
        log=self.root/'recovery.log';log.write_text('new constrained execution fixture')
        proof=self.root/'ready.json';write_json(proof,{'status':'ready','blocked_fingerprint':'failure-123','recovery_evidence':[{'path':str(log),'sha256':digest(log)}]})
        state=self.mutate('resume-case','c1',value=proof);self.assertEqual(state['cases']['c1']['calls'],['old-call'])
        log.write_text('changed')
        with self.assertRaisesRegex(ValueError,'hash'):self.mutate('resume-case','c1',value=proof)
    def test_one_live_parent_and_explicit_stale_owner_recovery(self):
        with self.assertRaisesRegex(ValueError,'live parent'):batch.claim(self.pool,'test-batch',102)
        with patch('batch_control.identity',side_effect=lambda pid:None if pid==101 else {'pid':pid,'created_ticks':1000+pid}):
            with self.assertRaisesRegex(ValueError,'Stale'):batch.claim(self.pool,'test-batch',102)
            self.assertEqual(batch.claim(self.pool,'test-batch',102,True)['pid'],102)
    def test_read_only_search_processes_are_not_case_backgrounds(self):
        work=self.root/'work1'
        rows=[{'pid':1,'parent_pid':0,'name':'pwsh.exe','command':f'pwsh -Command Get-Content "{work}/server.py"','created_ticks':1,'ports':[]},
              {'pid':2,'parent_pid':0,'name':'rg.exe','command':f'rg --files "{work}"','created_ticks':2,'ports':[]},
              {'pid':3,'parent_pid':0,'name':'python.exe','command':f'python -c "print(\"{work}/server.py\")"','created_ticks':3,'ports':[]},
              {'pid':4,'parent_pid':0,'name':'python.exe','command':f'python "{work}/server.py"','created_ticks':4,'ports':[8123]}]
        self.assertEqual([r['pid'] for r in owned_processes(work,rows)],[4])
    def test_evidence_index_never_auto_fills_missing_ids_and_binds_hashes(self):
        work=self.root/'work1';a=work/'a.png';b=work/'b.log';a.write_bytes(b'a');b.write_text('b')
        manifest=self.root/'evidence.json';write_json(manifest,{'files':['a.png','b.log']});index=work/'index.json';create(work,manifest,index)
        self.assertFalse(check(index,['E001'],work)['complete']);self.assertEqual(check(index,['E001'],work)['missing'],['E002'])
        with self.assertRaises(ValueError):check(index,['E001','E001'],work)
        a.write_bytes(b'changed')
        with self.assertRaisesRegex(ValueError,'changed'):check(index,['E001','E002'],work)
    def test_neutral_review_facts_bind_hashes_without_decision_or_viewed_ids(self):
        work=self.root/'work1';output=self.root/'output';output.mkdir();(output/'result.csv').write_text('value\n1\n')
        png=work/'figure.png';png.write_bytes(b'actual fixture image');log=work/'check.log';log.write_text('fixture actual execution evidence')
        write_json(work/'.product-v2/run.json',{'run_id':'fixture','output':str(output)})
        write_json(work/'.product-v2/chart-manifest.json',{'figures':[{'figure_id':1,'png':'figure.png','sha256':digest(png)}]})
        manifest=work/'manifest.json';write_json(manifest,{'files':['figure.png','check.log']});index=work/'index.json';create(work,manifest,index)
        facts=work/'facts.json';review_input(work,index,facts);value=read_json(facts)
        for forbidden in ('decision','reviewer_agent_id','reviewed_evidence','chart_reviews'):self.assertNotIn(forbidden,value)
        self.assertEqual(value['current_artifacts'],{'result.csv':digest(output/'result.csv')})
        with self.assertRaisesRegex(ValueError,'overwrite'):review_input(work,index,facts)
        png.write_bytes(b'changed');
        with self.assertRaisesRegex(ValueError,'changed'):review_input(work,index,work/'new-facts.json')
    def test_analytical_review_facts_carry_policy_and_actual_visual_requirements(self):
        work=self.root/'work1';output=self.root/'analytical-output';output.mkdir()
        png=work/'analytical.png';png.write_bytes(b'fixture PNG')
        write_json(work/'.product-v2/run.json',{'run_id':'analytical','output':str(output),'chart_policy':'analytical-v1'})
        figure={'figure_id':1,'png':png.name,'sha256':digest(png),'caption':'图1 调度轨迹',
                'question':'延迟怎样影响调度','data_source':'input.csv和调度实际输出','chart_type':'schedule','labels':['时间','设备']}
        chart_path=work/'.product-v2/chart-manifest.json';write_json(chart_path,{'figures':[figure]})
        manifest=work/'analytical-evidence.json';write_json(manifest,{'files':[png.name]})
        index=work/'analytical-index.json';create(work,manifest,index)
        target=work/'analytical-facts.json';review_input(work,index,target);facts=read_json(target)
        self.assertEqual(facts['current_charts']['chart_policy'],'analytical-v1')
        self.assertIn('no_schematic_evidence',facts['chart_review_requirements']['visual_evidence'])
        self.assertIn('before/red explanation/after',facts['chart_review_requirements']['instruction'])
        for forbidden in ('decision','reviewer_agent_id','reviewed_evidence','chart_reviews'):self.assertNotIn(forbidden,facts)
        figure['labels']=['示意'];write_json(chart_path,{'figures':[figure]})
        with self.assertRaisesRegex(ValueError,'must not contain 示意'):review_input(work,index,work/'bad-facts.json')
        figure['labels']=['时间'];write_json(chart_path,{'figures':[figure,figure]})
        with self.assertRaisesRegex(ValueError,'Distinct positive figure_id'):review_input(work,index,work/'duplicate-facts.json')
        write_json(work/'.product-v2/run.json',{'run_id':'analytical','output':str(output),'chart_policy':'unknown'})
        with self.assertRaisesRegex(ValueError,'Unknown chart policy'):review_input(work,index,work/'unknown-facts.json')
    def test_full_source_index_and_effective_requirements_are_present(self):
        result=validate_audit();self.assertEqual(result['sources'],26);self.assertGreater(result['clauses'],900)
        self.assertGreater(len(DECISIONS),70)

if __name__=='__main__':unittest.main()
