"""Finalization and saved final bindings cannot bypass current review lifecycle."""
import json
from pathlib import Path
import unittest
from unittest.mock import patch
import test_contracts as fixtures
from common import digest, read_json
from contracts import final_review_binding
from proflow import finalize


class FinalReviewFreshnessTests(unittest.TestCase):
    def setUp(self):
        self.fixture = fixtures.ContractTests(); self.fixture.setUp()
        self.addCleanup(self.fixture.tearDown)
        self.saved = self.fixture.verify_models()

    def saved_binding(self):
        f = self.fixture
        with patch('contracts.SESSION_ROOT', f.sessions):
            return final_review_binding(f.work, f.proof, f.files, f.charts, f.proof_path, self.saved)

    def append(self, path, *events):
        with path.open('a', encoding='utf-8') as stream:
            stream.write(''.join(json.dumps(event) + '\n' for event in events))

    def both_reject(self, expression):
        for validate in (self.fixture.verify_models, self.saved_binding):
            with self.subTest(entry=validate.__name__), self.assertRaisesRegex(ValueError, expression): validate()

    def test_legacy_final_without_lifecycle_remains_valid_and_saved_binding_reads_each_session_once(self):
        f = self.fixture; counts = {f.parent_log: 0, f.review_log: 0}; original = Path.open
        def tracked(path, *args, **kwargs):
            if path in counts: counts[path] += 1
            return original(path, *args, **kwargs)
        with patch.object(Path, 'open', tracked): self.assertEqual(self.saved_binding(), self.saved)
        self.assertEqual(counts, {f.parent_log: 1, f.review_log: 1})

    def test_child_task_restart_rejects_old_pass_at_both_final_gates(self):
        f = self.fixture; proof = f.proof_path.read_bytes()
        self.append(f.review_log, {'type': 'event_msg', 'payload': {'type': 'task_started'}})
        self.both_reject('live/resumed after')
        self.assertEqual(f.proof_path.read_bytes(), proof)

    def test_child_new_turn_context_rejects_old_pass_even_with_same_model(self):
        self.append(self.fixture.review_log, {'type': 'turn_context', 'payload': {'model': 'gpt-6.1-sol', 'effort': 'ultra'}})
        self.both_reject('live/resumed after')

    def test_restarted_then_completed_child_still_requires_a_new_final(self):
        self.append(self.fixture.review_log, {'type': 'event_msg', 'payload': {'type': 'task_started'}},
                    {'type': 'event_msg', 'payload': {'type': 'task_complete'}})
        self.both_reject('live/resumed after')

    def test_pending_parent_followup_and_message_cannot_reuse_old_pass(self):
        f = self.fixture; original = f.parent_log.read_bytes()
        for tool in ('followup_task', 'send_message'):
            for target in ('/root/review', 'review'):
                with self.subTest(tool=tool, target=target):
                    f.parent_log.write_bytes(original)
                    self.append(f.parent_log, {'type': 'response_item', 'timestamp': '2026-10-15T10:00:03Z',
                        'payload': {'type': 'function_call', 'name': 'collaboration.' + tool, 'call_id': tool,
                                    'arguments': json.dumps({'target': target, 'message': 'continue verification'})}})
                    self.both_reject('later continuation')

    def test_legitimate_followup_with_fresh_attested_final_and_terminal_completion_is_valid(self):
        f = self.fixture; proof = f.proof_path.read_bytes()
        final = json.loads(f.review_log.read_text(encoding='utf-8').splitlines()[-1]); final['timestamp'] = '2026-10-15T10:00:03Z'
        self.append(f.parent_log, {'type': 'response_item', 'timestamp': '2026-10-15T10:00:00Z',
            'payload': {'type': 'function_call', 'name': 'collaboration.followup_task', 'call_id': 'fresh',
                        'arguments': json.dumps({'target': '/root/review', 'message': 'finish actual verification'})}})
        self.append(f.review_log, {'type': 'event_msg', 'payload': {'type': 'task_started'}},
                    {'type': 'turn_context', 'payload': {'model': 'gpt-6.1-sol', 'effort': 'ultra'}}, final,
                    {'type': 'event_msg', 'payload': {'type': 'task_complete'}})
        self.assertEqual(f.verify_models(), self.saved); self.assertEqual(self.saved_binding(), self.saved)
        self.assertEqual(f.proof_path.read_bytes(), proof)

    def test_direct_finalize_rejects_old_pass_without_creating_a_receipt(self):
        f = self.fixture
        f.proof.update(checks=f.runtime_records(f.work, f.out), reviewed_files=f.files, visual_notes=['fixture'],
                       limitations=['fixture only'], source_zip_sha256=digest(f.system / '项目源码.zip'))
        f.make_media_fixture(f.work, f.out)
        f.proof['video_timeline_sha256'] = read_json(f.work / '.product-v2/controlled-video.json')['sha256']; f.save_proof()
        self.append(f.review_log, {'type': 'event_msg', 'payload': {'type': 'task_started'}})
        proof = f.proof_path.read_bytes()
        with patch('proflow.cleanup_ready'), patch('contracts.SESSION_ROOT', f.sessions):
            with self.assertRaisesRegex(ValueError, 'live/resumed after'): finalize(f.work, f.out, f.proof_path)
        self.assertFalse((f.work / '.product-v2/final-receipt.json').exists()); self.assertEqual(f.proof_path.read_bytes(), proof)


if __name__ == '__main__': unittest.main()
