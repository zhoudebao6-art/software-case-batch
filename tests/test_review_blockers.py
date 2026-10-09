"""Environment rejection is diagnostic, never acceptance or paid content repair."""
import copy
import unittest
from pathlib import Path
from unittest.mock import patch

import test_caseflow as fixtures
from test_caseflow import flow, FakeExecutor
from test_speed import compact_response


class ReviewBlockerTests(unittest.TestCase):
    setUp = fixtures.CaseflowTests.setUp
    tearDown = fixtures.CaseflowTests.tearDown
    make_source = fixtures.CaseflowTests.make_source
    run_fake = fixtures.CaseflowTests.run_fake

    def blocked_review(self, complete=False):
        self.make_source()
        flow.plan(self.cfg, self.source)
        self.cfg['runner'].update(review_mode='combined_final')
        self.fake = FakeExecutor()
        self.saved = []

        def execute(cfg, case, stage, context, output=None):
            rec = self.fake(cfg, case, stage, context, output)
            if stage == 'build':
                flow.atomic_json(case / '.caseflow-environment.json', {
                    'status': 'ready', 'requires_environment_repair': False,
                    'reason': 'Old successful probe'})
            if stage == 'review_final':
                raw = compact_response(flow.read_json(output), context['review_request'])
                raw.update(verdict='blocked', issues=[{
                    'severity': 'blocker', 'artifact': 'read-only runtime',
                    'evidence': 'helper_unknown_error: setup refresh had errors',
                    'fix': 'Owner must verify the restricted runtime before resuming'}])
                if not complete:
                    raw.update(reviewed_evidence=[], chart_reviews=[],
                               limitations=['No text evidence could be read'])
                flow.atomic_json(output, raw)
                self.saved.append((output, copy.deepcopy(raw)))
            return rec
        self.execute = execute
        return self.run_fake(execute)['cases'][0]

    def test_partial_blocked_preserves_reason_and_never_fills_coverage(self):
        state = self.blocked_review()
        self.assertEqual(state['stage'], 'blocked')
        self.assertIn('setup refresh had errors', state['reason'])
        self.assertNotIn('Review omits', state['reason'])
        record = state['final_review']
        self.assertTrue(record['diagnostic_only'])
        self.assertTrue(record['missing_evidence'])
        self.assertTrue(record['missing_charts'])
        bound = flow.read_json(Path(record['path']))
        self.assertEqual(bound['reviewed_files'], [])
        self.assertEqual(bound['chart_reviews'], [])
        self.assertEqual(flow.read_json(self.saved[0][0]), self.saved[0][1])
        self.assertFalse(any(s.startswith('repair') for _, s in self.fake.stages))
        # A diagnostic cannot be relabeled as a pass.
        bound['verdict'] = 'pass'
        bound['issues'] = []
        with self.assertRaises(flow.Blocked):
            flow.verify_review(bound, record['snapshot_files'], set(record['snapshot_files']))

    def test_complete_blocked_also_stops_without_content_repair(self):
        state = self.blocked_review(complete=True)
        self.assertEqual(state['stage'], 'blocked')
        self.assertEqual(state['review_calls_started'], 1)
        self.assertFalse(any(s.startswith('repair') for _, s in self.fake.stages))

    def test_same_blocker_and_old_ready_note_do_not_trigger_paid_retry(self):
        first = self.blocked_review()
        calls = len(self.fake.stages)
        second = self.run_fake(self.execute)['cases'][0]
        self.assertEqual(len(self.fake.stages), calls)
        self.assertEqual(second['calls'], first['calls'])
        self.assertIn('resume_deferred', second)
        flow.atomic_json(Path(first['workspace']) / '.caseflow-environment.json', {
            'status': 'ready', 'requires_environment_repair': False,
            'reason': 'Fixture owner verified recovery after the rejected review'})
        resumed = self.run_fake(self.fake)['cases'][0]
        self.assertEqual(resumed['stage'], 'delivered', resumed.get('reason'))
        self.assertEqual([s for _, s in self.fake.stages].count('build'), 1)
        self.assertFalse(any(s.startswith('repair') for _, s in self.fake.stages))

    def test_blocked_does_not_relax_identity_ids_or_hashes(self):
        files = {'one.txt': 'a' * 64, 'two.txt': 'b' * 64}
        req = flow.review_request(files, set(files))
        raw = dict(protocol='evidence-ids-v1', review_id=req['review_id'], verdict='blocked',
                   issues=[dict(severity='blocker', artifact='runtime', evidence='Failed command', fix='Repair runtime')],
                   reviewed_evidence=['E001'], chart_reviews=[], coverage='One read', limitations=['One unread'])
        bound = flow.bind_review_response(raw, req, files, set(files), {'charts': []})
        for key, value in [('review_id', 'old'), ('reviewed_evidence', ['E999']),
                           ('reviewed_evidence', ['E001', 'E001']), ('issues', [])]:
            with self.subTest(key=key), self.assertRaises(flow.Blocked):
                flow.bind_review_response({**raw, key: value}, req, files, set(files), {'charts': []})
        bound['reviewed_files'][0]['sha256'] = 'c' * 64
        with self.assertRaisesRegex(flow.Blocked, 'stale/wrong hash'):
            flow.verify_review(bound, files, set(files), manifest={'charts': []})

    def test_controlled_environment_errors_do_not_enter_paid_repair(self):
        self.make_source()
        flow.plan(self.cfg, self.source)
        self.cfg['runner'].update(review_mode='combined_final')
        fake = FakeExecutor()
        with patch.object(flow, 'validate_build_contract', side_effect=flow.Blocked('runtime root-only update: os error 32')):
            state = self.run_fake(fake)['cases'][0]
        self.assertEqual(state['stage'], 'blocked')
        self.assertEqual(state['worker_blocker']['category'], 'file_in_use')
        self.assertEqual([s for _, s in fake.stages], ['build'])
        self.run_fake(fake)
        self.assertEqual([s for _, s in fake.stages], ['build'])


if __name__ == '__main__':
    unittest.main()
