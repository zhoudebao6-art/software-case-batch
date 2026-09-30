"""Explicit repair effort is separate from construction and read-only review."""
import unittest
from pathlib import Path
from unittest.mock import patch
import test_caseflow as fixtures
from test_caseflow import flow


class RepairModelTests(unittest.TestCase):
    setUp = fixtures.CaseflowTests.setUp
    tearDown = fixtures.CaseflowTests.tearDown

    def configured(self):
        cfg = flow.read_json(self.config_path)
        cfg['models']['builder'] = {'model': 'gpt-6.1-sol', 'reasoning_effort': 'high'}
        cfg['models']['repairer'] = {'model': 'gpt-6.1-sol', 'reasoning_effort': 'ultra'}
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
        self.assertIn('gpt-6-sol', review)
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


if __name__ == '__main__': unittest.main()
