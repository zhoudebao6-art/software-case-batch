"""Exercise the real PowerShell entry in isolated directories, without installs."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest


@unittest.skipUnless(os.name == 'nt', 'Windows environment entry')
class EnvironmentEntryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.entry = self.root / 'Enter-Environment.ps1'
        shutil.copy2(Path(__file__).resolve().parents[1] / 'Enter-Environment.ps1', self.entry)
        self.settings = {'python': 'retained-python', 'node': 'retained-node',
                         'playwright_module': 'retained-playwright', 'ffmpeg': 'retained-ffmpeg',
                         'ffprobe': 'retained-ffprobe', 'output_root': str(self.root / 'delivery'),
                         'cache_root': str(self.root / 'configured-cache')}
        self.shell = shutil.which('pwsh') or str(Path(os.environ['SystemRoot']) / 'System32/WindowsPowerShell/v1.0/powershell.exe')
        self.probe = self.root / 'probe.ps1'
        self.probe.write_text(". (Join-Path $PSScriptRoot 'Enter-Environment.ps1')\n"
            "@{cache=$env:SCB_PRO_CACHE_ROOT; temp=$env:TEMP; tmp=$env:TMP; tmpdir=$env:TMPDIR; "
            "nodecache=$env:NODE_COMPILE_CACHE; browsers=$env:PLAYWRIGHT_BROWSERS_PATH; "
            "python=$env:SCB_PRO_PYTHON; node=$env:SCB_PRO_NODE; output=$env:SCB_PRO_OUTPUT_ROOT} | ConvertTo-Json -Compress\n",
            encoding='utf-8-sig')

    def tearDown(self):
        self.temp.cleanup()

    def invoke(self, overrides=None):
        config = self.root / 'local.config.json'
        config.write_text(json.dumps(self.settings), encoding='utf-8-sig')
        before = config.read_bytes()
        env = os.environ.copy()
        env.pop('SCB_PRO_CACHE_ROOT', None)
        env['PLAYWRIGHT_BROWSERS_PATH'] = 'existing-browser-installation'
        env.update(overrides or {})
        result = subprocess.run([self.shell, '-NoProfile', '-NonInteractive', '-File', str(self.probe)],
                                env=env, capture_output=True, text=True, timeout=20)
        self.assertEqual(config.read_bytes(), before, 'Entry must not rewrite local config')
        return result

    def test_configured_cache_keeps_installed_dependencies_and_output(self):
        result = self.invoke()
        self.assertEqual(result.returncode, 0, result.stderr)
        facts = json.loads(result.stdout)
        self.assertEqual(facts['temp'], str(self.root / 'configured-cache/temp'))
        self.assertEqual(facts['tmp'], facts['temp'])
        self.assertEqual(facts['tmpdir'], facts['temp'])
        self.assertEqual(facts['nodecache'], str(self.root / 'configured-cache/cache/node-compile-cache'))
        self.assertEqual(facts['browsers'], 'existing-browser-installation')
        self.assertEqual(facts['python'], 'retained-python')
        self.assertEqual(facts['node'], 'retained-node')
        self.assertEqual(facts['output'], str(self.root / 'delivery'))

    def test_explicit_process_cache_overrides_old_config_without_changing_it(self):
        selected = str(self.root / 'caller-cache')
        result = self.invoke({'SCB_PRO_CACHE_ROOT': selected})
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout)['cache'], selected)
        self.assertFalse((self.root / 'configured-cache').exists())

    def test_browser_configuration_is_independent_from_regenerable_cache(self):
        self.settings['playwright_browsers_path'] = 'configured-browser-installation'
        result = self.invoke()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout)['browsers'], 'configured-browser-installation')

    def test_relative_or_drive_relative_cache_fails_before_creating_directories(self):
        for bad in ['relative-cache', 'E:relative-cache', '\\root-relative-cache']:
            self.settings['cache_root'] = bad
            result = self.invoke()
            self.assertNotEqual(result.returncode, 0)
            self.assertIn('cache_root must be an explicit absolute directory', result.stderr)
        self.assertFalse((self.root / 'configured-cache').exists())

    @unittest.skipUnless(Path('E:/').exists(), 'Local E-drive default')
    def test_default_is_E_even_when_entry_is_loaded_through_another_path(self):
        self.settings.pop('cache_root')
        result = self.invoke()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout)['temp'], 'E:\\codex+\\temp')


if __name__ == '__main__':
    unittest.main()
