"""Synthetic gate fixtures only; no live dispatch, decryption or reviewer signatures."""
import base64
import copy
from datetime import datetime,timezone
import hashlib
import json
from pathlib import Path
import sys
import unittest

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
from common import digest,read_json,write_json
from contracts import review_dispatch_binding
import test_expedited_route as admitted_fixtures


def timestamp(ns):
    seconds,microseconds=divmod(ns//1000,1000000)
    return datetime.fromtimestamp(seconds,timezone.utc).replace(microsecond=microseconds).isoformat().replace('+00:00','Z')


class EncryptedDispatchTests(unittest.TestCase):
    def setUp(self):
        self.admitted=admitted_fixtures.AdmittedModelContractTests();self.admitted.setUp()
        self.addCleanup(self.admitted.tearDown)
        self.fixture=self.admitted.fixture
        self.active=self.admitted.admit();self.permit_result=self.admitted.bind(self.active)
        self.reference=self.permit_result['review_dispatch_permit']
        self.permit=read_json(self.reference['path'])
        self.called_ns=(self.permit['issued_ns']//1000000000+2)*1000000000
        self.returned_ns=self.called_ns+100000000
        self.call=next(e for e in self.fixture.events if e['payload'].get('call_id')=='review' and e['payload']['type']=='function_call')
        self.result=next(e for e in self.fixture.events if e['payload'].get('call_id')=='review' and e['payload']['type']=='function_call_output')
        # Envelope-shaped opaque bytes are enough for these parser fixtures.
        # No keys exist and no cryptographic authentication is claimed.
        self.cipher=base64.urlsafe_b64encode(b'\x80'+b'\0'*8+b'i'*16+b'c'*16+b'h'*32).decode('ascii')
        arguments=json.loads(self.call['payload']['arguments']);arguments['message']=self.cipher
        self.call['payload']['arguments']=json.dumps(arguments)
        self.call['timestamp']=timestamp(self.called_ns);self.result['timestamp']=timestamp(self.returned_ns)
        self.fixture.save_dispatch()
        self.binding=self.expected_binding()
        self.fixture.proof['review_dispatch_binding']=copy.deepcopy(self.binding)
        self.review_events=[
            {'type':'session_meta','payload':{'id':'child-fixture','timestamp':timestamp(self.called_ns+10000000),
                'source':{'subagent':{'thread_spawn':{'agent_path':'/root/review','parent_thread_id':'parent-fixture'}}}}},
            {'type':'turn_context','payload':{'model':'gpt-6.1-sol','effort':'ultra'}},
            {'timestamp':timestamp(self.called_ns+1000000000),'type':'response_item',
             'payload':{'type':'message','role':'assistant','phase':'final_answer','content':[]}},
        ]
        self.save_all()

    def expected_binding(self):
        admission=read_json(self.active['review_admission']['path'])
        return {'contract':'desktop-encrypted-spawn-v1','token':admission['token'],
            'dispatch_nonce':self.permit['dispatch_nonce'],'run_id':admission['run_id'],'workspace':admission['workspace'],
            'parent_session_id':'parent-fixture','call_id':'review',
            'dispatch_message_sha256':hashlib.sha256(self.cipher.encode('utf-8')).hexdigest(),
            'dispatch_event_sha256':hashlib.sha256(json.dumps([self.call,self.result],sort_keys=True,ensure_ascii=False).encode()).hexdigest()}

    def final_text(self,binding=None):
        return json.dumps({'reviewer_agent_id':'/root/review','review_evidence_sha256':digest(self.fixture.proof_path),
                           'review_dispatch_binding':self.binding if binding is None else binding})

    def save_review(self):
        self.fixture.review_log.write_text(''.join(json.dumps(e)+'\n' for e in self.review_events),encoding='utf-8')

    def save_all(self):
        self.fixture.save_dispatch();write_json(self.fixture.proof_path,self.fixture.proof)
        self.review_events[-1]['payload']['content']=[{'type':'output_text','text':self.final_text()}]
        self.save_review()

    def verify(self):return self.fixture.verify_models()

    def neutral_binding(self):
        return review_dispatch_binding(self.fixture.work,self.active['review_admission'],self.reference,
                                       self.fixture.parent_log,'review')

    def test_supported_cipher_true_child_and_exact_final_pass(self):
        self.assertEqual(self.verify()['review_dispatch_binding'],self.binding)
        self.assertEqual(self.neutral_binding(),self.binding)

    def test_neutral_helper_reads_only_and_cannot_emit_or_amend_a_final(self):
        paths=[self.fixture.parent_log,self.fixture.review_log,self.fixture.proof_path,Path(self.reference['path']),
               self.fixture.work/'.product-v2/model-dispatch.json']
        before={p:p.read_bytes() for p in paths}
        self.assertEqual(self.neutral_binding(),self.binding)
        self.assertEqual({p:p.read_bytes() for p in paths},before)

    def test_no_parent_plaintext_or_decrypted_child_text_is_required(self):
        self.review_events.insert(2,{'type':'response_item','payload':{'type':'message','role':'user',
            'content':[{'type':'encrypted_content','encrypted_content':'opaque child NEW_TASK'}]}})
        self.save_review();self.verify()
        arguments=json.loads(self.call['payload']['arguments'])
        self.assertNotIn(self.permit['dispatch_nonce'],arguments['message'])

    def test_cipher_shape_does_not_bypass_plaintext_scope(self):
        for message in ('gAAAA-not-a-valid-envelope','opaque-encrypted-message',self.active['token']+' '+str(self.fixture.work)):
            with self.subTest(message=message):
                arguments=json.loads(self.call['payload']['arguments']);arguments['message']=message
                self.call['payload']['arguments']=json.dumps(arguments);self.fixture.save_dispatch()
                with self.assertRaisesRegex(ValueError,'scope checks|verified permit nonce'):self.verify()

    def test_plaintext_current_scope_remains_supported_without_new_binding(self):
        arguments=json.loads(self.call['payload']['arguments'])
        arguments['message']=' '.join((self.active['token'],self.permit['dispatch_nonce'],self.fixture.run['run_id'],str(self.fixture.work)))
        self.call['payload']['arguments']=json.dumps(arguments)
        self.fixture.proof.pop('review_dispatch_binding');self.fixture.save_dispatch();self.fixture.save_proof()
        self.assertNotIn('review_dispatch_binding',self.verify())

    def test_wrong_or_missing_proof_binding_fields_are_rejected(self):
        for key in self.binding:
            for missing in (False,True):
                with self.subTest(key=key,missing=missing):
                    changed=copy.deepcopy(self.binding)
                    if missing:changed.pop(key)
                    else:changed[key]='different'
                    self.fixture.proof['review_dispatch_binding']=changed;self.save_all()
                    with self.assertRaisesRegex(ValueError,'Encrypted review proof'):self.verify()

    def test_wrong_or_missing_final_binding_fields_are_rejected(self):
        for key in self.binding:
            for missing in (False,True):
                with self.subTest(key=key,missing=missing):
                    changed=copy.deepcopy(self.binding)
                    if missing:changed.pop(key)
                    else:changed[key]='different'
                    self.review_events[-1]['payload']['content'][0]['text']=self.final_text(changed);self.save_review()
                    with self.assertRaisesRegex(ValueError,'final must attest'):self.verify()

    def test_old_exact_proof_hash_without_cipher_binding_cannot_attest(self):
        self.review_events[-1]['payload']['content'][0]['text']=json.dumps({'reviewer_agent_id':'/root/review',
                                                                         'review_evidence_sha256':digest(self.fixture.proof_path)})
        self.save_review()
        with self.assertRaisesRegex(ValueError,'final must attest'):self.verify()

    def test_stale_proof_hash_rejected(self):
        self.fixture.proof['limitations']='changed after final';write_json(self.fixture.proof_path,self.fixture.proof)
        with self.assertRaisesRegex(ValueError,'final must attest'):self.verify()

    def test_loaded_proof_must_equal_the_attested_bytes(self):
        changed=copy.deepcopy(self.fixture.proof);changed['decision']='fail';write_json(self.fixture.proof_path,changed)
        self.review_events[-1]['payload']['content'][0]['text']=self.final_text();self.save_review()
        with self.assertRaisesRegex(ValueError,'Encrypted review proof'):self.verify()

    def test_changed_immutable_permit_rejected(self):
        changed=copy.deepcopy(self.permit);changed['dispatch_nonce']='f'*32;write_json(self.reference['path'],changed)
        with self.assertRaisesRegex(ValueError,'dispatch permit changed'):self.verify()

    def test_proof_cannot_bind_another_permit(self):
        self.fixture.proof['review_dispatch_permit']={'path':'another','sha256':'another'};self.save_all()
        with self.assertRaisesRegex(ValueError,'verification permit'):self.verify()

    def test_admission_and_permit_must_precede_call(self):
        for called_ns in (self.permit['issued_ns']-1000000000,0):
            with self.subTest(called_ns=called_ns):
                self.call['timestamp']=timestamp(called_ns);self.fixture.save_dispatch()
                with self.assertRaisesRegex(ValueError,'must precede'):self.verify()

    def test_result_cannot_precede_call(self):
        self.result['timestamp']=timestamp(self.called_ns-1000000);self.fixture.save_dispatch()
        with self.assertRaisesRegex(ValueError,'must precede'):self.verify()

    def test_missing_naive_or_malformed_dispatch_timestamps_fail_closed(self):
        for value in (None,'2026-10-13T01:02:03','invalid'):
            with self.subTest(value=value):
                self.call['timestamp']=value;self.fixture.save_dispatch()
                with self.assertRaisesRegex(ValueError,'timezone-aware'):self.verify()

    def test_unauthenticated_cipher_timestamp_never_substitutes_for_log_time(self):
        self.call.pop('timestamp');self.fixture.save_dispatch()
        with self.assertRaisesRegex(ValueError,'timezone-aware'):self.neutral_binding()

    def test_distinct_child_identity_correct_parent_and_agent_are_required(self):
        original=copy.deepcopy(self.review_events[0])
        mutations=[('id','parent-fixture'),('id',None),('parent_thread_id','another-parent'),('agent_path','/root/build')]
        for key,value in mutations:
            with self.subTest(key=key,value=value):
                self.review_events[0]=copy.deepcopy(original)
                target=self.review_events[0]['payload']
                if key!='id':target=target['source']['subagent']['thread_spawn']
                target[key]=value;self.save_review()
                with self.assertRaisesRegex(ValueError,'final must attest'):self.verify()

    def test_child_creation_must_belong_to_same_actual_call_window(self):
        for created_ns in (self.called_ns-1000000,self.returned_ns+1000000):
            with self.subTest(created_ns=created_ns):
                self.review_events[0]['payload']['timestamp']=timestamp(created_ns);self.save_review()
                with self.assertRaisesRegex(ValueError,'final must attest'):self.verify()

    def test_replayed_call_with_updated_proof_cannot_reuse_old_child_session(self):
        self.call['timestamp']=timestamp(self.called_ns+3000000000)
        self.result['timestamp']=timestamp(self.returned_ns+3000000000);self.fixture.save_dispatch()
        self.binding=self.neutral_binding();self.fixture.proof['review_dispatch_binding']=self.binding
        self.save_all()
        with self.assertRaisesRegex(ValueError,'final must attest'):self.verify()

    def test_duplicate_call_or_output_is_rejected(self):
        for event in (self.call,self.result):
            with self.subTest(type=event['payload']['type']):
                self.fixture.events.append(copy.deepcopy(event));self.fixture.save_dispatch()
                with self.assertRaisesRegex(ValueError,'One actual dispatch'):self.verify()
                self.fixture.events.pop()

    def test_multiple_parent_or_child_session_metadata_are_rejected(self):
        self.fixture.save_dispatch()
        with self.fixture.parent_log.open('a',encoding='utf-8') as stream:
            stream.write(json.dumps({'type':'session_meta','payload':{'id':'another-parent'}})+'\n')
        with self.assertRaisesRegex(ValueError,'parent session identity'):self.verify()
        self.fixture.save_dispatch();self.review_events.insert(1,copy.deepcopy(self.review_events[0]));self.save_review()
        with self.assertRaisesRegex(ValueError,'final must attest'):self.verify()

    def test_wrong_model_effort_or_fork_cannot_be_hidden_by_signed_binding(self):
        original=json.loads(self.call['payload']['arguments'])
        for key,value in (('model','gpt-6-astra'),('reasoning_effort','high'),('fork_turns','all')):
            with self.subTest(key=key):
                changed={**original,key:value};self.call['payload']['arguments']=json.dumps(changed)
                self.binding=self.expected_binding();self.fixture.proof['review_dispatch_binding']=copy.deepcopy(self.binding);self.save_all()
                with self.assertRaisesRegex(ValueError,'review dispatch must'):self.verify()
                with self.assertRaisesRegex(ValueError,'admitted model/effort'):self.neutral_binding()

    def test_wrong_child_turn_model_or_effort_rejected(self):
        for model,effort in (('gpt-6-astra','low'),('gpt-6.1-sol','high')):
            with self.subTest(model=model,effort=effort):
                self.review_events[1]['payload']={'model':model,'effort':effort};self.save_review()
                with self.assertRaisesRegex(ValueError,'final must attest'):self.verify()

    def test_wrong_reviewer_cannot_sign_final(self):
        final=json.loads(self.final_text());final['reviewer_agent_id']='/root/build'
        self.review_events[-1]['payload']['content'][0]['text']=json.dumps(final);self.save_review()
        with self.assertRaisesRegex(ValueError,'final must attest'):self.verify()

    def test_parent_summary_cannot_replace_true_child_final(self):
        self.fixture.dispatch['stages']['review']['review_session_log']=str(self.fixture.parent_log);self.fixture.save_dispatch()
        with self.fixture.parent_log.open('a',encoding='utf-8') as stream:stream.write(json.dumps(self.review_events[-1])+'\n')
        with self.assertRaisesRegex(ValueError,'final must attest'):self.verify()

    def test_intermediate_or_user_message_cannot_sign(self):
        for role,phase in (('assistant','commentary'),('user','final_answer')):
            with self.subTest(role=role,phase=phase):
                self.review_events[-1]['payload']['role']=role;self.review_events[-1]['payload']['phase']=phase;self.save_review()
                with self.assertRaisesRegex(ValueError,'final must attest'):self.verify()

    def test_latest_final_replaces_earlier_valid_final_even_when_opaque(self):
        self.review_events.append({'timestamp':timestamp(self.called_ns+2000000000),'type':'response_item',
            'payload':{'type':'message','role':'assistant','phase':'final_answer',
                       'content':[{'type':'encrypted_content','encrypted_content':'opaque final'}]}})
        self.save_review()
        with self.assertRaisesRegex(ValueError,'final must attest'):self.verify()

    def test_final_before_recorded_result_cannot_attest(self):
        self.review_events[-1]['timestamp']=timestamp(self.called_ns);self.save_review()
        with self.assertRaisesRegex(ValueError,'final must attest'):self.verify()

    def test_whole_final_json_only_and_exact_memory_suffix_supported(self):
        final=self.final_text()
        self.review_events[-1]['payload']['content']=[{'type':'output_text','text':final},
                                                      {'type':'output_text','text':' conflicting result'}]
        self.save_review()
        with self.assertRaisesRegex(ValueError,'final must attest'):self.verify()
        self.review_events[-1]['payload']['content']=[{'type':'output_text','text':final+'\n<oai-mem-citation>\n<citation_entries>MEMORY.md:1-2|note=[fixture]</citation_entries>\n<rollout_ids></rollout_ids>\n</oai-mem-citation>'}]
        self.save_review();self.verify()

    def test_same_reviewer_and_builder_are_rejected(self):
        self.result['payload']['output']=json.dumps({'task_name':'/root/build'})
        self.fixture.dispatch['stages']['review']['agent_id']='/root/build'
        self.binding=self.expected_binding();self.fixture.proof['review_dispatch_binding']=self.binding;self.save_all()
        with self.assertRaisesRegex(ValueError,'Distinct actual stage'):self.verify()

    def test_successful_matching_result_required(self):
        self.result['payload']['output']=json.dumps({'task_name':'/root/review','error':'dispatch failed'})
        self.binding=self.expected_binding();self.fixture.proof['review_dispatch_binding']=self.binding;self.save_all()
        with self.assertRaisesRegex(ValueError,'Distinct actual stage'):self.verify()
        with self.assertRaisesRegex(ValueError,'successful dispatch result'):self.neutral_binding()

    def test_current_artifacts_and_chart_snapshot_still_required(self):
        for key in ('artifact_hashes','chart_snapshot'):
            with self.subTest(key=key):
                original=self.fixture.dispatch['stages']['review'][key]
                self.fixture.dispatch['stages']['review'][key]={};self.fixture.save_dispatch()
                with self.assertRaisesRegex(ValueError,'current artifacts'):self.verify()
                self.fixture.dispatch['stages']['review'][key]=original


if __name__=='__main__':unittest.main()
