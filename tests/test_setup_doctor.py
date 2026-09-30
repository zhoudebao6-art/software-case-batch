import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
import test_caseflow


class SetupDoctorTests(unittest.TestCase):
    def test_recording_default_is_two_slots_with_memory_guard(self):
        from caseflow import config_at
        root = Path(__file__).resolve().parents[1]
        cfg = config_at(root / 'config.json')
        self.assertEqual(cfg['execution']['recording_concurrency'], 2)
        self.assertGreaterEqual(cfg['execution']['recording_min_available_mb'], 1024)
        self.assertGreaterEqual(cfg['execution']['recording_reserve_mb'], 512)

    def test_setup_never_overwrites_existing_local_configuration(self):
        from portable_setup import write_config
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'config.json'
            path.write_bytes(b'keep-local-config')
            with self.assertRaises(FileExistsError): write_config(path, {'new': True})
            self.assertEqual(path.read_bytes(), b'keep-local-config')

    def test_installed_skill_rebinds_links_to_clone_location(self):
        from portable_setup import install_skill
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / 'repo'; (root / 'skill').mkdir(parents=True)
            (root / 'skill/SKILL.md').write_text('---\nname: software-case-batch\ndescription: test\n---\n[Rules](../rules/requirements.md)\n', encoding='utf-8')
            dest = install_skill(root, Path(tmp) / 'codex')
            self.assertIn((root.resolve() / 'rules/requirements.md').as_posix(), dest.read_text(encoding='utf-8'))
            self.assertNotIn('../rules/', dest.read_text(encoding='utf-8'))

    def test_missing_runtime_blocks_before_any_subprocess(self):
        from runtime_doctor import check_environment
        with patch('runtime_doctor.subprocess.run') as execute:
            report = check_environment({'runtime': {}, 'runner': {}}, check_cli=False)
        self.assertFalse(report['ok'])
        self.assertTrue(any('python' in e for e in report['errors']))
        execute.assert_not_called()

    def test_policy_and_memory_failures_are_distinct(self):
        from runtime_doctor import failure_kind
        self.assertEqual(failure_kind('Rejected: blocked by policy'), 'policy_denied')
        self.assertEqual(failure_kind('memory allocation failed'), 'memory_exhausted')
        self.assertEqual(failure_kind('PermissionError: Access denied'), 'permission_or_lock')

    def test_low_memory_is_reported_before_model_dispatch(self):
        from runtime_doctor import recording_memory_requirement_mb, check_environment
        from unittest.mock import patch
        cfg = {'runtime': {}, 'runner': {}, 'execution': {
            'recording_concurrency': 2,
            'recording_min_available_mb': 4096,
            'recording_reserve_mb': 2048,
        }}
        self.assertEqual(recording_memory_requirement_mb(cfg), 6144)
        with patch('runtime_doctor.available_memory_mb', return_value=2048):
            report = check_environment(cfg, check_cli=False)
        self.assertFalse(report['ok'])
        self.assertTrue(any('recording' in e.lower() and 'memory' in e.lower() for e in report['errors']))


if __name__ == '__main__': unittest.main()
