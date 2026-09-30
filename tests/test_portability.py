"""Portable paths and the registered new pipeline must work outside repo cwd."""
import json
import os
import tempfile
import unittest
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
        self.assertEqual(loaded['_root'], self.root / 'cases')
        self.assertEqual(loaded['runner']['workspace_root'], str(self.root / 'cases'))
        self.assertEqual(loaded['runtime']['python'], str(self.root / 'tools/python.exe'))
        self.assertEqual(loaded['standards'], str(self.root / 'rules/requirements.md'))
        self.assertEqual(loaded['runner']['protected_source_roots'], [str(self.root / 'protected')])

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


if __name__ == '__main__':
    unittest.main()
