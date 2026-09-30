"""Observable call budgets, combined evidence coverage, and resume behavior."""
import unittest
from pathlib import Path
from unittest.mock import patch

import test_caseflow as fixtures
from test_caseflow import FakeExecutor, flow, put, PNG


class EconomyTests(unittest.TestCase):
    tearDown = fixtures.CaseflowTests.tearDown
    make_source = fixtures.CaseflowTests.make_source
    run_fake = fixtures.CaseflowTests.run_fake

    def setUp(self):
        fixtures.CaseflowTests.setUp(self)
        self.cfg['runner'].update(review_mode='combined_final', max_review_calls_per_case=2, max_final_review_repairs=1)

    def test_pass_once_covers_visual_word_and_video_and_resume_is_free(self):
        self.make_source()
        manifest = flow.plan(self.cfg, self.source)
        fake = FakeExecutor()
        captured = {}
        def execute(cfg, case, stage, context, output=None):
            if stage == 'review_final':
                captured.update(context)
            return fake(cfg, case, stage, context, output)
        state = self.run_fake(execute)['cases'][0]
        self.assertEqual(state['stage'], 'delivered', state.get('reason'))
        self.assertEqual([s for _, s in fake.stages], ['build', 'video', 'review_final'])
        self.assertEqual(state['review_calls_started'], 1)
        self.assertIn('exports/fig.png', captured['required_review_files'])
        self.assertIn('evidence/docx-render/page-1.png', captured['required_review_files'])
        self.assertIn('recording/evidence/last.png', captured['required_review_files'])
        self.assertEqual(self.run_fake(execute)['cases'][0]['stage'], 'delivered')
        self.assertEqual(len(fake.stages), 3)
        # Recover a crash after atomic publish but before state commit, without new model calls.
        p = flow.state_at(flow.batch_folder(self.cfg, manifest), state['case_id'])
        data = flow.read_json(p)
        data['stage'] = 'final_pass'
        flow.atomic_json(p, data)
        self.assertEqual(self.run_fake(execute)['cases'][0]['stage'], 'delivered')
        self.assertEqual(len(fake.stages), 3)

    def test_revision_is_one_sol_repair_and_one_ultra_recheck(self):
        self.make_source()
        flow.plan(self.cfg, self.source)
        fake = FakeExecutor(revise_visual=True)
        state = self.run_fake(fake)['cases'][0]
        self.assertEqual(state['stage'], 'delivered', state.get('reason'))
        self.assertEqual([s for _, s in fake.stages], ['build', 'video', 'review_final', 'repair_final', 'video', 'review_final'])
        self.assertEqual(state['review_calls_started'], 2)

    def test_noop_video_after_screen_repair_does_not_clear_recording_pending(self):
        self.make_source()
        flow.plan(self.cfg, self.source)
        fake = FakeExecutor(revise_visual=True)

        def execute(cfg, case, stage, context, output=None):
            if stage == 'video' and fake.video_calls:
                fake.stages.append((case.name, stage))
                return {'stage': stage, 'model': 'gpt-6-sol', 'reasoning_effort': 'high',
                        'sandbox': 'workspace-write', 'thread_id': 'fixture-noop-video', 'exit_code': 0}
            return fake(cfg, case, stage, context, output)

        state = self.run_fake(execute)['cases'][0]
        self.assertEqual(state['stage'], 'blocked')
        self.assertTrue(state['recording_pending'])
        self.assertIn('did not produce a new video artifact', state['reason'])
        self.assertEqual(state['review_calls_started'], 1)
        self.assertEqual([s for _, s in fake.stages],
                         ['build', 'video', 'review_final', 'repair_final', 'video'])

    def test_permanent_rejection_has_no_third_review_even_after_resume(self):
        self.make_source()
        flow.plan(self.cfg, self.source)
        fake = FakeExecutor(revise_visual=True, permanent_visual=True)
        state = self.run_fake(fake)['cases'][0]
        self.assertEqual(state['stage'], 'blocked')
        calls = len(fake.stages)
        state = self.run_fake(fake)['cases'][0]
        self.assertEqual(state['stage'], 'blocked')
        self.assertEqual(state['review_calls_started'], 2)
        self.assertEqual(len(fake.stages), calls)
        self.assertFalse((self.source.parent / 'incoming1').exists())

    def test_failed_review_attempts_are_counted_before_dispatch(self):
        self.make_source()
        flow.plan(self.cfg, self.source)
        fake = FakeExecutor()
        calls = []
        def execute(cfg, case, stage, context, output=None):
            if stage == 'review_final':
                calls.append(stage)
                raise OSError('fixture transport failure')
            return fake(cfg, case, stage, context, output)
        for _ in range(3):
            state = self.run_fake(execute)['cases'][0]
            self.assertEqual(state['stage'], 'blocked')
        self.assertEqual(len(calls), 2)
        self.assertEqual(state['review_calls_started'], 2)
        self.assertIn('budget exhausted', state['reason'])

    def test_invalid_review_is_counted_and_never_published(self):
        self.make_source()
        flow.plan(self.cfg, self.source)
        fake = FakeExecutor()
        def execute(cfg, case, stage, context, output=None):
            result = fake(cfg, case, stage, context, output)
            if stage == 'review_final':
                report = flow.read_json(output)
                report['reviewed_files'] = []
                flow.atomic_json(output, report)
            return result
        for _ in range(3):
            state = self.run_fake(execute)['cases'][0]
            self.assertEqual(state['stage'], 'blocked')
        self.assertEqual([s for _, s in fake.stages].count('review_final'), 2)
        self.assertFalse((self.source.parent / 'incoming1').exists())

    def test_revise_with_transcribed_hash_still_reaches_sol_repair(self):
        self.make_source()
        manifest = flow.plan(self.cfg, self.source)
        fake = FakeExecutor(revise_visual=True)
        bad_report = []
        def execute(cfg, case, stage, context, output=None):
            result = fake(cfg, case, stage, context, output)
            if stage == 'review_final' and fake.revise_visual:
                report = flow.read_json(output)
                report['reviewed_files'][0]['sha256'] = 'shortened-digest'
                flow.atomic_json(output, report)
                bad_report.append(output)
            return result
        state = self.run_fake(execute)['cases'][0]
        self.assertEqual(state['stage'], 'delivered', state.get('reason'))
        self.assertEqual([s for _, s in fake.stages], ['build', 'video', 'review_final', 'repair_final', 'video', 'review_final'])
        self.assertEqual(state['review_calls_started'], 2)
        self.assertEqual(flow.read_json(bad_report[0])['reviewed_files'][0]['sha256'], 'shortened-digest')

    def test_pass_with_wrong_hash_is_never_accepted(self):
        self.make_source()
        flow.plan(self.cfg, self.source)
        fake = FakeExecutor()
        def execute(cfg, case, stage, context, output=None):
            result = fake(cfg, case, stage, context, output)
            if stage == 'review_final':
                report = flow.read_json(output)
                report['reviewed_files'][0]['sha256'] = 'shortened-digest'
                flow.atomic_json(output, report)
            return result
        state = self.run_fake(execute)['cases'][0]
        self.assertEqual(state['stage'], 'blocked')
        self.assertIn('stale/wrong hash', state['reason'])
        self.assertFalse((self.source.parent / 'incoming1').exists())

    def test_changed_artifacts_invalidate_combined_review_on_resume(self):
        self.make_source()
        manifest = flow.plan(self.cfg, self.source)
        output_root = Path(manifest['output_root'])
        fake = FakeExecutor()
        def execute(cfg, case, stage, context, output=None):
            result = fake(cfg, case, stage, context, output)
            if stage == 'review_final':
                put(output_root / 'existing.txt', b'foreign')
            return result
        self.assertEqual(self.run_fake(execute)['cases'][0]['stage'], 'blocked')
        case = flow.case_workspace(flow.batch_folder(self.cfg, manifest), manifest['cases'][0])
        put(case / 'evidence/ui/overview.png', PNG + b'changed')
        (output_root / 'existing.txt').unlink()
        output_root.rmdir()
        state = self.run_fake(fake)['cases'][0]
        self.assertEqual(state['stage'], 'delivered', state.get('reason'))
        self.assertEqual([s for _, s in fake.stages].count('review_final'), 2)

    def test_dry_run_routes_only_one_review_stage(self):
        self.make_source()
        flow.plan(self.cfg, self.source)
        commands = flow.run_batch(self.cfg, str(self.source), dry_run=True)['cases'][0]['commands']
        self.assertEqual([stage for stage in commands if stage.startswith('review_')], ['review_final'])
        self.assertIn('gpt-6-sol', commands['review_final'])
        self.assertIn('model_reasoning_effort=ultra', commands['review_final'])
        self.assertIn('read-only', commands['review_final'])
        self.assertIn('model_reasoning_effort=high', commands['repair_final'])

    def test_unlimited_repair_continues_beyond_two_rechecks(self):
        self.cfg['runner'].update(max_review_calls_per_case=None, max_final_review_repairs=None, max_repairs_per_review=None)
        self.make_source()
        flow.plan(self.cfg, self.source)
        fake = FakeExecutor(revise_visual=True, permanent_visual=True)
        repair_count = 0
        def execute(cfg, case, stage, context, output=None):
            nonlocal repair_count
            if stage == 'repair_final':
                repair_count += 1
                if repair_count == 3:
                    fake.permanent_visual = False
            result = fake(cfg, case, stage, context, output)
            if stage == 'repair_final':
                put(case / 'evidence/ui/overview.png', PNG + str(repair_count).encode())
            return result
        state = self.run_fake(execute)['cases'][0]
        self.assertEqual(state['stage'], 'delivered', state.get('reason'))
        self.assertEqual(state['review_calls_started'], 4)
        self.assertEqual(repair_count, 3)

    def test_actionable_blocked_review_is_repaired(self):
        self.cfg['runner'].update(max_review_calls_per_case=None, max_final_review_repairs=None)
        self.make_source()
        flow.plan(self.cfg, self.source)
        fake = FakeExecutor(revise_visual=True)
        def execute(cfg, case, stage, context, output=None):
            result = fake(cfg, case, stage, context, output)
            if stage == 'review_final' and fake.revise_visual:
                report = flow.read_json(output)
                report['verdict'] = 'blocked'
                flow.atomic_json(output, report)
            return result
        state = self.run_fake(execute)['cases'][0]
        self.assertEqual(state['stage'], 'delivered', state.get('reason'))
        self.assertEqual(state['repairs_final'], 1)

    def test_real_external_blocker_is_reported_without_endless_recheck(self):
        self.cfg['runner'].update(max_review_calls_per_case=None, max_final_review_repairs=None)
        self.make_source()
        flow.plan(self.cfg, self.source)
        fake = FakeExecutor(revise_visual=True)
        def execute(cfg, case, stage, context, output=None):
            result = fake(cfg, case, stage, context, output)
            if stage == 'repair_final':
                flow.atomic_json(case / 'evidence/repair-status.json', {
                    'status': 'blocked', 'requires_user_input': True, 'reason': 'fixture missing source measurement'})
            return result
        state = self.run_fake(execute)['cases'][0]
        self.assertEqual(state['stage'], 'blocked')
        self.assertIn('missing source measurement', state['reason'])
        self.assertEqual(state['review_calls_started'], 1)
        calls = len(fake.stages)
        with patch.dict('os.environ', {'CASEFLOW_DEFER_EXTERNAL_BLOCKERS': '1'}):
            deferred = self.run_fake(execute)['cases'][0]
        self.assertEqual(deferred['stage'], 'blocked')
        self.assertEqual(len(fake.stages), calls)

    def test_unlimited_config_is_valid_but_negative_limits_are_rejected(self):
        config = flow.read_json(self.config_path)
        config['runner'].update(review_mode='combined_final', max_review_calls_per_case=None,
                                max_final_review_repairs=None, max_repairs_per_review=None)
        flow.atomic_json(self.config_path, config)
        loaded = flow.config_at(self.config_path)
        self.assertIsNone(loaded['runner']['max_review_calls_per_case'])
        config['runner']['max_review_calls_per_case'] = -1
        flow.atomic_json(self.config_path, config)
        with self.assertRaises(flow.Blocked):
            flow.config_at(self.config_path)

    def test_external_blocked_review_can_resume_after_new_evidence(self):
        self.cfg['runner'].update(max_review_calls_per_case=None, max_final_review_repairs=None)
        self.make_source()
        manifest = flow.plan(self.cfg, self.source)
        fake = FakeExecutor(revise_visual=True)
        def repair_requires_data(cfg, case, stage, context, output=None):
            result = fake(cfg, case, stage, context, output)
            if stage == 'repair_final':
                available = (case / 'evidence/new-external-data.txt').exists()
                flow.atomic_json(case / 'evidence/repair-status.json', {
                    'status': 'ready_for_review' if available else 'blocked',
                    'requires_user_input': not available, 'reason': 'fixture external data'})
            return result
        self.assertEqual(self.run_fake(repair_requires_data)['cases'][0]['stage'], 'blocked')
        self.assertEqual(self.run_fake(repair_requires_data)['cases'][0]['stage'], 'blocked')
        self.assertEqual([s for _, s in fake.stages].count('review_final'), 1)
        case = flow.case_workspace(flow.batch_folder(self.cfg, manifest), manifest['cases'][0])
        put(case / 'evidence/new-external-data.txt', b'fixture evidence supplied')
        state = self.run_fake(repair_requires_data)['cases'][0]
        self.assertEqual(state['stage'], 'delivered', state.get('reason'))

    def test_authorized_material_autofill_reopens_only_pending_repair(self):
        self.cfg['runner'].update(max_review_calls_per_case=None, max_final_review_repairs=None)
        self.make_source()
        manifest = flow.plan(self.cfg, self.source)
        fake = FakeExecutor(revise_visual=True)
        def initial_block(cfg, case, stage, context, output=None):
            result = fake(cfg, case, stage, context, output)
            if stage == 'repair_final':
                flow.atomic_json(case / 'evidence/repair-status.json', {
                    'status': 'blocked', 'requires_user_input': True, 'reason': 'fixture material gap'})
            return result
        self.assertEqual(self.run_fake(initial_block)['cases'][0]['stage'], 'blocked')
        case = flow.case_workspace(flow.batch_folder(self.cfg, manifest), manifest['cases'][0])
        flow.atomic_json(case / 'evidence/repair-status.json', {
            'status': 'authorized_pending_repair', 'requires_user_input': False,
            'user_authorized_autofill': True, 'reason': 'fixture user authorization'})
        observed = []
        def complete(cfg, workspace, stage, context, output=None):
            if stage == 'repair_final':
                observed.append(context.get('authorized_material_autofill', {}).get('user_authorized_autofill'))
            result = fake(cfg, workspace, stage, context, output)
            if stage == 'repair_final':
                flow.atomic_json(workspace / 'evidence/repair-status.json', {
                    'status': 'ready_for_review', 'requires_user_input': False})
                put(workspace / 'evidence/ui/overview.png', PNG + b'authorized-repair')
            return result
        state = self.run_fake(complete)['cases'][0]
        self.assertEqual(state['stage'], 'delivered', state.get('reason'))
        self.assertEqual(observed, [True])

    def test_authorized_material_repair_cannot_succeed_with_pending_status(self):
        self.cfg['runner'].update(max_review_calls_per_case=None, max_final_review_repairs=None)
        self.make_source()
        manifest = flow.plan(self.cfg, self.source)
        fake = FakeExecutor(revise_visual=True)
        def initial_block(cfg, case, stage, context, output=None):
            result = fake(cfg, case, stage, context, output)
            if stage == 'repair_final':
                flow.atomic_json(case / 'evidence/repair-status.json', {
                    'status': 'blocked', 'requires_user_input': True, 'reason': 'fixture material gap'})
            return result
        self.assertEqual(self.run_fake(initial_block)['cases'][0]['stage'], 'blocked')
        case = flow.case_workspace(flow.batch_folder(self.cfg, manifest), manifest['cases'][0])
        flow.atomic_json(case / 'evidence/repair-status.json', {
            'status': 'authorized_pending_repair', 'requires_user_input': False,
            'user_authorized_autofill': True, 'reason': 'fixture user authorization'})
        state = self.run_fake(fake)['cases'][0]
        self.assertEqual(state['stage'], 'blocked')
        self.assertIn('remains unfinished', state['reason'])
