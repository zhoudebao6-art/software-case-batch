from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from sandbox_probe import check_worker_sandbox, runtime_diagnostics
from runtime_doctor import failure_kind


class SandboxProbeTests(unittest.TestCase):
    def run_probe(self, execute, mode='workspace-write'):
        with tempfile.TemporaryDirectory() as tmp, \
             patch('caseflow.native_codex', return_value=Path('codex.exe')), \
             patch('sandbox_probe.sandbox_log_cursor', return_value={}), \
             patch('sandbox_probe.run_probe_command', side_effect=execute):
            return check_worker_sandbox({'runtime': {'python': 'python.exe'}}, tmp, mode=mode)

    def test_modern_cli_runs_write_read_remove_without_model_or_permission_changes(self):
        seen = []
        def execute(command, **kwargs):
            seen.append(command)
            if command[1:] == ['help', 'sandbox']:
                return subprocess.CompletedProcess(command, 0, 'Full command args to run under Windows', '')
            code = command[-1]
            marker = code.split('print(')[1].split(')')[0].strip("'")
            self.assertIn("p.open('x'", code)
            self.assertIn('p.unlink()', code)
            self.assertIn('sandbox_mode="workspace-write"', command)
            self.assertNotIn('exec', command)
            self.assertNotIn('--approve-for-me', command)
            self.assertNotIn('-C', command)
            self.assertTrue(Path(kwargs['cwd']).is_dir())
            self.assertEqual(Path(kwargs['env']['TEMP']), Path(kwargs['cwd']) / '.runtime' / 'tmp')
            return subprocess.CompletedProcess(command, 0, marker + '\n', '')
        result = self.run_probe(execute)
        self.assertTrue(result['ok'])
        self.assertEqual(result['model_calls'], 0)
        self.assertEqual(len(seen), 2)

    def test_old_cli_uses_documented_windows_subcommand_and_same_cwd(self):
        def execute(command, **kwargs):
            if command[1:] == ['help', 'sandbox']:
                return subprocess.CompletedProcess(command, 0, 'Commands:\n  windows  Run sandbox', '')
            self.assertEqual(command[3:5], ['sandbox', 'windows'])
            self.assertTrue(Path(kwargs['cwd']).is_dir())
            self.assertIn('sandbox_mode="read-only"', command)
            self.assertNotIn("p.open('x'", command[-1])
            marker = command[-1].split('print(')[1].split(')')[0].strip("'")
            return subprocess.CompletedProcess(command, 0, marker, '')
        self.assertTrue(self.run_probe(execute, mode='read-only')['ok'])

    def test_failed_refresh_stays_failed_and_reads_bounded_runtime_context(self):
        execute = [subprocess.CompletedProcess([], 0, 'Full command args to run under Windows', ''),
                   subprocess.CompletedProcess([], 1, '', 'helper_unknown_error: setup refresh had errors')]
        with patch('sandbox_probe.runtime_diagnostics', return_value=[
                'runtime read/execute validation failed: node_repl.exe: sharing violation (os error 32)']):
            result = self.run_probe(execute)
        self.assertFalse(result['ok'])
        self.assertEqual(result['kind'], 'file_in_use')
        self.assertEqual(result['model_calls'], 0)
        self.assertEqual(len(result['fingerprint']), 64)

    def test_exit_zero_without_marker_does_not_claim_success(self):
        result = self.run_probe([
            subprocess.CompletedProcess([], 0, 'Full command args to run under Windows', ''),
            subprocess.CompletedProcess([], 0, '', '')])
        self.assertFalse(result['ok'])

    def test_unknown_help_fails_without_attempting_a_command(self):
        result = self.run_probe([subprocess.CompletedProcess([], 0, 'unknown version', '')])
        self.assertFalse(result['ok'])
        self.assertNotIn('command', result)

    def test_timeout_is_not_a_pass_and_modes_cannot_be_weakened(self):
        result = self.run_probe([subprocess.TimeoutExpired('codex help sandbox', 15)])
        self.assertFalse(result['ok'])
        with self.assertRaises(ValueError):
            check_worker_sandbox({}, '.', mode='danger-full-access')

    def test_sharing_setup_and_policy_are_distinct(self):
        self.assertEqual(failure_kind('os error 32'), 'file_in_use')
        self.assertEqual(failure_kind('setup refresh had errors'), 'sandbox_setup_failed')
        self.assertEqual(failure_kind('blocked by policy'), 'policy_denied')

    def test_runtime_context_excludes_old_and_summary_lines(self):
        with tempfile.TemporaryDirectory() as tmp:
            log = Path(tmp) / 'sandbox.log'
            log.write_text('[old] runtime read/execute validation failed: old\n', encoding='utf-8')
            before = {log: log.stat().st_size}
            with log.open('a', encoding='utf-8') as stream:
                stream.write('[new] runtime read/execute validation failed: node_repl.exe (os error 32)\n')
                stream.write('[new] setup refresh: errors=[runtime read/execute validation failed: duplicate]\n')
            with patch('sandbox_probe.sandbox_log_cursor', return_value={log: log.stat().st_size}):
                self.assertEqual(runtime_diagnostics(before), [
                    'runtime read/execute validation failed: node_repl.exe (os error 32)'])


if __name__ == '__main__':
    unittest.main()
