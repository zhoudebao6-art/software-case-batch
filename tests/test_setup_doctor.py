import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
import test_caseflow


class SetupDoctorTests(unittest.TestCase):
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
            self.assertIn((root / 'rules/requirements.md').as_posix(), dest.read_text(encoding='utf-8'))
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


if __name__ == '__main__': unittest.main()
