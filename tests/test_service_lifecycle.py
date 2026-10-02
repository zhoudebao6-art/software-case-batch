"""Mocked lifecycle checks plus one isolated Windows temporary-service test."""
import copy
import hashlib
import json
from pathlib import Path
import tempfile
import os
import subprocess
import sys
import time
import unittest
from unittest.mock import patch
import test_caseflow
import service_lifecycle as life


class ServiceLifecycleTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.case = Path(self.tmp.name).resolve() / '业务案'
        self.case.mkdir()
        command = f'python "{self.case}/server.py"'
        self.identity = {'pid': 123, 'port': 18001, 'listener_ports': [18001],
                         'created_at': '2026-10-01T00:00:00.0000000+00:00',
                         'command_line': command,
                         'command_line_sha256': hashlib.sha256(command.encode()).hexdigest()}
        self.plan = {'base_url': 'http://127.0.0.1:18001', 'health_path': '/health',
                     'case_id': 'case', 'version': 'v1'}
        self.proof = {'status': 'verified', 'identity': self.identity, 'case_id': 'case',
                      'workspace': str(self.case), 'version': 'v1', 'assigned_ports': [18001]}
        self.report = {'service_process': self.proof, 'service_plan': self.plan}

    def test_only_verified_delivered_listener_is_stopped(self):
        with patch.object(life, 'listener_identity', side_effect=[self.identity, None]), \
             patch('capture_runner.service_ready') as health, \
             patch.object(life, 'terminate_verified') as stop:
            result = life.cleanup_after_delivery(self.case, 'case', self.report)
        self.assertEqual(result['status'], 'stopped')
        stop.assert_called_once_with(self.identity)
        health.assert_called_once()

    def test_pid_reuse_foreign_command_shared_port_and_wrong_case_do_not_stop(self):
        for update in ({'pid': 456}, {'created_at': 'new'}, {'command_line_sha256': 'changed'},
                       {'command_line': 'python other/server.py'}, {'listener_ports': [18001, 8888]}):
            with self.subTest(update=update), patch.object(life, 'listener_identity', return_value={**self.identity, **update}), \
                 patch.object(life, 'terminate_verified') as stop:
                result = life.cleanup_after_delivery(self.case, 'case', self.report)
                self.assertEqual(result['status'], 'pending')
                stop.assert_not_called()

    def test_keep_online_inflight_and_missing_proof_remain_pending(self):
        for in_flight, report in ((True, self.report), (False, {})):
            with patch.object(life, 'terminate_verified') as stop:
                self.assertEqual(life.cleanup_after_delivery(self.case, 'case', report, in_flight=in_flight)['status'], 'pending')
                stop.assert_not_called()
        (self.case / '.runtime').mkdir()
        (self.case / '.runtime/keep-online.json').write_text('{}')
        with patch.object(life, 'listener_identity') as probe:
            self.assertEqual(life.cleanup_after_delivery(self.case, 'case', self.report)['status'], 'pending')
            probe.assert_not_called()

    def test_stop_policy_denied_is_recorded_without_retry(self):
        with patch.object(life, 'listener_identity', return_value=self.identity), \
             patch('capture_runner.service_ready'), \
             patch.object(life, 'terminate_verified', side_effect=life.IdentityError('blocked by policy')) as stop:
            result = life.cleanup_after_delivery(self.case, 'case', self.report)
        self.assertEqual(result['status'], 'pending')
        self.assertEqual(result['failure_kind'], 'policy_denied')
        self.assertEqual(stop.call_count, 1)

    def test_health_mismatch_does_not_stop(self):
        with patch.object(life, 'listener_identity', return_value=self.identity), \
             patch('capture_runner.service_ready', side_effect=ValueError('wrong version')), \
             patch.object(life, 'terminate_verified') as stop:
            self.assertEqual(life.cleanup_after_delivery(self.case, 'case', self.report)['status'], 'pending')
        stop.assert_not_called()

    def test_command_boundary_and_protected_title_services(self):
        self.assertTrue(life.case_owns_command(self.case, self.identity['command_line']))
        self.assertFalse(life.case_owns_command(self.case, f'python "{self.case}-other/server.py"'))
        self.assertFalse(life.case_owns_command(self.case, f'python "{self.case}/Hermes.py"'))

    def test_listener_probe_preserves_unicode_and_absence(self):
        with patch.object(life, '_powershell_json', return_value={'absent': True}):
            self.assertIsNone(life.listener_identity(18001))
        with patch.object(life, '_powershell_json', return_value=copy.deepcopy(self.identity)):
            self.assertEqual(life.listener_identity(18001)['command_line_sha256'], self.identity['command_line_sha256'])

    def test_receipt_outside_case_preserves_review_snapshot_and_no_retry(self):
        import caseflow as flow
        folder = Path(self.tmp.name) / 'batch'
        folder.mkdir()
        (self.case / 'evidence').mkdir()
        flow.atomic_json(self.case / 'evidence/artifact-manifest.json', {})
        before = flow.snapshot(self.case, video=True)
        state = {'case_id': 'case', 'stage': 'delivered'}
        with patch.object(life, 'cleanup_after_delivery', return_value={'status': 'pending'}) as clean:
            flow.finish_delivery_cleanup(self.case, folder, state)
            flow.finish_delivery_cleanup(self.case, folder, state)
        clean.assert_called_once()
        self.assertTrue(state['cleanup_pending'])
        self.assertTrue(Path(state['cleanup_receipt']).is_file())
        self.assertEqual(before, flow.snapshot(self.case, video=True))

    @unittest.skipUnless(os.name == 'nt', 'Windows listener/process handle integration')
    def test_windows_isolated_service_identity_and_exact_handle_cleanup(self):
        script = self.case / 'server.py'
        script.write_text('''import json, sys
from pathlib import Path
from http.server import BaseHTTPRequestHandler, HTTPServer
root=Path(__file__).resolve().parent
class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        body=json.dumps({'case_id':'case','workspace':str(root),'version':'v1'}).encode()
        self.send_response(200);self.send_header('Content-Length',str(len(body)));self.end_headers();self.wfile.write(body)
    def log_message(self,*args): pass
server=HTTPServer(('127.0.0.1',0),Handler)
(root/'port.txt').write_text(str(server.server_port))
server.serve_forever()
''', encoding='utf-8')
        child = subprocess.Popen([sys.executable, str(script)], stdout=subprocess.DEVNULL, stderr=subprocess.PIPE,
                                 creationflags=subprocess.CREATE_NO_WINDOW)
        try:
            deadline = time.monotonic() + 10
            while not (self.case/'port.txt').is_file() and child.poll() is None and time.monotonic() < deadline:
                time.sleep(.05)
            self.assertTrue((self.case/'port.txt').is_file())
            port = int((self.case/'port.txt').read_text())
            plan = {**self.plan, 'base_url': f'http://127.0.0.1:{port}'}
            proof = life.capture_identity(self.case, [port], plan)
            self.assertEqual(proof['status'], 'verified', proof)
            self.assertEqual(proof['identity']['pid'], child.pid)
            receipt = life.cleanup_after_delivery(self.case, 'case', {'service_process': proof, 'service_plan': plan})
            self.assertEqual(receipt['status'], 'stopped', receipt)
            child.wait(timeout=5)
        finally:
            if child.poll() is None:
                child.terminate(); child.wait(timeout=5)
            if child.stderr:
                child.stderr.close()


if __name__ == '__main__':
    unittest.main()
