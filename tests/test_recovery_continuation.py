import json
import tempfile
import unittest
from pathlib import Path

import test_caseflow as fixtures
from test_caseflow import flow, FakeExecutor


class RuntimeStreamSnapshotTests(unittest.TestCase):
    def test_registered_live_stream_growth_does_not_invalidate_artifact_snapshot(self):
        with tempfile.TemporaryDirectory() as temp:
            case = Path(temp)
            (case / 'evidence').mkdir()
            path = case / 'evidence/service-20260929-091224-stdout.log'
            path.write_text('first request\n')
            flow.atomic_json(case / 'evidence/runtime-streams.json', {
                'purpose': 'live_service_output', 'paths': [path.relative_to(case).as_posix()]})
            before = flow.snapshot(case, video=True)
            path.write_text('first request\nsecond request\n')
            after = flow.snapshot(case, video=True)
            self.assertEqual(before, after)
            self.assertNotIn('evidence/service-20260929-091224-stdout.log', after)

    def test_declared_artifact_cannot_be_excluded_as_runtime_output(self):
        with tempfile.TemporaryDirectory() as temp:
            case = Path(temp)
            (case / 'evidence').mkdir()
            path = 'evidence/service-20260929-091224-stdout.log'
            (case / path).write_text('{"tests": []}')
            flow.atomic_json(case / 'evidence/runtime-streams.json', {
                'purpose': 'live_service_output', 'paths': [path]})
            flow.atomic_json(case / 'evidence/artifact-manifest.json', {'test_report': path})
            with self.assertRaises(flow.Blocked):
                flow.snapshot(case, video=True)


class OwnerRepairContinuationTests(unittest.TestCase):
    setUp = fixtures.CaseflowTests.setUp
    tearDown = fixtures.CaseflowTests.tearDown
    make_source = fixtures.CaseflowTests.make_source
    run_fake = fixtures.CaseflowTests.run_fake

    def test_owner_repair_runs_before_fresh_independent_review(self):
        self.make_source()
        flow.plan(self.cfg, self.source)
        self.cfg['runner']['review_mode'] = 'combined_final'
        fake = FakeExecutor()
        actions = []

        def execute(cfg, case, stage, context, output=None):
            result = fake(cfg, case, stage, context, output)
            if stage == 'build':
                flow.atomic_json(case / 'evidence/repair-status.json', {
                    'status': 'pending_owner_repair', 'requires_user_input': False,
                    'required_action': 'Fix current formula rendering and prewarm chart route.'})
            if stage == 'repair_final':
                actions.append(context.get('required_action'))
                flow.atomic_json(case / 'evidence/repair-status.json', {
                    'status': 'ready_for_review', 'requires_user_input': False})
            return result

        state = self.run_fake(execute)['cases'][0]
        self.assertEqual(state['stage'], 'delivered', state.get('reason'))
        stages = [stage for _, stage in fake.stages]
        self.assertIn('repair_final', stages)
        self.assertLess(stages.index('repair_final'), stages.index('review_final'))
        self.assertTrue(any('Fix current formula rendering' in action for action in actions))


if __name__ == '__main__':
    unittest.main()
