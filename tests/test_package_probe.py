"""Real tiny isolated applications/process trees, never production case reruns."""
import json
import ctypes
from ctypes import wintypes
import os
from pathlib import Path
import socket
import struct
import subprocess
import sys
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import patch
import zipfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from common import digest, read_json, write_json
import package_probe
from package_probe import probe, unpack, validate_result, stop_windows_job

APP = '''\
from http.server import BaseHTTPRequestHandler, HTTPServer
import json
from pathlib import Path
class Handler(BaseHTTPRequestHandler):
    def log_message(self, *args): pass
    def do_GET(self):
        value = json.loads(Path('saved.json').read_text())
        self.send_response(200); self.end_headers(); self.wfile.write(json.dumps(value).encode())
    def do_POST(self):
        value = json.loads(self.rfile.read(int(self.headers['Content-Length'])))
        result = {'sum': value['a'] + value['b']}
        Path('saved.json').write_text(json.dumps(result))
        self.send_response(200); self.end_headers(); self.wfile.write(json.dumps(result).encode())
server = HTTPServer(('127.0.0.1', 0), Handler)
Path('port.txt').write_text(str(server.server_port))
server.serve_forever()
'''

CASE_PROBE = '''\
import json, os, socket, subprocess, sys, time, urllib.request
from pathlib import Path
root = Path(os.environ['SCB_PACKAGE_ROOT'])
child = subprocess.Popen([sys.executable, '-B', str(root / 'app.py')], cwd=root)
for i in range(100):
    if (root / 'port.txt').exists(): break
    assert child.poll() is None
    time.sleep(.02)
port = int((root / 'port.txt').read_text())
base = 'http://127.0.0.1:' + str(port)
request = urllib.request.Request(base, json.dumps({'a': 7, 'b': 11}).encode(), {'Content-Type': 'application/json'})
with urllib.request.urlopen(request, timeout=3) as response:
    assert json.loads(response.read()) == {'sum': 18}
with urllib.request.urlopen(base, timeout=3) as response:
    assert json.loads(response.read()) == {'sum': 18}
result = {'core_flow': 'POST calculation persists sum 18; GET returns the saved value', 'port': port,
          'child_pid': child.pid,
          'checks': [{'kind': 'startup', 'name': 'extracted HTTP service responds', 'passed': True},
                     {'kind': 'core_flow', 'name': 'calculation and persisted query agree', 'passed': True}]}
Path(os.environ['SCB_PACKAGE_RESULT']).write_text(json.dumps(result), encoding='utf-8')
print('extracted application actual startup/core chain exercised', flush=True)
# Leave the real listener for the invocation Job/session to close.
'''


class PackageProbeTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.work = self.root / 'case'; (self.work / '.product-v2').mkdir(parents=True)
        self.out = self.root / 'product'; (self.out / '模拟系统').mkdir(parents=True)
        self.archive = self.out / '模拟系统/项目源码.zip'
        with zipfile.ZipFile(self.archive, 'w') as bundle:
            bundle.writestr('app.py', APP)
        write_json(self.work / '.product-v2/run.json', {'workspace': str(self.work), 'run_id': 'isolated-test', 'output': str(self.out)})
        write_json(self.work / '.product-v2/source-package.json', {'sha256': digest(self.archive)})
        self.case_probe = self.work / 'case_probe.py'; self.case_probe.write_text(CASE_PROBE, encoding='utf-8')
        self.receipt = self.work / 'evidence/startup.json'
        self.environment = patch.dict(os.environ, SCB_PRO_PYTHON=sys.executable)
        self.environment.start(); self.addCleanup(self.environment.stop)

    def assert_port_closed(self, port):
        with socket.socket() as sock:
            sock.settimeout(.2)
            self.assertNotEqual(sock.connect_ex(('127.0.0.1', port)), 0)

    def test_real_extracted_service_core_chain_and_child_exit(self):
        original = digest(self.archive)
        result = probe(self.work, self.case_probe, self.receipt, timeout=15)
        self.assertEqual(result['status'], 'completed', result)
        self.assertEqual(result['source_zip_sha256'], original)
        self.assertEqual(digest(self.archive), original)
        self.assertEqual(result['cleanup']['status'], 'stopped')
        self.assertEqual(result['cleanup']['remaining_pids'], [])
        self.assert_port_closed(result['case_assertions']['port'])
        self.assertFalse(Path(result['extract_root']).exists())
        self.assertFalse((self.out / '.product-v2').exists())
        self.assertTrue(Path(result['log']).read_text(encoding='utf-8').strip())
        self.assertEqual(read_json(self.receipt), result)
        self.assertEqual(result['execution_check']['kind'], 'package_startup')
        self.assertEqual(result['execution_check']['sha256'], digest(Path(result['log'])))
        with self.assertRaisesRegex(ValueError, 'wholly new'):
            probe(self.work, self.case_probe, self.receipt)

    def test_new_layout_real_extracted_service_core_chain_and_child_exit(self):
        # Same real startup/probe/precise teardown through the new frozen path.
        target=self.out/'系统材料'
        (self.out/'模拟系统').rename(target)
        (target/'项目源码.zip').rename(target/'源代码.zip')
        self.archive=target/'源代码.zip'
        run=read_json(self.work/'.product-v2/run.json')
        run['delivery_layout_version']='system-materials-v2'
        write_json(self.work/'.product-v2/run.json',run)
        self.test_real_extracted_service_core_chain_and_child_exit()

    def test_timeout_closes_real_listener_and_retains_failed_tree(self):
        self.case_probe.write_text(CASE_PROBE + '\nwhile True: time.sleep(.1)\n', encoding='utf-8')
        result = probe(self.work, self.case_probe, self.receipt, timeout=1.5)
        self.assertEqual(result['status'], 'failed', result)
        self.assertTrue(result['timed_out'])
        self.assertEqual(result['cleanup']['remaining_pids'], [])
        self.assertEqual(result['cleanup']['status'], 'stopped')
        extract = Path(result['extract_root']); self.addCleanup(__import__('shutil').rmtree, extract)
        self.assert_port_closed(int((extract / 'port.txt').read_text()))

    def test_cli_runs_real_probe_and_returns_small_receipt_pointer(self):
        command = [sys.executable, '-B', str(Path(__file__).resolve().parents[1] / 'scripts/package_probe.py'),
                   'run', '--workspace', str(self.work), '--probe', str(self.case_probe), '--receipt', str(self.receipt)]
        result = subprocess.run(command, capture_output=True, text=True, encoding='utf-8', timeout=25)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        output = json.loads(result.stdout)
        self.assertEqual(output['status'], 'completed')
        self.assertEqual(output['receipt'], str(self.receipt))
        self.assertNotIn('command', output)
        self.assert_port_closed(read_json(self.receipt)['case_assertions']['port'])

    def test_mismatched_zip_and_external_probe_refused_before_receipt(self):
        self.archive.write_bytes(b'changed')
        with self.assertRaisesRegex(ValueError, 'differs'):
            probe(self.work, self.case_probe, self.receipt)
        self.assertFalse(self.receipt.exists())
        with self.assertRaisesRegex(ValueError, 'inside the original'):
            probe(self.work, Path(__file__), self.receipt)

    def test_cli_nonobject_package_metadata_is_blocked_before_receipt_or_case_execution(self):
        marker = self.work / 'case-was-executed'
        self.case_probe.write_text('from pathlib import Path\nPath(' + repr(str(marker)) + ').touch()\n', encoding='utf-8')
        for value in ([], None, 'wrong shape', 42):
            with self.subTest(value=value):
                write_json(self.work / '.product-v2/source-package.json', value)
                command = [sys.executable, '-B', str(Path(__file__).resolve().parents[1] / 'scripts/package_probe.py'),
                           'run', '--workspace', str(self.work), '--probe', str(self.case_probe), '--receipt', str(self.receipt)]
                actual = subprocess.run(command, capture_output=True, text=True, encoding='utf-8', timeout=10)
                self.assertEqual(actual.returncode, 2, actual.stdout + actual.stderr)
                result = json.loads(actual.stdout)
                self.assertEqual(result['status'], 'blocked')
                self.assertIn('JSON object', result['error'])
                self.assertEqual(actual.stderr, '')
                self.assertFalse(self.receipt.exists())
                self.assertFalse(self.receipt.with_suffix('.log').exists())
                self.assertFalse(marker.exists())

    def test_cli_archive_decoder_failures_persist_failed_receipt_and_never_run_case(self):
        marker = self.work / 'case-was-executed'
        self.case_probe.write_text('from pathlib import Path\nPath(' + repr(str(marker)) + ').touch()\n', encoding='utf-8')
        for kind in ('unsupported-method', 'corrupt-deflate', 'bad-zip'):
            with self.subTest(kind=kind):
                with zipfile.ZipFile(self.archive, 'w', compression=zipfile.ZIP_DEFLATED) as bundle:
                    bundle.writestr('app.py', APP)
                data = bytearray(self.archive.read_bytes())
                if kind == 'unsupported-method':
                    struct.pack_into('<H', data, 8, 99)
                    struct.pack_into('<H', data, data.index(b'PK\x01\x02') + 10, 99)
                elif kind == 'corrupt-deflate':
                    length = struct.unpack_from('<H', data, 26)[0] + struct.unpack_from('<H', data, 28)[0]
                    data[30 + length] = 7  # Reserved DEFLATE block type: real zlib.error.
                else:
                    data = bytearray(b'not a ZIP archive')
                self.archive.write_bytes(data)
                archive_sha = digest(self.archive); probe_sha = digest(self.case_probe)
                write_json(self.work / '.product-v2/source-package.json', {'sha256': archive_sha})
                receipt = self.receipt.with_name(kind + '.json')
                command = [sys.executable, '-B', str(Path(__file__).resolve().parents[1] / 'scripts/package_probe.py'),
                           'run', '--workspace', str(self.work), '--probe', str(self.case_probe), '--receipt', str(receipt)]
                actual = subprocess.run(command, capture_output=True, text=True, encoding='utf-8', timeout=10)
                self.assertEqual(actual.returncode, 2, actual.stdout + actual.stderr)
                self.assertEqual(actual.stderr, '')
                self.assertEqual(json.loads(actual.stdout)['status'], 'failed')
                result = read_json(receipt)
                self.assertEqual(result['status'], 'failed')
                self.assertTrue(result['error'])
                extract = Path(result['extract_root']); self.addCleanup(__import__('shutil').rmtree, extract)
                self.assertTrue(result['extract_root_retained'])
                self.assertTrue(extract.is_dir())
                self.assertEqual(result['log_sha256'], digest(receipt.with_suffix('.log')))
                self.assertNotIn('launcher_pid', result)
                self.assertNotIn('case_assertions', result)
                self.assertNotIn('execution_check', result)
                self.assertEqual(receipt.with_suffix('.log').read_text(encoding='utf-8'), '')
                self.assertFalse(marker.exists())
                self.assertEqual(digest(self.archive), archive_sha)
                self.assertEqual(digest(self.case_probe), probe_sha)

    def test_keep_extracted_is_unprepared_and_original_service_untouched(self):
        # A real unrelated listening socket remains open throughout Job cleanup.
        with socket.socket() as other:
            other.bind(('127.0.0.1', 0)); other.listen()
            other_port = other.getsockname()[1]
            result = probe(self.work, self.case_probe, self.receipt, timeout=15, keep_extracted=True)
            self.assertEqual(result['status'], 'completed', result)
            extract = Path(result['extract_root']); self.addCleanup(__import__('shutil').rmtree, extract)
            self.assertTrue(extract.is_dir())
            self.assertFalse((extract / '.product-v2').exists())
            with socket.create_connection(('127.0.0.1', other_port), timeout=1):
                pass

    def test_exit_zero_without_business_assertions_is_failure(self):
        self.case_probe.write_text("print('no business probe')\n", encoding='utf-8')
        result = probe(self.work, self.case_probe, self.receipt, timeout=10)
        self.assertEqual(result['status'], 'failed')
        self.assertEqual(result['exit_code'], 0)
        extract = Path(result['extract_root']); self.addCleanup(__import__('shutil').rmtree, extract)

    def test_cleanup_pending_retains_tree_and_original_failure_evidence(self):
        def pending(*_):
            self.receipt.with_suffix('.log').write_text('original startup failure\n', encoding='utf-8')
            return {'exit_code': None, 'timed_out': False, 'execution_error': 'original wait failure',
                    'cleanup': {'mechanism': 'windows-job', 'status': 'cleanup_pending',
                                'remaining_pids': [123], 'errors': ['member wait failure']}}
        with patch('package_probe.execute', side_effect=pending), patch('package_probe.shutil.rmtree') as remove:
            result = probe(self.work, self.case_probe, self.receipt)
        self.assertEqual(result['status'], 'failed', result)
        self.assertEqual(result['execution_error'], 'original wait failure')
        self.assertEqual(result['cleanup']['errors'], ['member wait failure'])
        self.assertTrue(result['extract_root_retained'])
        self.assertTrue(Path(result['extract_root']).is_dir())
        self.assertEqual(self.receipt.with_suffix('.log').read_text(), 'original startup failure\n')
        self.assertEqual(result['log_sha256'], digest(self.receipt.with_suffix('.log')))
        self.assertNotIn('execution_check', result)
        remove.assert_not_called()
        self.addCleanup(__import__('shutil').rmtree, Path(result['extract_root']))

    def test_unsafe_zip_members_fail_before_extracting_any_files(self):
        for name in ('../outside', '/outside', 'C:/outside', 'folder/../outside', 'bad./x', 'CON.txt', 'a//b'):
            with self.subTest(name=name):
                archive = self.root / 'unsafe.zip'
                with zipfile.ZipFile(archive, 'w') as bundle:
                    bundle.writestr(name, 'bad')
                target = self.root / 'extract'; target.mkdir(exist_ok=True)
                with self.assertRaisesRegex(ValueError, 'Unsafe'):
                    unpack(archive, target)
                self.assertEqual(list(target.iterdir()), [])
        for names in (('same', 'SAME'), ('same/x', 'same/X')):
            with zipfile.ZipFile(self.root / 'duplicate.zip', 'w') as bundle:
                for name in names: bundle.writestr(name, 'bad')
            with self.assertRaisesRegex(ValueError, 'Duplicate'):
                unpack(self.root / 'duplicate.zip', self.root / 'extract')
        with zipfile.ZipFile(self.root / 'symlink.zip', 'w') as bundle:
            member = zipfile.ZipInfo('link'); member.external_attr = 0o120777 << 16
            bundle.writestr(member, '../outside')
        with self.assertRaisesRegex(ValueError, 'Unsafe'):
            unpack(self.root / 'symlink.zip', self.root / 'extract')

    def test_finite_timeout_and_actual_named_assertions(self):
        for timeout in (0, -1, 1801, float('nan'), float('inf'), True):
            with self.assertRaisesRegex(ValueError, 'Timeout'):
                probe(self.work, self.case_probe, self.receipt, timeout=timeout)
        for value in ({}, {'core_flow': 'actual', 'checks': []},
                      {'core_flow': 'actual', 'checks': [{'kind': 'startup', 'name': 'claim', 'passed': 1}]}):
            with self.assertRaises(ValueError): validate_result(value)


