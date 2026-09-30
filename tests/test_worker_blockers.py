"""Isolated regressions for paid retries and masked worker blockers."""
import unittest
from pathlib import Path
import test_caseflow as fixtures
from test_caseflow import flow, FakeExecutor


class WorkerBlockerTests(unittest.TestCase):
    setUp = fixtures.CaseflowTests.setUp
    tearDown = fixtures.CaseflowTests.tearDown
    make_source = fixtures.CaseflowTests.make_source
    run_fake = fixtures.CaseflowTests.run_fake

    def blocked_video(self, *, fallback=False):
        self.make_source()
        self.manifest = flow.plan(self.cfg, self.source)
        self.cfg['runner']['review_mode'] = 'combined_final'
        self.fake = FakeExecutor(revise_visual=True)

        def execute(cfg, case, stage, context, output=None):
            if stage == 'video' and self.fake.video_calls:
                self.fake.stages.append((case.name, stage))
                note = {'status': 'blocked', 'requires_user_input': True,
                        'reason': 'Current service startup rejected: blocked by policy; old service retained.'}
                rec = {'stage': stage, 'model': 'gpt-6-sol', 'reasoning_effort': 'high',
                       'sandbox': 'workspace-write', 'thread_id': 'fixture-blocked-video', 'exit_code': 0}
                if fallback:
                    note['requires_environment_repair'] = True
                    rec['final_message'] = 'CASEFLOW_ENVIRONMENT_BLOCKER:' + fixtures.json.dumps(note)
                else:
                    flow.atomic_json(case / 'evidence/repair-status.json', note)
                return rec
            return self.fake(cfg, case, stage, context, output)
        self.execute = execute
        return self.run_fake(execute)['cases'][0]

    def test_video_retains_specific_blocker_before_generic_missing_video(self):
        state = self.blocked_video()
        self.assertEqual(state['stage'], 'blocked')
        self.assertIn('blocked by policy', state['reason'])
        self.assertNotIn('did not produce', state['reason'])
        self.assertEqual(state['failed_stage'], 'video')
        self.assertTrue(state['recording_pending'])
        self.assertEqual(state['review_calls_started'], 1)

    def test_unchanged_external_note_never_dispatches_another_paid_worker(self):
        first = self.blocked_video()
        count = len(self.fake.stages)
        folder = flow.batch_folder(self.cfg, self.manifest)
        flow.control_batch(self.cfg, self.manifest['batch_id'], 'resume-case', case_id=first['case_id'])
        second = self.run_fake(self.execute)['cases'][0]
        self.assertEqual(len(self.fake.stages), count)
        self.assertEqual(second['calls'], first['calls'])
        self.assertEqual(second['repairs_final'], first['repairs_final'])
        self.assertEqual(second['stage'], 'blocked')

    def test_current_ready_note_allows_continuation_without_rebuilding(self):
        state = self.blocked_video()
        note_path = Path(state['workspace']) / 'evidence/repair-status.json'
        flow.atomic_json(note_path, {'status': 'ready_for_review', 'requires_user_input': False,
            'reason': 'Fixture recovery verified; prior blocked by policy is retained in history.'})
        resumed = self.run_fake(self.fake)['cases'][0]
        self.assertEqual(resumed['stage'], 'delivered', resumed.get('reason'))
        self.assertEqual([s for _, s in self.fake.stages].count('build'), 1)
        self.assertEqual(resumed['review_calls_started'], 2)

    def test_final_response_blocker_is_not_hidden_by_video_hash_check(self):
        state = self.blocked_video(fallback=True)
        self.assertIn('blocked by policy', state['reason'])
        self.assertEqual(state['failed_stage'], 'video')
        self.assertTrue(state['recording_pending'])

    def test_old_ready_file_cannot_clear_final_response_blocker(self):
        state = self.blocked_video(fallback=True)
        count = len(self.fake.stages)
        resumed = self.run_fake(self.execute)['cases'][0]
        self.assertEqual(len(self.fake.stages), count)
        self.assertEqual(resumed['stage'], 'blocked')
        flow.atomic_json(Path(state['workspace']) / '.caseflow-environment.json', {
            'status': 'ready', 'requires_environment_repair': False,
            'reason': 'Fixture owner verified recovery after the failure'})
        resumed = self.run_fake(self.fake)['cases'][0]
        self.assertEqual(resumed['stage'], 'delivered', resumed.get('reason'))

    def test_diagnostic_view_never_launches_or_mutates_cases(self):
        state = self.blocked_video()
        folder = flow.batch_folder(self.cfg, self.manifest)
        state_file = flow.state_at(folder, state['case_id'])
        before = state_file.read_bytes()
        report = flow.diagnose_batch(self.cfg, self.manifest['batch_id'])
        self.assertEqual(report['counts']['blocked'], 1)
        self.assertEqual(report['cases'][0]['current_blocker']['category'], 'tool_policy')
        self.assertEqual(report['pipeline_profile'], 'legacy')
        self.assertEqual(report['calls'], len(state['calls']))
        self.assertEqual(state_file.read_bytes(), before)

    def test_blocked_case_does_not_prevent_an_independent_case_finishing(self):
        self.make_source('blocked.docx')
        self.make_source('healthy.docx')
        flow.plan(self.cfg, self.source)
        fake = FakeExecutor()
        def execute(cfg, case, stage, context, output=None):
            rec = fake(cfg, case, stage, context, output)
            if stage == 'build' and context['case_name'] == 'blocked':
                flow.atomic_json(case / 'evidence/repair-status.json', {
                    'status': 'blocked', 'requires_user_input': True,
                    'reason': 'Required service start rejected: blocked by policy'})
            return rec
        states = {row['case_name']: row for row in self.run_fake(execute)['cases']}
        self.assertEqual(states['blocked']['stage'], 'blocked')
        self.assertEqual(states['healthy']['stage'], 'delivered')
        blocked_workspace = Path(states['blocked']['workspace']).name
        self.assertEqual([s for name, s in fake.stages if name == blocked_workspace], ['build'])


if __name__ == '__main__':
    unittest.main()
