import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import runtime_paths as paths


class RuntimePathsTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.cache = self.root / 'selected-cache'
        (self.cache / 'temp').mkdir(parents=True)
        self.env = {'SCB_PRO_CACHE_ROOT':str(self.cache), **{k:str(self.cache/'temp') for k in ('TEMP','TMP','TMPDIR')}}

    def test_configured_drive_and_temp_are_used(self):
        with patch.dict(os.environ, self.env):
            self.assertEqual(paths.checked_temp_root(), self.cache/'temp')

    def test_mismatched_or_missing_temp_fails(self):
        for name in ('TEMP','TMP','TMPDIR'):
            for value in ('', str(self.root/'wrong')):
                with self.subTest(name=name, value=value), patch.dict(os.environ, {**self.env,name:value}):
                    with self.assertRaises(ValueError): paths.checked_temp_root()

    def test_relative_cache_root_fails(self):
        with patch.dict(os.environ, {**self.env,'SCB_PRO_CACHE_ROOT':'relative'}):
            with self.assertRaises(ValueError): paths.cache_root()

    def test_missing_directory_fails(self):
        other=self.root/'absent'
        with patch.dict(os.environ, {'SCB_PRO_CACHE_ROOT':str(other), **{k:str(other/'temp') for k in ('TEMP','TMP','TMPDIR')}}):
            with self.assertRaises(ValueError): paths.checked_temp_root()

    def test_config_fallback_and_environment_precedence(self):
        scripts=self.root/'skill'/'scripts'; scripts.mkdir(parents=True)
        (scripts.parent/'local.config.json').write_text(json.dumps({'cache_root':str(self.root/'configured')}))
        with patch.object(paths,'__file__',str(scripts/'runtime_paths.py')):
            with patch.dict(os.environ, {'SCB_PRO_CACHE_ROOT':''}):
                self.assertEqual(paths.cache_root(),self.root/'configured')
            with patch.dict(os.environ,self.env):
                self.assertEqual(paths.cache_root(),self.cache)


if __name__ == '__main__': unittest.main()
