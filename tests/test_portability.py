"""Portable paths and the registered new pipeline must work outside repo cwd."""
import json
import os
import tempfile
import unittest
from unittest.mock import patch
from types import SimpleNamespace
from pathlib import Path

import test_caseflow as fixtures
import caseflow as flow
from controlled_evidence import registered_pipeline_profile


class PortableConfigTests(unittest.TestCase):
    setUp = fixtures.CaseflowTests.setUp
    tearDown = fixtures.CaseflowTests.tearDown

    def test_relative_paths_resolve_against_config_not_shell_cwd(self):
        cfg = flow.read_json(self.config_path)
        cfg['runner'].update(workspace_root='cases', protected_source_roots=['protected'])
        cfg['runtime'] = {'python': 'tools/python.exe', 'node_modules': 'node_modules'}
        cfg['standards'] = 'rules/requirements.md'
        flow.atomic_json(self.config_path, cfg)
        loaded = flow.config_at(self.config_path)
        root = self.root.resolve()
        self.assertEqual(loaded['_root'], root / 'cases')
        self.assertEqual(loaded['runner']['workspace_root'], str(root / 'cases'))
        self.assertEqual(loaded['runtime']['python'], str(root / 'tools/python.exe'))
        self.assertEqual(loaded['standards'], str(root / 'rules/requirements.md'))
        self.assertEqual(loaded['runner']['protected_source_roots'], [str(root / 'protected')])

    def test_new_profile_is_accepted_from_registration_not_worker_label(self):
        workspace = self.root / 'cases'
        case = workspace / '2026-09' / 'registered'
        case.mkdir(parents=True)
        folder = workspace / '.batches' / 'batch'
        folder.mkdir(parents=True)
        entry = {'case_id': 'case', 'workspace_relative': '2026-09/registered',
                 'workspace_name': 'registered', 'source_sha256': 'source'}
        flow.atomic_json(folder / 'manifest.json', {
            'pipeline_profile': 'deliverable-first-v1', 'cases': [entry]})
        manifest = {'case_id': 'case', 'source_sha256': 'source', 'pipeline_profile': 'legacy'}
        self.assertEqual(registered_pipeline_profile(case, manifest, self.cfg), 'deliverable-first-v1')
        manifest['source_sha256'] = 'different'
        self.assertIsNone(registered_pipeline_profile(case, manifest, self.cfg))


@unittest.skipUnless(os.name == 'nt', 'Windows short path regression')
class WindowsShortPathTests(unittest.TestCase):
    def setUp(self):
        import ctypes
        self.temp = tempfile.TemporaryDirectory(prefix='caseflow-long-directory-')
        self.addCleanup(self.temp.cleanup)
        self.long = Path(self.temp.name).resolve()
        buffer = ctypes.create_unicode_buffer(32768)
        size = ctypes.windll.kernel32.GetShortPathNameW(str(self.long), buffer, len(buffer))
        self.assertGreater(size, 0)
        self.short = Path(buffer.value)
        if self.short == self.long:
            self.skipTest('Filesystem does not provide a short alias')

    def test_short_path_snapshot_and_capture_are_plain_directories(self):
        from capture_runner import local_file
        (self.long / 'src').mkdir()
        (self.long / 'src/app.py').write_text('pass', encoding='utf-8')
        flow.prepare_control_directories(self.short)
        files = flow.snapshot(self.short, video=False)
        self.assertIn('src/app.py', files)
        self.assertEqual(local_file(self.short, 'src/app.py').read_text(), 'pass')

    def test_short_path_output_has_same_identity_as_long_source(self):
        flow.validate_output_root({'source_root': str(self.long),
                                   'output_root': str(self.short / '_成品')})


class PathLinkGuardTests(unittest.TestCase):
    def test_reparse_point_in_ancestor_is_refused(self):
        from path_safety import has_path_link
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve()
            actual_lstat = Path.lstat
            def lstat(path):
                if path == root:
                    return SimpleNamespace(st_mode=0, st_file_attributes=0x400)
                return actual_lstat(path)
            with patch.object(Path, 'lstat', lstat):
                self.assertTrue(has_path_link(root / 'not-created-yet'))


if __name__ == '__main__':
    unittest.main()