@unittest.skipUnless(os.name == 'nt', 'Windows process-handle semantics')
class WindowsPackageCleanupTests(unittest.TestCase):
    class FakeJob:
        """Job disappears from census immediately, but member exit is delayed."""
        def __init__(self, mode='async'):
            self.handle = 77
            self.k = self
            self.mode = mode
            self.now = 0
            self.terminated = False
            self.events = []
            self.member_waits = 0

        def pids(self):
            if self.terminated and self.mode == 'query-failed':
                raise ValueError('original Job query failed')
            # Deliberately empty even while the retained member is not signaled.
            return [] if self.terminated else [101, 102]

        def OpenProcess(self, rights, inherit, pid):
            self.asserted_rights = rights
            self.events.append(('open', pid))
            if self.mode == 'open-denied':
                ctypes.set_last_error(5)
                return 0
            return pid + 1000

        def IsProcessInJob(self, handle, job, member):
            ctypes.cast(member, ctypes.POINTER(wintypes.BOOL)).contents.value = True
            return True

        def TerminateJobObject(self, handle, code):
            self.events.append(('terminate-job', handle))
            if self.mode == 'terminate-failed':
                ctypes.set_last_error(5)
                return False
            self.terminated = True
            return True

        def WaitForSingleObject(self, handle, milliseconds):
            self.events.append(('wait', handle))
            if handle != 1102:
                return 0
            self.member_waits += 1
            self.now += milliseconds / 1000
            if self.mode == 'wait-failed':
                return 0xffffffff
            if self.mode == 'timeout' or self.member_waits == 1:
                return 258
            return 0

        def CloseHandle(self, handle):
            self.events.append(('close-handle', handle))
            return True

        def close(self):
            self.events.append(('close-job', self.handle))
            self.handle = None

        def ResumeThread(self, handle):
            if self.mode == 'resume-failed':
                ctypes.set_last_error(5)
                return 0xffffffff
            return 1

        def GetExitCodeProcess(self, handle, code):
            ctypes.cast(code, ctypes.POINTER(wintypes.DWORD)).contents.value = 0
            return True

    def stop(self, job, timeout=.25):
        with patch('package_probe.time.monotonic', side_effect=lambda: job.now):
            return stop_windows_job(job, timeout)

    def assert_member_handles_closed(self, job):
        self.assertEqual([event for event in job.events if event[0] == 'close-handle'],
                         [('close-handle', 1101), ('close-handle', 1102)])

    def test_empty_job_query_cannot_hide_asynchronous_member_exit(self):
        job = self.FakeJob()
        result = self.stop(job)
        self.assertEqual(result['status'], 'stopped', result)
        self.assertEqual(result['remaining_pids'], [])
        self.assertEqual(job.member_waits, 2)
        self.assertEqual(job.handle, 77)  # Observation Job is still held.
        self.assertEqual(job.asserted_rights, 0x101000)
        self.assert_member_handles_closed(job)

    def test_member_timeout_is_bounded_pending_even_when_query_is_empty(self):
        job = self.FakeJob('timeout')
        result = self.stop(job)
        self.assertEqual(result['status'], 'cleanup_pending', result)
        self.assertEqual(result['remaining_pids'], [102])
        self.assertGreaterEqual(job.now, .25)
        self.assertLessEqual(job.now, .251)
        self.assert_member_handles_closed(job)

    def test_cleanup_api_failures_preserve_reason_and_close_member_handles(self):
        for mode, reason in (('terminate-failed', 'Access is denied'),
                             ('query-failed', 'original Job query failed'),
                             ('wait-failed', 'process wait failed')):
            with self.subTest(mode=mode):
                job = self.FakeJob(mode)
                result = self.stop(job)
                self.assertEqual(result['status'], 'cleanup_pending', result)
                self.assertTrue(result['errors'])
                if mode != 'terminate-failed':
                    self.assertIn(reason, result['errors'][0])
                self.assert_member_handles_closed(job)

    def test_process_open_denial_cannot_be_reported_as_stopped(self):
        job = self.FakeJob('open-denied')
        result = self.stop(job)
        self.assertEqual(result['status'], 'cleanup_pending', result)
        self.assertTrue(all('OpenProcess failed' in error for error in result['errors']))
        self.assertEqual([event for event in job.events if event[0] == 'close-handle'], [])

    def test_launch_and_resume_failures_keep_cleanup_and_original_error(self):
        info = SimpleNamespace(pid=101, process=501, thread=502)
        for mode in ('launch-failed', 'resume-failed'):
            with self.subTest(mode=mode):
                job = self.FakeJob(mode)
                with patch('media_job.Job', return_value=job), \
                     patch('media_job.launch_suspended', side_effect=ValueError('launch fixture failure')
                           if mode == 'launch-failed' else None, return_value=info), \
                     patch('package_probe.time.monotonic', side_effect=lambda: job.now):
                    result = package_probe.execute(['owned-fixture'], {}, 1)
                self.assertEqual(result['cleanup']['status'], 'stopped', result)
                self.assertTrue(result['execution_error'])
                self.assertEqual(job.events[-1] if mode == 'launch-failed' else job.events[-3], ('close-job', 77))
                if mode == 'launch-failed':
                    self.assertNotIn('launcher_pid', result)
                else:
                    self.assertEqual(job.events[-2:], [('close-handle', 502), ('close-handle', 501)])

    def test_execute_waits_member_handles_before_closing_observation_job(self):
        job = self.FakeJob()
        info = SimpleNamespace(pid=101, process=501, thread=502)
        with patch('media_job.Job', return_value=job), \
             patch('media_job.launch_suspended', return_value=info), \
             patch('media_job.job_pids', return_value=[]) as named_query, \
             patch('package_probe.time.monotonic', side_effect=lambda: job.now):
            result = package_probe.execute(['owned-fixture'], {}, 1)
        self.assertEqual(result['cleanup']['status'], 'stopped', result)
        self.assertEqual(result['exit_code'], 0)
        self.assertEqual(job.member_waits, 2)
        self.assertLess(job.events.index(('wait', 1102)), job.events.index(('close-job', 77)))
        self.assertEqual(job.events[-3:], [('close-job', 77), ('close-handle', 502), ('close-handle', 501)])
        named_query.assert_not_called()


if __name__ == '__main__':
    unittest.main()
