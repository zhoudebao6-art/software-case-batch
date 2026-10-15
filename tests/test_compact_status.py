"""Read-only status projections, including stale journals and malformed records."""
from contextlib import redirect_stdout
import io
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
import batch_control as batch
import scheduler_policy as scheduler
from common import read_json,write_json


class CompactStatusTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name);self.target=self.root/'b'
        self.manifest={'batch_id':'b','cases':[{'case_id':'a','workspace':'do-not-scan'},
                                            {'case_id':'z','workspace':'do-not-scan-z'}]}
        self.state={'drain':True,'cases':{'a':{'phase':'blocked','calls':[], 'pending':[],
                        'blocker':'actual reproducible error','blocked_fingerprint':'fingerprint',
                        'recovery':{'path':'new-recovery.json','sha256':'saved-hash'}},
                        'z':{'phase':'delivered','calls':[],'pending':[]}},
                    'control_decision':{'revision':7,'action':'drain','applied_ns':123},
                    'control_decisions':[{'revision':1,'action':'continue'}]*200}
        self.pool=[{'batch_id':'b','case_id':'a','token':'live','stage':'build','status':'waiting','owner':{'pid':12}},
                   {'batch_id':'b','case_id':'a','token':'old','stage':'build','status':'released'},
                   {'batch_id':'other','case_id':'c','token':'external','stage':'review','status':'active'}]
        self.save();write_json(self.target/'owner.json',{'pid':123,'created_ticks':345})

    def tearDown(self):self.temp.cleanup()

    def save(self):
        write_json(self.target/'manifest.json',self.manifest);write_json(self.target/'state.json',self.state)
        write_json(self.root/'queue.json',self.pool)

    def run_status(self,*args):
        output=io.StringIO()
        with patch.object(sys,'argv',['batch_control.py','status','--root',str(self.root),'--batch-id','b',*args]),redirect_stdout(output):
            code=batch.main()
        text=output.getvalue()
        return code,json.loads(text) if code==0 else text

    def run_read_only_status(self,*args):
        before={str(p):(p.read_bytes(),p.stat().st_mtime_ns) for p in self.root.rglob('*') if p.is_file()}
        with patch.object(batch,'digest',side_effect=AssertionError('No source/delivery/media hashes')):
            result=self.run_status('--compact',*args)
        self.assertEqual(before,{str(p):(p.read_bytes(),p.stat().st_mtime_ns)
                                 for p in self.root.rglob('*') if p.is_file()})
        return result

    def test_full_default_matches_original_payload(self):
        code,result=self.run_status()
        self.assertEqual(code,0)
        self.assertEqual(result,{'manifest':self.manifest,'state':self.state,'scheduler':scheduler.config(self.root),
                                 'current_tickets':[self.pool[0]]})

    def test_read_only_no_workspace_scan_and_single_read_per_loaded_record(self):
        before={str(p):p.read_bytes() for p in self.root.rglob('*') if p.is_file()}
        with patch.object(batch,'read_json',wraps=read_json) as reads,patch.object(batch,'digest',side_effect=AssertionError('No hashes')):
            code,result=self.run_status('--compact')
        self.assertEqual(code,0)
        paths=[Path(c.args[0]).name for c in reads.call_args_list]
        self.assertEqual(sorted(paths),['manifest.json','owner.json','queue.json','state.json'])
        self.assertEqual(before,{str(p):p.read_bytes() for p in self.root.rglob('*') if p.is_file()})
        self.assertTrue(result['drain']);self.assertEqual(result['owner']['pid'],123)
        self.assertEqual(result['control_decision']['revision'],7)
        self.assertEqual(result['cases'][0]['blocker'],'actual reproducible error')
        self.assertEqual(result['cases'][0]['recovery']['path'],'new-recovery.json')
        self.assertIn('no fresh acceptance',result['scope'].lower())
        self.assertIn('not verified publication',result['scope'])

    def test_target_case_and_unknown_case_rejected_for_both_views(self):
        for compact in [[],['--compact']]:
            code,result=self.run_status(*compact,'--case-id','z');self.assertEqual(code,0)
            self.assertEqual([c['case_id'] for c in result['cases']] if compact else list(result['state']['cases']),['z'])
            self.assertEqual(result['current_tickets'],[])
            code,error=self.run_status(*compact,'--case-id','wrong');self.assertEqual(code,2)
            self.assertIn('Unknown registered case_id',error)

    def test_unknown_phase_missing_and_unregistered_state_remain_visible(self):
        self.state['cases']['a']['phase']='future-phase';del self.state['cases']['z']
        self.state['cases']['ghost']={'phase':'blocked','blocker':'unregistered still blocked'};self.save()
        code,result=self.run_status('--compact');self.assertEqual(code,0)
        rows={c['case_id']:c for c in result['cases']}
        self.assertEqual(rows['a']['phase'],'future-phase');self.assertTrue(rows['a']['warnings'])
        self.assertIsNone(rows['z']['phase']);self.assertFalse(rows['z']['state_present'])
        self.assertFalse(rows['ghost']['registered']);self.assertEqual(rows['ghost']['blocker'],'unregistered still blocked')
        self.assertEqual(result['counts']['phases'],{'future-phase':1,'unknown':1,'blocked':1})
        code,_=self.run_status('--compact','--case-id','ghost');self.assertEqual(code,2)

    def test_large_history_retains_latest_call_and_current_pending(self):
        item=self.state['cases']['a'];item['calls']=[{'status':'completed','source':'x'*5000}]*1000
        item['calls'].append({'stage':'review','status':'errored','model':'gpt-6.1-sol','error':'service capacity',
                              'call_id':'current-call','session_log':'current.jsonl','source':'x'*5000})
        item['usage']=[{'log':'y'*5000}]*1000
        item['pending']=[{'token':'old','status':'active','reason':'obsolete'}]*1000
        item['pending'] += [{'token':'live','status':'active','reason':'await resource'},
                            {'token':'unknown','status':'future-status','reason':'keep unknown blocker'}]
        self.save();_,full=self.run_status();code,result=self.run_status('--compact');self.assertEqual(code,0)
        row=result['cases'][0];self.assertEqual(row['latest_call']['call_id'],'current-call')
        self.assertEqual(row['latest_call']['error'],'service capacity')
        self.assertEqual(row['call_count'],1001)
        self.assertEqual([p['token'] for p in row['pending']],['live','unknown'])
        self.assertEqual(row['pending'][0]['status'],'waiting')
        self.assertLess(len(json.dumps(result)),len(json.dumps(full))/100)
        self.assertNotIn('source',row['latest_call']);self.assertNotIn('control_decisions',result)

    def test_scheduler_snapshot_reused_and_reservations_not_dispatch(self):
        settings={'mode':scheduler.ADAPTIVE_CONTRACT,'model_pool_capacity':3,
                  'history':[{'action':'old','previous':{'log':'x'*10000}}]*1000+
                            [{'action':'bind-controller','revision':1001,'at_ns':12}]}
        census={'groups':[{'group':'g','worker_ceiling':1,'reserved_model_slots':1,'unreserved_model_slots':0}],
                'model_pool_capacity':3,'unreserved_global_model_slots':2,'active_model_reservations':1,
                'unknown_active_model_reservations':1,'scope':'local reservations only'}
        with patch.object(scheduler,'config',return_value=settings),patch.object(scheduler,'snapshot',return_value=census) as snapshot:
            code,result=self.run_status('--compact')
        self.assertEqual(code,0);snapshot.assert_called_once_with(str(self.root),self.pool,settings)
        self.assertEqual(result['scheduler']['reservations'],census)
        self.assertEqual(result['scheduler']['latest_control']['revision'],1001)
        self.assertIn('not actual dispatch',result['scheduler']['scope'])
        self.assertNotIn('dispatch_count',result['scheduler'])

    def test_recording_and_capacity_cooldown_keep_current_resume_details(self):
        item=self.state['cases']['a'];item['recording_pending']={'path':'capture-pending.json','sha256':'capture-hash'}
        item['maintenance_pause']={'reason':'current user maintenance'};item['resume_action']='reuse actual capture'
        retry={'failed_token':'old','not_before_ns':999999,'cooldown_seconds':30,
               'proof':{'session_log':'actual-session.jsonl','call_id':'failed-call','events_sha256':'actual-hash'}}
        self.pool[0]['capacity_retry']=retry;self.save()
        code,result=self.run_status('--compact');self.assertEqual(code,0)
        self.assertEqual(result['cases'][0]['recording_pending'],item['recording_pending'])
        self.assertEqual(result['cases'][0]['maintenance_pause'],item['maintenance_pause'])
        self.assertEqual(result['cases'][0]['resume_action'],'reuse actual capture')
        self.assertEqual(result['current_tickets'][0]['capacity_retry'],retry)
        self.assertIn('not actual publication counts',result['scope'])

    def test_unreliable_field_types_do_not_claim_ready_or_drop_blockers(self):
        item=self.state['cases']['a'];item.update(phase={'unexpected':'phase'},pending={'error':'actual pending error'},calls=[None])
        self.state['drain']='false';self.save()
        code,result=self.run_status('--compact');self.assertEqual(code,0)
        self.assertEqual(result['drain'],'false');self.assertTrue(result['warnings'])
        self.assertEqual(result['cases'][0]['pending'],{'error':'actual pending error'})
        self.assertEqual(result['cases'][0]['blocker'],'actual reproducible error')
        self.assertTrue(result['cases'][0]['warnings'])
        item['calls']=['actual unstructured latest call error '+('x'*5000)];self.save()
        code,result=self.run_status('--compact');self.assertEqual(code,0)
        latest=result['cases'][0]['latest_call']
        self.assertIn('actual unstructured latest call error',latest['invalid_record_preview'])
        self.assertTrue(latest['truncated'])

    def test_real_read_errors_and_invalid_top_level_collections_fail(self):
        self.target.joinpath('state.json').write_text('{',encoding='utf-8')
        code,error=self.run_status('--compact');self.assertEqual(code,2);self.assertIn('ERROR:',error)
        self.state['cases']=[];self.save()
        code,error=self.run_status('--compact');self.assertEqual(code,2);self.assertIn('state cases an object',error)
        self.save()
        with patch.object(scheduler,'snapshot',side_effect=OSError('real snapshot error')),\
             patch.object(scheduler,'config',return_value={'mode':scheduler.ADAPTIVE_CONTRACT}):
            code,error=self.run_status('--compact')
        self.assertEqual(code,2);self.assertIn('real snapshot error',error)

    def test_unknown_queue_status_cannot_disappear_when_pending_is_empty(self):
        self.pool=[{'batch_id':'b','case_id':'a','token':'broken','stage':'build',
                    'status':'unexpected-corrupt-status','error':'actual unresolved dispatch error'}]
        self.save();code,result=self.run_read_only_status();self.assertEqual(code,0)
        self.assertEqual(result['cases'][0]['pending'],[])
        self.assertEqual(result['current_tickets'][0]['status'],'unexpected-corrupt-status')
        self.assertEqual(result['current_tickets'][0]['error'],'actual unresolved dispatch error')
        self.assertTrue(any('queue.json[0]' in warning for warning in result['warnings']))
        code,full=self.run_status();self.assertEqual(code,0);self.assertEqual(full['current_tickets'],[])

    def test_queue_missing_status_or_legacy_identity_fields_retain_diagnostics(self):
        self.pool=[{'batch_id':'b','case_id':'a','token':'broken','stage':'build','error':'missing status'}]
        self.save();code,result=self.run_read_only_status();self.assertEqual(code,0)
        self.assertEqual(result['current_tickets'][0]['error'],'missing status');self.assertTrue(result['warnings'])
        for key in ('case_id','token','stage'):
            with self.subTest(missing_identity=key):
                ticket=dict(self.pool[0]);ticket.pop(key);write_json(self.root/'queue.json',[ticket])
                code,result=self.run_read_only_status();self.assertEqual(code,0)
                self.assertEqual(result['current_tickets'][0]['error'],'missing status')
                self.assertIn('invalid_record_preview',result['current_tickets'][0])
                self.assertTrue(any('queue.json[0]' in warning for warning in result['warnings']))
        ticket=dict(self.pool[0]);ticket.pop('batch_id');write_json(self.root/'queue.json',[ticket])
        code,error=self.run_read_only_status();self.assertEqual(code,2);self.assertIn('queue.json[0]',error)
        write_json(self.root/'queue.json',{})
        code,error=self.run_read_only_status();self.assertEqual(code,2);self.assertIn('queue.json',error)

    def test_other_case_terminal_token_cannot_resolve_current_pending(self):
        pending={'token':'collision','status':'active','reason':'actual unresolved work'}
        self.state['cases']['a']['pending']=[pending]
        self.pool=[{'batch_id':'b','case_id':'z','token':'collision','stage':'build','status':'released'}]
        self.save();code,result=self.run_read_only_status('--case-id','a');self.assertEqual(code,0)
        self.assertEqual(result['cases'][0]['pending'],[pending]);self.assertTrue(result['cases'][0]['warnings'])

    def test_duplicate_queue_token_never_selects_an_arbitrary_terminal_record(self):
        pending={'token':'collision','status':'active','reason':'still unresolved'}
        self.state['cases']['a']['pending']=[pending]
        active={'batch_id':'b','case_id':'a','token':'collision','stage':'build','status':'active'}
        terminal=dict(active,status='released')
        for records in ([active,terminal],[terminal,active]):
            with self.subTest(queue=records):
                self.pool=records;self.save();code,result=self.run_read_only_status();self.assertEqual(code,0)
                self.assertEqual(result['cases'][0]['pending'],[pending])
                self.assertTrue(any('Duplicate recorded queue token' in warning for warning in result['warnings']))
                self.assertTrue(result['cases'][0]['warnings'])

    def test_same_case_stage_or_explicit_identity_conflict_keeps_pending(self):
        self.pool=[{'batch_id':'b','case_id':'a','token':'collision','stage':'review','status':'released'}]
        for extra in ({'stage':'build'},{'case_id':'z'},{'batch_id':'other'}):
            with self.subTest(identity=extra):
                pending={'token':'collision','status':'active','reason':'still unresolved',**extra}
                self.state['cases']['a']['pending']=[pending];self.save()
                code,result=self.run_read_only_status();self.assertEqual(code,0)
                self.assertEqual(result['cases'][0]['pending'],[pending]);self.assertTrue(result['cases'][0]['warnings'])

    def test_valid_matching_terminal_ticket_and_other_batch_token_remain_distinct(self):
        pending={'token':'finished','status':'active','reason':'historical attempt'}
        self.state['cases']['a']['pending']=[pending]
        terminal={'batch_id':'b','case_id':'a','token':'finished','stage':'build','status':'released'}
        self.pool=[terminal];self.save();code,result=self.run_read_only_status();self.assertEqual(code,0)
        self.assertEqual(result['cases'][0]['pending'],[])
        self.pool=[dict(terminal,batch_id='other')];self.save()
        code,result=self.run_read_only_status();self.assertEqual(code,0)
        self.assertEqual(result['cases'][0]['pending'],[pending])

    def test_empty_owner_and_call_without_identity_preserve_schema_error_summary(self):
        write_json(self.target/'owner.json',{})
        self.state['cases']['a']['calls']=[{'message':'actual schema-corrupt call failure','fatal':True}]
        self.save();code,result=self.run_read_only_status();self.assertEqual(code,0)
        self.assertEqual(result['owner']['invalid_record_preview'],'{}');self.assertTrue(result['warnings'])
        row=result['cases'][0];latest=row['latest_call']
        self.assertEqual(latest['message'],'actual schema-corrupt call failure');self.assertTrue(latest['fatal'])
        self.assertIn('actual schema-corrupt call failure',latest['invalid_record_preview'])
        self.assertTrue(row['warnings'])
        self.state['cases']['a']['calls']=[{'unexpected':'x'*5000}];self.save()
        code,result=self.run_read_only_status();self.assertEqual(code,0)
        latest=result['cases'][0]['latest_call'];self.assertTrue(latest['truncated'])
        self.assertEqual(len(latest['invalid_record_preview']),2000)

    def test_recorded_admission_metadata_survives_without_fresh_admission(self):
        admission={'lane':'repair','group':'g','work_kind':'repair','fixed_stage_quotas':False}
        self.pool[0].update(status='active',scheduler_admission=admission,work_kind='repair')
        self.save()
        with patch.object(batch,'mutate',side_effect=AssertionError('No fresh admission')):
            code,result=self.run_read_only_status()
        self.assertEqual(code,0);ticket=result['current_tickets'][0]
        self.assertEqual(ticket['scheduler_admission'],admission);self.assertEqual(ticket['work_kind'],'repair')
        self.assertIn('no fresh acceptance or admission',result['scope'])

    def test_legacy_absent_history_fields_are_not_silently_confirmed_empty(self):
        self.state['cases']['a'].pop('pending');self.state['cases']['a'].pop('calls');self.save()
        code,result=self.run_read_only_status();self.assertEqual(code,0)
        row=result['cases'][0];self.assertEqual(row['pending'],[]);self.assertEqual(row['call_count'],0)
        self.assertTrue(any('legacy absence' in warning for warning in row['warnings']))

    def test_compact_manifest_batch_identity_cannot_hide_or_import_other_batch_tickets(self):
        for batch_id in ('other','',None,123,' '):
            with self.subTest(batch_id=batch_id):
                self.manifest['batch_id']=batch_id;self.save()
                code,error=self.run_read_only_status();self.assertEqual(code,2)
                self.assertIn('manifest batch_id',error);self.assertIn(str(self.target/'manifest.json'),error)
                code,full=self.run_status();self.assertEqual(code,0)
                self.assertEqual(full['current_tickets'],[self.pool[0]])
        self.manifest.pop('batch_id');self.save()
        code,error=self.run_read_only_status();self.assertEqual(code,2);self.assertIn('manifest batch_id',error)

    def test_compact_manifest_case_identity_must_be_a_nonempty_string(self):
        for case_id in ('',' ',None,123):
            with self.subTest(case_id=case_id):
                self.manifest['cases'][0]['case_id']=case_id;self.save()
                code,error=self.run_read_only_status();self.assertEqual(code,2)
                self.assertIn('manifest case ID',error)
                code,full=self.run_status();self.assertEqual(code,0)
                self.assertEqual(full['current_tickets'],[self.pool[0]])

    def test_present_null_owner_is_diagnostic_while_missing_owner_remains_absent(self):
        write_json(self.target/'owner.json',None)
        code,result=self.run_read_only_status();self.assertEqual(code,0)
        self.assertEqual(result['owner']['invalid_record_type'],'NoneType')
        self.assertEqual(result['owner']['invalid_record_preview'],'null')
        self.assertTrue(any('Recorded owner' in warning for warning in result['warnings']))
        self.target.joinpath('owner.json').unlink()
        code,result=self.run_read_only_status();self.assertEqual(code,0);self.assertIsNone(result['owner'])
        self.assertFalse(any('Recorded owner' in warning for warning in result.get('warnings',[])))


if __name__=='__main__':unittest.main()
