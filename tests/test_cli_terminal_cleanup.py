import json
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from test_caseflow import flow


class TerminalCleanupTests(unittest.TestCase):
    def test_completed_cli_cleanup_preserves_actual_exit_code_and_only_terminates_cli(self):
        with tempfile.TemporaryDirectory() as temp:
            log = Path(temp) / 'worker.jsonl'
            log.write_text(json.dumps({'type': 'turn.completed', 'usage': {'output_tokens': 8}}) + '\n')

            class Process:
                args = ['codex.exe', 'exec']
                returncode = None
                terminated = 0
                inputs = []

                def communicate(self, input=None, timeout=None):
                    self.inputs.append(input)
                    if self.returncode is None:
                        raise subprocess.TimeoutExpired(self.args, timeout)
                    return None, None

                def terminate(self):
                    self.terminated += 1
                    self.returncode = -1

            proc = Process()
            tick = iter(range(0, 1000, 10))
            with patch.object(flow.time, 'monotonic', side_effect=lambda: next(tick)):
                cleanup = flow.wait_for_cli_exit(proc, 'prompt', 300, log, terminal_grace=30)
            self.assertTrue(cleanup)
            self.assertEqual(proc.terminated, 1)
            self.assertEqual(proc.returncode, -1)
            self.assertEqual(proc.inputs[0], 'prompt')
            self.assertTrue(all(value is None for value in proc.inputs[1:]))

    def test_error_or_nested_terminal_text_does_not_trigger_completed_cleanup(self):
        with tempfile.TemporaryDirectory() as temp:
            log = Path(temp) / 'worker.jsonl'
            log.write_text(json.dumps({'type': 'item.completed', 'item': {
                'type': 'command_execution', 'aggregated_output': '{"type":"turn.completed"}'}}) + '\n')
            self.assertFalse(flow.cli_terminal_completed(log))
            log.write_text(json.dumps({'type': 'turn.failed', 'error': 'policy denied'}) + '\n')
            self.assertFalse(flow.cli_terminal_completed(log))

    def test_nonzero_result_requires_parent_cleanup_terminal_and_actual_final_message(self):
        base = {'exit_code': -1, 'terminal_cli_cleanup': True,
                'terminal_completed': True, 'final_message': 'Actual phase result.'}
        self.assertTrue(flow.worker_call_completed(base))
        for key in ('terminal_cli_cleanup', 'terminal_completed', 'final_message'):
            missing = dict(base)
            missing[key] = False
            self.assertFalse(flow.worker_call_completed(missing))
        self.assertFalse(flow.worker_call_completed({'exit_code': 1, 'final_message': 'blocked by policy'}))
        self.assertFalse(flow.worker_call_completed({**base, 'timed_out': True}))

    def test_running_or_failed_worker_keeps_normal_timeout_and_is_not_terminal_cleanup(self):
        with tempfile.TemporaryDirectory() as temp:
            log = Path(temp) / 'worker.jsonl'
            log.write_text('{"type":"turn.failed","error":"policy denied"}\n')

            class Process:
                args = ['codex.exe', 'exec']
                terminated = False

                def communicate(self, input=None, timeout=None):
                    raise subprocess.TimeoutExpired(self.args, timeout)

                def terminate(self):
                    self.terminated = True

            proc = Process()
            tick = iter(range(0, 1000, 10))
            with patch.object(flow.time, 'monotonic', side_effect=lambda: next(tick)):
                with self.assertRaises(subprocess.TimeoutExpired):
                    flow.wait_for_cli_exit(proc, 'prompt', 40, log, terminal_grace=10)
            self.assertFalse(proc.terminated)


if __name__ == '__main__':
    unittest.main()
