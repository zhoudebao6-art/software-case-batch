import unittest
import sys
import json
import tempfile
from unittest.mock import patch
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import caseflow as flow


class WorkerApprovalRouteTests(unittest.TestCase):
    def cfg(self, mode='auto_review'):
        return {'runner': {'worker_approval_mode': mode}, 'models': {
            'builder': {'model': 'gpt-6-sol', 'reasoning_effort': 'high'},
            'reviewer': {'model': 'gpt-6-sol', 'reasoning_effort': 'ultra'}}}

    def test_build_and_repair_can_request_independent_review(self):
        for stage in ['build', 'repair_visual', 'repair_final', 'video']:
            cmd = flow.command_for(self.cfg(), Path('case'), stage, dry_run=True)
            self.assertIn('--approve-for-me', cmd)
            self.assertNotIn('approval_policy=never', cmd)
            self.assertNotIn('--sandbox', cmd)  # flag already selects workspace-write
            self.assertNotIn('--dangerously-bypass-approvals-and-sandbox', cmd)
            self.assertIn('model_reasoning_effort=high', cmd)

    def test_independent_acceptance_remains_read_only_without_escalation(self):
        for stage in ['review_visual', 'review_video', 'review_final']:
            cmd = flow.command_for(self.cfg(), Path('case'), stage, Path('review.json'), dry_run=True)
            self.assertNotIn('--approve-for-me', cmd)
            self.assertIn('approval_policy=never', cmd)
            self.assertEqual(cmd[cmd.index('--sandbox') + 1], 'read-only')
            self.assertIn('model_reasoning_effort=ultra', cmd)

    def test_missing_opt_in_preserves_previous_route(self):
        cfg = self.cfg(); cfg['runner'].pop('worker_approval_mode')
        self.assertIn('approval_policy=never', flow.command_for(cfg, Path('case'), 'build', dry_run=True))

    def test_unknown_or_unrestricted_modes_fail_closed(self):
        for mode in ['full_access', 'on-request', 'bypass', None]:
            with self.assertRaises(flow.Blocked):
                flow.command_for(self.cfg(mode), Path('case'), 'build', dry_run=True)

    def test_pinned_cli_failure_never_silently_uses_desktop_cli(self):
        cfg = self.cfg()
        with tempfile.TemporaryDirectory() as tmp:
            cfg['runner']['codex_executable'] = str(Path(tmp) / 'missing.exe')
            with patch.object(flow.shutil, 'which', side_effect=AssertionError('Fallback forbidden')):
                with self.assertRaisesRegex(flow.Blocked, 'refusing fallback'):
                    flow.native_codex(cfg)

    def test_opted_in_nested_runtime_uses_same_cli_and_preserves_restrictions(self):
        cfg = self.cfg()
        cfg['runner'].update(codex_executable=r'E:\verified runtime\codex.exe', bind_node_repl_cli=True)
        for stage in ('build', 'review_final'):
            cmd = flow.command_for(cfg, Path('case'), stage, Path('review.json'), dry_run=True)
            binding = next(x for x in cmd if x.startswith('mcp_servers.node_repl.env.CODEX_CLI_PATH='))
            self.assertEqual(json.loads(binding.split('=', 1)[1]), cmd[0])
            if stage.startswith('review_'):
                self.assertIn('approval_policy=never', cmd)
                self.assertEqual(cmd[cmd.index('--sandbox') + 1], 'read-only')
            else:
                self.assertIn('--approve-for-me', cmd)
            self.assertNotIn('danger-full-access', cmd)

    def test_machines_without_node_repl_do_not_invent_mcp_configuration(self):
        cmd = flow.command_for(self.cfg(), Path('case'), 'build', dry_run=True)
        self.assertFalse(any('mcp_servers.node_repl' in x for x in cmd))


if __name__ == '__main__':
    unittest.main()
