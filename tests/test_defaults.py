"""New default/output propagation and general workflow contract regressions."""
import json
import os
import shutil
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch
import zipfile
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
from common import digest,read_json,write_json
import proflow
from audit_inheritance import validate as validate_audit

ROOT=Path(__file__).resolve().parents[1]

class DefaultPolicyTests(unittest.TestCase):
    def test_f_root_is_exact_in_code_local_and_example_config(self):
        self.assertEqual(proflow.DEFAULT_OUTPUT_ROOT,r'F:\研发图表')
        for name in ('local.config.json','local.config.example.json'):
            self.assertEqual(read_json(ROOT/name)['output_root'],r'F:\研发图表')
        with patch.dict(os.environ,{},clear=True):self.assertEqual(str(proflow.default_output_root()),r'F:\研发图表')
    def test_explicit_configured_root_is_honored_and_invalid_root_does_not_fallback(self):
        with tempfile.TemporaryDirectory() as tmp:
            target=Path(tmp)/'explicit-user-output'
            with patch.dict(os.environ,{'SCB_PRO_OUTPUT_ROOT':str(target)}):self.assertEqual(proflow.default_output_root(),target)
            with patch.dict(os.environ,{'SCB_PRO_OUTPUT_ROOT':'relative-output'}),self.assertRaises(ValueError):proflow.default_output_root()
    def test_explicit_output_is_required_and_command_creates_nothing_when_missing(self):
        with tempfile.TemporaryDirectory() as tmp:
            work=Path(tmp)/'case';work.mkdir()
            with self.assertRaises(SystemExit):proflow.main(['prepare','--workspace',str(work),'--title','设备业务','--source-docx',str(work/'source.docx')])
            self.assertFalse((work/'.product-v2').exists())
    def test_f_default_does_not_override_an_explicit_separate_workspace_delivery(self):
        with tempfile.TemporaryDirectory() as tmp:
            total=Path(tmp);work=total/'cases'/'other-case';work.mkdir(parents=True)
            output=total/'成品'/'batch'/'other-case';source=work/'input.docx'
            with zipfile.ZipFile(source,'w') as archive:archive.writestr('word/document.xml','<document/>')
            with patch.dict(os.environ,{'SCB_PRO_OUTPUT_ROOT':r'F:\研发图表'}):run=proflow.prepare(work,output,'对象业务管理',source)
            self.assertEqual(run['output'],str(output));self.assertTrue(output.exists())
            prompt=(work/'.product-v2/深化命令词.txt').read_text(encoding='utf8')
            self.assertIn(r'F:\研发图表',prompt);self.assertIn(str(output),prompt)
            for rule in ('以后每个授权案件','列表、详情、统计、摘要和日志','筛选','分页','迟到异步请求','不硬编码','不静默回D盘或桌面','缓存仍D:'):
                if rule=='缓存仍D:':self.assertIn(r'工具缓存仍D:\codex+',prompt)
                else:self.assertIn(rule,prompt)
    def test_environment_sets_only_process_roots_and_keeps_d_temp(self):
        if os.name!='nt':self.skipTest('Windows environment loader')
        shell=shutil.which('pwsh.exe') or shutil.which('pwsh')
        if not shell:raise ValueError('The configured PowerShell 7 launcher must be available; do not bypass Windows PowerShell 5.1 policy')
        script="$env:SCB_OUTPUT_ROOT='D:\\old-root'; . '"+str(ROOT/'Enter-Environment.ps1')+"'; [pscustomobject]@{pro=$env:SCB_PRO_OUTPUT_ROOT;legacy=$env:SCB_OUTPUT_ROOT;temp=$env:TEMP;tmp=$env:TMP;cache=$env:PIP_CACHE_DIR} | ConvertTo-Json -Compress"
        result=subprocess.run([shell,'-NoProfile','-NonInteractive','-Command',script],capture_output=True,text=True,encoding='utf-8',check=True)
        if result.stderr.strip():self.fail('Environment loader reported an execution error: '+result.stderr)
        observed=json.loads(result.stdout.lstrip('\ufeff'))
        self.assertEqual(observed['pro'],r'F:\研发图表');self.assertEqual(observed['legacy'],r'F:\研发图表')
        self.assertEqual(observed['temp'],r'D:\codex+\temp');self.assertEqual(observed['tmp'],observed['temp']);self.assertEqual(observed['cache'],r'D:\codex+\cache\pip')
    def test_original_snapshot_and_r1_record_stay_unchanged(self):
        result=validate_audit();self.assertEqual(result['sources'],26)
        prior=read_json(ROOT/'tests/fixtures/original-snapshot-baseline.json')
        migration=read_json(ROOT/'references/original-discovery-mapping.json')
        mapping={item['old']:item['new'] for item in migration['mappings']}
        for relative,sha in prior['files'].items():
            if relative.startswith('references/original/'):self.assertEqual(digest(ROOT/mapping.get(relative,relative)),sha)
            if relative=='references/original-sources.json':self.assertEqual(migration['prior_index_sha256'],sha)
        self.assertFalse(any(p.name in {'SKILL.md','AGENTS.md'} for p in (ROOT/'references/original').rglob('*')))
        matrix=read_json(ROOT/'references/inheritance-decisions.json')
        self.assertIn('U9',matrix['user_overrides']);self.assertEqual(len(matrix['rows']),78)
        root=next(row for row in matrix['rows'] if row['requirement']=='default-output-root')
        self.assertEqual(root['decision'],'partial-explicit-override');self.assertIn('F:\\研发图表',root['gap_and_fix'])

if __name__=='__main__':unittest.main()
