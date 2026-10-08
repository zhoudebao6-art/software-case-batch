"""Explicit repair effort is separate from construction and read-only review."""
import unittest
from pathlib import Path
from unittest.mock import patch
import test_caseflow as fixtures
from test_caseflow import flow, FakeExecutor


class RepairModelTests(unittest.TestCase):
    setUp = fixtures.CaseflowTests.setUp
    tearDown = fixtures.CaseflowTests.tearDown
    make_source = fixtures.CaseflowTests.make_source
    run_fake = fixtures.CaseflowTests.run_fake

    def configured(self):
        cfg = flow.read_json(self.config_path)
        cfg['models']['builder'] = {'model': 'gpt-6.1-sol', 'reasoning_effort': 'high'}
        cfg['models']['repairer'] = {'model': 'gpt-6.1-sol', 'reasoning_effort': 'ultra'}
        cfg['models']['reviewer'] = {'model': 'gpt-6.1-sol', 'reasoning_effort': 'ultra'}
        flow.atomic_json(self.config_path, cfg)
        return flow.config_at(self.config_path)

    def test_actual_stage_commands_separate_high_build_and_ultra_repair(self):
        cfg = self.configured()
        for stage in ('repair_visual', 'repair_final', 'repair_video', 'prepare_video'):
            cmd = flow.command_for(cfg, self.root, stage, dry_run=True)
            self.assertIn('gpt-6.1-sol', cmd)
            self.assertIn('model_reasoning_effort=ultra', cmd)
            self.assertNotIn('read-only', cmd)
        self.assertIn('model_reasoning_effort=high', flow.command_for(cfg, self.root, 'build', dry_run=True))
        review = flow.command_for(cfg, self.root, 'review_final', self.root / 'r.json', dry_run=True)
        self.assertIn('gpt-6.1-sol', review)
        self.assertIn('model_reasoning_effort=ultra', review)
        self.assertIn('read-only', review)

    def test_explicit_wrong_repair_route_is_rejected(self):
        self.configured()
        for selected in ({'model': 'gpt-6.1-sol', 'reasoning_effort': 'high'},
                         {'model': 'gpt-6-astra', 'reasoning_effort': 'low'}, None):
            cfg = flow.read_json(self.config_path); cfg['models']['repairer'] = selected
            flow.atomic_json(self.config_path, cfg)
            with self.assertRaises(flow.Blocked): flow.config_at(self.config_path)

    def test_launch_failure_record_still_records_actual_repair_effort(self):
        cfg = self.configured(); case = self.root / 'case'; case.mkdir()
        with patch.object(flow, 'native_codex', return_value=self.exe), \
             patch.object(flow.subprocess, 'Popen', side_effect=OSError('fixture launch error')):
            record = flow.invoke(cfg, case, 'repair_final', {})
        self.assertEqual((record['model'], record['reasoning_effort']), ('gpt-6.1-sol', 'ultra'))
        self.assertIn('model_reasoning_effort=ultra', record['command'])
        self.assertEqual(record['exit_code'], -1)

    def test_default_config_and_batch_dispatch_use_same_sol_61_routes(self):
        defaults = flow.config_at(Path(__file__).resolve().parents[1] / 'config.example.json')
        self.assertEqual(defaults['models']['builder'], {'model': 'gpt-6.1-sol', 'reasoning_effort': 'high'})
        for role in ('repairer', 'reviewer'):
            self.assertEqual(defaults['models'][role], {'model': 'gpt-6.1-sol', 'reasoning_effort': 'ultra'})
        self.cfg = self.configured()
        self.cfg['runner']['review_mode'] = 'combined_final'
        self.make_source()
        batch = flow.plan(self.cfg, self.source)
        commands = flow.run_batch(self.cfg, batch['batch_id'], dry_run=True)['cases'][0]['commands']
        for stage, command in commands.items():
            self.assertIn('gpt-6.1-sol', command, stage)
            effort = 'ultra' if stage.startswith(('review_', 'repair_')) else 'high'
            self.assertIn('model_reasoning_effort=' + effort, command, stage)
        state = self.run_fake(FakeExecutor())['cases'][0]
        self.assertEqual(state['stage'], 'delivered', state.get('reason'))
        self.assertEqual(state['final_review']['model'], 'gpt-6.1-sol')

    def test_new_default_preserves_hash_bound_legacy_delivery_without_new_calls(self):
        self.cfg['runner']['review_mode'] = 'combined_final'
        self.make_source(); flow.plan(self.cfg, self.source)
        fake = FakeExecutor()
        before = self.run_fake(fake)['cases'][0]
        self.assertEqual(before['stage'], 'delivered', before.get('reason'))
        self.assertEqual(before['final_review']['model'], 'gpt-6-sol')
        calls = len(fake.stages)
        self.cfg['models']['reviewer'] = {'model': 'gpt-6.1-sol', 'reasoning_effort': 'ultra'}
        after = self.run_fake(fake)['cases'][0]
        self.assertEqual(after['stage'], 'delivered', after.get('reason'))
        self.assertEqual(after['delivery_sha256'], before['delivery_sha256'])
        self.assertEqual(after['final_review'], before['final_review'])
        self.assertEqual(len(fake.stages), calls)

    def test_new_review_cannot_report_old_model_as_current_route(self):
        self.cfg = self.configured()
        self.cfg['runner']['review_mode'] = 'combined_final'
        self.make_source(); flow.plan(self.cfg, self.source)
        fake = FakeExecutor()
        def wrong(cfg, case, stage, context, output=None):
            result = fake(cfg, case, stage, context, output)
            if stage.startswith('review_'):
                result['model'] = 'gpt-6-sol'
            return result
        state = self.run_fake(wrong)['cases'][0]
        self.assertEqual(state['stage'], 'blocked')
        self.assertIn('explicitly selected route', state['reason'])

    def test_standard_reviewer_cannot_lower_effort(self):
        cfg = flow.read_json(self.config_path)
        cfg['models']['reviewer'] = {'model': 'gpt-6.1-sol', 'reasoning_effort': 'high'}
        flow.atomic_json(self.config_path, cfg)
        with self.assertRaises(flow.Blocked):
            flow.config_at(self.config_path)


if __name__ == '__main__': unittest.main()
