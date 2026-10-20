"""Actual request records cannot silently switch a review's frozen evidence index."""
import base64
import copy
import json
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import test_contracts as fixtures
from common import digest, write_json
from contracts import _model_review, final_review_binding


class ReviewDispatchCoverageBindingTests(unittest.TestCase):
    def setUp(self):
        self.f = fixtures.ContractTests()
        self.f.setUp()
        self.index = self.f.work / '.product-v2/request-index.json'
        write_json(self.index, {'note':'Coverage helper has its own real snapshot regression suite.'})
        self.reference = {'path':str(self.index),'sha256':digest(self.index)}
        self.coverage = {'required':True,'status':'bound-reviewer-coverage',
                         'review_index':self.reference,'review_id':'isolated-request-binding',
                         'required_evidence':['E001']}
        self.f.proof['review_index'] = self.reference
        self.f.dispatch['stages']['review']['review_index'] = self.reference
        self.message('Read the frozen index SHA256 '+self.reference['sha256'])

    def tearDown(self):
        self.f.tearDown()

    def message(self, value):
        for event in self.f.events:
            payload = event['payload']
            if payload.get('type') == 'function_call' and payload.get('call_id') == 'review':
                args = json.loads(payload['arguments']); args['message'] = value
                payload['arguments'] = json.dumps(args)
        self.f.save_dispatch(); self.f.save_proof()

    def verify(self, recorded=None, first=False):
        with patch('evidence_index.validate_review_coverage',return_value=copy.deepcopy(self.coverage)) as coverage, \
             patch('contracts.SESSION_ROOT',self.f.sessions):
            if recorded is not None:
                value = final_review_binding(self.f.work,self.f.proof,self.f.files,self.f.charts,self.f.proof_path,recorded)
            elif first:
                value = _model_review(self.f.work,self.f.proof,self.f.files,self.f.charts,self.f.proof_path,
                                      _first_dispatch=self.f.work/'.product-v2/model-dispatch.json')
            else:
                value = self.f.verify_models()
            return value, coverage.call_args.kwargs['current']

    def test_visible_actual_request_binds_index_hash_and_current_verification(self):
        result, current = self.verify()
        self.assertTrue(current)
        self.assertEqual(result['review_coverage']['request_binding']['kind'],'index-sha256-in-request')

    def test_mutable_stage_and_new_signed_proof_cannot_change_what_parent_requested(self):
        self.coverage['review_index'] = {'path':str(self.index),'sha256':'a'*64}
        self.f.proof['review_index'] = self.coverage['review_index']
        self.f.dispatch['stages']['review']['review_index'] = self.coverage['review_index']
        self.f.save_dispatch(); self.f.save_proof()
        with self.assertRaisesRegex(ValueError,'Actual review dispatch message must bind'):
            self.verify()

    def test_neutral_facts_hash_can_point_to_the_same_immutable_index(self):
        facts = self.f.work / '.product-v2/request-facts.json'
        write_json(facts, {'index':self.reference})
        self.f.dispatch['stages']['review']['review_facts'] = {'path':str(facts),'sha256':digest(facts)}
        self.message('Read these exact neutral facts SHA256 '+digest(facts))
        result, _ = self.verify()
        self.assertEqual(result['review_coverage']['request_binding']['kind'],'facts-sha256-in-request')
        write_json(facts, {'index':{'path':str(self.index),'sha256':'b'*64}})
        self.f.dispatch['stages']['review']['review_facts']['sha256'] = digest(facts)
        self.message('Read these exact neutral facts SHA256 '+digest(facts))
        with self.assertRaisesRegex(ValueError,'Actual review dispatch message must bind'):
            self.verify()

    def test_missing_request_binding_is_rejected(self):
        self.message('Open some files and inspect them.')
        with self.assertRaisesRegex(ValueError,'Actual review dispatch message must bind'):
            self.verify()

    def test_frozen_final_and_first_revise_authenticate_index_without_current_tree_rehash(self):
        original, _ = self.verify()
        _, current = self.verify(recorded=original)
        self.assertFalse(current)
        self.f.proof['decision'] = 'revise'; self.f.save_proof()
        _, current = self.verify(first=True)
        self.assertFalse(current)

    def test_opaque_message_keeps_actual_call_and_independent_final_proof_binding(self):
        token = base64.urlsafe_b64encode(bytes([128])+bytes(72)).decode()
        self.message(token)
        result, _ = self.verify()
        binding = result['review_coverage']['request_binding']
        self.assertEqual(binding['kind'],'encrypted-dispatch-and-independent-final-proof')
        self.assertEqual(binding['dispatch_event_sha256'],result['review']['dispatch_event_sha256'])
        # Opaque request handling cannot replace the independent final attestation.
        self.f.save_proof(attest=False)
        with self.assertRaisesRegex(ValueError,'Independent reviewer final'):
            self.verify()


if __name__ == '__main__':
    unittest.main()
