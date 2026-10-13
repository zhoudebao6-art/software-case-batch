"""Native math refusal boundaries without opening or closing user Office."""
from contextlib import redirect_stdout
import hashlib
import io
import json
from pathlib import Path
import socket
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch
import zipfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import native_math_worker as native
import render_native_math as render


def docx(path, colors=('', 'FF0000')):
    runs = []
    for index, color in enumerate(colors):
        properties = '<w:rPr><w:color w:val="' + color + '"/></w:rPr>' if color else ''
        runs.append('<m:oMath><m:r>' + properties + '<m:t>x' + str(index) + '=1</m:t></m:r></m:oMath>')
    xml = ('<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main" '
           'xmlns:m="http://schemas.openxmlformats.org/officeDocument/2006/math"><w:body>'
           + ''.join(runs) + '</w:body></w:document>')
    with zipfile.ZipFile(path, 'w') as package:
        package.writestr('word/document.xml', xml)
    return path


def row(pid, parent, ticks, profile, ports=(), name='soffice.bin'):
    return {'pid': pid, 'parent_pid': parent, 'created_ticks': ticks, 'name': name,
            'command': name + ' -env:UserInstallation=' + profile + ' --accept=socket,port=24444;',
            'ports': list(ports)}


class NativeMathRenderTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='native-math-unit-', dir=r'D:\codex+\temp')
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.source = docx(self.root / 'source.docx')
        self.office = self.root / 'office'
        self.office.mkdir()
        for name in ('soffice.com', 'python.exe'):
            (self.office / name).write_bytes(b'placeholder; never executed')
        self.raster = self.root / 'pdftoppm.exe'
        self.raster.write_bytes(b'placeholder; never executed')
        self.worker = self.root / 'worker.py'
        self.worker.write_text('# pinned fixture worker\n', encoding='utf-8')
        self.worker_hash = hashlib.sha256(self.worker.read_bytes()).hexdigest()
        self.source_hash = hashlib.sha256(self.source.read_bytes()).hexdigest()
        self.output = self.root / 'rendered'
        self.profile = 'file:///D:/codex+/temp/unique-test/profile'
        self.launcher = {'pid': 100, 'created_ticks': 1000}
        self.rows = [row(100, 1, 1000, self.profile, name='soffice.com'),
                     row(101, 100, 1001, self.profile, ports=(24444,))]

    def arguments(self):
        return ['--source', str(self.source), '--output', str(self.output),
                '--office-dir', str(self.office), '--pdftoppm', str(self.raster),
                '--worker-script', str(self.worker), '--worker-sha256', self.worker_hash,
                '--source-sha256', self.source_hash]

    def rejected_before_office(self, args, message):
        with patch.object(render.subprocess, 'Popen', side_effect=AssertionError('Office must not start')) as launch:
            with self.assertRaisesRegex(ValueError, message):
                render.main(args)
            launch.assert_not_called()
        self.assertFalse(self.output.exists())

    def test_whole_red_black_mapping_and_mixed_refusal(self):
        manifest = native.math_manifest(self.source)
        self.assertEqual([item['explicit_red'] for item in manifest], [False, True])
        self.assertEqual([item['text'] for item in manifest], ['x0=1', 'x1=1'])
        with zipfile.ZipFile(self.source) as package:
            xml = package.read('word/document.xml').decode('utf-8')
        xml = xml.replace('<m:t>x1=1</m:t></m:r>', '<m:t>x1=1</m:t></m:r><m:r><m:t>+2</m:t></m:r>')
        with zipfile.ZipFile(self.source, 'w') as package:
            package.writestr('word/document.xml', xml)
        arguments = self.arguments()
        arguments[arguments.index('--source-sha256') + 1] = hashlib.sha256(self.source.read_bytes()).hexdigest()
        self.rejected_before_office(arguments, 'Mixed math colors')

    def test_source_hash_drift_refuses_before_launch(self):
        with self.source.open('ab') as stream:
            stream.write(b'changed after pin')
        self.rejected_before_office(self.arguments(), 'Pinned source Word hash differs')

    def test_worker_hash_drift_refuses_before_launch(self):
        self.worker.write_text('# modified after pin\n', encoding='utf-8')
        self.rejected_before_office(self.arguments(), 'Pinned native-math worker hash differs')

    def test_external_worker_requires_pin(self):
        arguments = self.arguments()
        start = arguments.index('--worker-sha256')
        del arguments[start:start + 2]
        self.rejected_before_office(arguments, 'External worker override requires')

    def test_busy_actual_loopback_refuses_without_office(self):
        with socket.socket() as owned_socket:
            owned_socket.bind(('127.0.0.1', 0))
            owned_socket.listen()
            port = owned_socket.getsockname()[1]
            with patch.object(render.subprocess, 'Popen') as launch:
                with self.assertRaises(OSError):
                    render.main(self.arguments() + ['--port', str(port)])
                launch.assert_not_called()
            self.assertFalse(self.output.exists())

    def test_listener_requires_exact_tree_profile_and_creation(self):
        self.assertEqual(render.verified_listener(self.rows, self.launcher, self.profile, 24444)['pid'], 101)
        self.assertEqual(render.verified_listener(self.rows, {'pid': 100, 'created_ticks': 1007},
                                                 self.profile, 24444)['pid'], 101)
        foreign = row(200, 1, 1002, self.profile, ports=(24444,))
        for replacement in (foreign, row(101, 100, 1001, 'file:///other/profile', ports=(24444,)),
                            row(101, 100, 999, self.profile, ports=(24444,))):
            with self.subTest(replacement=replacement):
                with self.assertRaisesRegex(ValueError, 'not this held Office'):
                    render.verified_listener([self.rows[0], replacement], self.launcher, self.profile, 24444)
        with self.assertRaisesRegex(ValueError, 'PID was reused'):
            render.verified_listener(self.rows, {'pid': 100, 'created_ticks': 999}, self.profile, 24444)
        with self.assertRaisesRegex(ValueError, 'not unique'):
            render.verified_listener(self.rows + [foreign], self.launcher, self.profile, 24444)

    def test_internal_worker_refuses_foreign_listener_before_uno(self):
        foreign = [self.rows[0], row(201, 1, 1002, 'file:///other/profile', ports=(24444,))]
        with patch('process_guard.inventory', return_value=foreign):
            with self.assertRaisesRegex(ValueError, 'not this held Office'):
                native.worker(self.source, self.root, 24444, self.launcher,
                              {'pid': 201, 'created_ticks': 1002}, self.profile)

    def timeout_probe(self, stage, *, cleanup_fails=False):
        """Run the real parent failure/cleanup path with inert process fixtures."""
        self.output = self.root / (stage + ('-cleanup-fails' if cleanup_fails else '-closed'))
        partial_stdout = ('PARTIAL-' + stage.upper() + '-STDOUT\n').encode() + b'\xe4\xb8'
        partial_stderr = ('PARTIAL-' + stage.upper() + '-STDERR\n').encode() + b'\xff'
        state = {'rows': {}, 'terminated': [], 'calls': []}
        process = Mock(pid=100)
        process.poll.return_value = None
        process.wait.return_value = 0

        def launch(command, **kwargs):
            profile = next(value.split('=', 1)[1] for value in command
                           if value.startswith('-env:UserInstallation='))
            accept = next(value for value in command if value.startswith('--accept='))
            port = int(accept.split('port=', 1)[1].split(';', 1)[0])
            current = [row(100, 1, 1000, profile, name='soffice.com'),
                       row(101, 100, 1001, profile, ports=(port,)),
                       row(200, 1, 1002, 'file:///unrelated/profile')]
            for item in current:
                item['command'] = item['command'].replace('port=24444;', 'port=' + str(port) + ';')
                item['command_sha256'] = hashlib.sha256(item['command'].encode()).hexdigest()
                state['rows'][item['pid']] = item
            return process

        def run(command, **kwargs):
            current_stage = 'worker' if command[0] == str(self.office / 'python.exe') else 'raster'
            self.assertEqual(kwargs['timeout'], 150 if current_stage == 'worker' else 300)
            self.assertTrue(kwargs['capture_output'])
            self.assertEqual(kwargs['creationflags'], subprocess.CREATE_NO_WINDOW)
            state['calls'].append(current_stage)
            if current_stage == stage:
                raise subprocess.TimeoutExpired(command, kwargs['timeout'],
                                                output=partial_stdout, stderr=partial_stderr)
            self.assertEqual(current_stage, 'worker')
            mapping = {'source_sha256': self.source_hash, 'expected': [
                {'native_formula_before': 'x0=1', 'native_formula_after': 'x0=1', 'explicit_red': False},
                {'native_formula_before': 'x1=1', 'native_formula_after': 'color hex FF0000 { x1=1 }',
                 'explicit_red': True}]}
            (self.output / 'math-color-render-mapping.json').write_text(json.dumps(mapping), encoding='utf-8')
            (self.output / 'source.pdf').write_bytes(b'inert PDF fixture; never rendered')
            return subprocess.CompletedProcess(command, 0, 'WORKER-COMPLETED\n', '')

        def stop(saved):
            self.assertIn(saved['pid'], (100, 101))
            self.assertEqual(saved, state['rows'][saved['pid']])
            state['terminated'].append(saved['pid'])
            if cleanup_fails:
                raise OSError('fixture exact cleanup failed')
            del state['rows'][saved['pid']]

        summary = io.StringIO()
        with patch.object(render.subprocess, 'Popen', side_effect=launch), \
                patch.object(render.subprocess, 'run', side_effect=run), \
                patch('batch_control.identity', side_effect=lambda pid: self.launcher if pid in state['rows'] else None), \
                patch('process_guard.inventory', side_effect=lambda: list(state['rows'].values())), \
                patch('process_guard.terminate_exact', side_effect=stop), redirect_stdout(summary):
            self.assertEqual(render.main(self.arguments()), 2)
        report = json.loads((self.output / 'controlled-render.json').read_text(encoding='utf-8'))
        self.assertEqual(json.loads(summary.getvalue())['status'], report['status'])
        self.assertEqual(report['status'], 'cleanup_pending' if cleanup_fails else 'failed')
        self.assertIsNone(report[stage + '_exit_code'])
        self.assertTrue(report[stage + '_timed_out'])
        self.assertEqual(report[stage + '_timeout_seconds'], 150 if stage == 'worker' else 300)
        for stream, expected in (('stdout', partial_stdout), ('stderr', partial_stderr)):
            log = Path(report[stage + '_' + stream + '_log'])
            self.assertEqual(log.read_bytes(), expected)
            self.assertEqual(report[stage + '_' + stream + '_sha256'], hashlib.sha256(expected).hexdigest())
        combined = partial_stdout + b'\n' + partial_stderr
        self.assertEqual(Path(report[stage + '_log']).read_bytes(), combined)
        self.assertEqual(report[stage + '_log_sha256'], hashlib.sha256(combined).hexdigest())
        self.assertTrue(report['source_unchanged'])
        self.assertEqual(report['shadow_sha256'], self.source_hash)
        self.assertIn(200, state['rows'])
        if cleanup_fails:
            self.assertEqual(report['cleanup_error'], 'fixture exact cleanup failed')
            self.assertEqual(state['terminated'], [101])
        else:
            self.assertEqual(state['terminated'], [101, 100])
            self.assertEqual(report['remaining'], [])
            self.assertEqual(report['ports_still_listening'], [])
            self.assertFalse(report['launcher_still_alive'])
        return report, state, process

    def test_worker_timeout_retains_raw_diagnostics_and_cleanup_status(self):
        for cleanup_fails in (False, True):
            with self.subTest(cleanup_fails=cleanup_fails):
                report, state, process = self.timeout_probe('worker', cleanup_fails=cleanup_fails)
                self.assertEqual(state['calls'], ['worker'])
                self.assertNotIn('raster_exit_code', report)
                process.wait.assert_not_called()

    def test_raster_timeout_retains_raw_diagnostics_and_cleanup_status(self):
        for cleanup_fails in (False, True):
            with self.subTest(cleanup_fails=cleanup_fails):
                report, state, process = self.timeout_probe('raster', cleanup_fails=cleanup_fails)
                self.assertEqual(state['calls'], ['worker', 'raster'])
                self.assertEqual(report['worker_exit_code'], 0)
                self.assertFalse(report['worker_timed_out'])
                worker_log = Path(report['worker_log'])
                self.assertEqual(worker_log.read_bytes(), b'WORKER-COMPLETED\n\n')
                self.assertEqual(report['worker_log_sha256'], hashlib.sha256(worker_log.read_bytes()).hexdigest())
                process.wait.assert_called_once_with(timeout=20)


if __name__ == '__main__':
    unittest.main()
