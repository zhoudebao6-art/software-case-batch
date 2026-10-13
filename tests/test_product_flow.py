import csv
import hashlib
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
import zipfile

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
from common import digest, inside, forbidden, read_json
from proflow import prepare, clean_csv, pack_source, scan_delivery, preserve_draft, SYSTEM
from process_guard import command_owned, protected, same

class FlowTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name)
        self.work=self.root/'case';self.work.mkdir();self.out=self.root/'delivery'
        self.source=self.work/'技术说明（原中文）.docx'
        with zipfile.ZipFile(self.source,'w') as z:
            z.writestr('word/document.xml','<document/>')
        prepare(self.work,self.out,'设备运行管理',self.source)
    def tearDown(self): self.tmp.cleanup()
    def manifest(self,name,value):
        p=self.work/(name+'.json');p.write_text(json.dumps(value,ensure_ascii=False),encoding='utf8');return p
    def csv(self,name,rows,encoding='utf-8-sig',delimiter=','):
        p=self.work/name;p.parent.mkdir(parents=True,exist_ok=True)
        with p.open('w',encoding=encoding,newline='') as f:csv.writer(f,delimiter=delimiter).writerows(rows)
        return p
    def clean(self,entries):return clean_csv(self.work,self.out,self.manifest('keep',{'files':entries}))
    def entry(self,path,**kwargs):return {'path':path,'reason':'业务运行记录','primary_key':['编号'],**kwargs}
    def test_prepare_is_idempotent_and_preserves_output(self):
        before=digest(self.work/'.product-v2/run.json');prepare(self.work,self.out,'设备运行管理',self.source)
        self.assertEqual(before,digest(self.work/'.product-v2/run.json'))
        with self.assertRaises(ValueError):prepare(self.work,self.root/'other','设备运行管理',self.source)
    def test_preexisting_output_refused(self):
        other=self.root/'other';other.mkdir()
        with self.assertRaises(ValueError):prepare(other,self.out,'任务管理',self.source)
    def test_overlapping_output_refused(self):
        with self.assertRaises(ValueError):prepare(self.work,self.work/'delivery','任务管理',self.source)
    def test_prompt_embeds_exact_paths_and_latest_layout(self):
        text=(self.work/'.product-v2/深化命令词.txt').read_text(encoding='utf8')
        self.assertIn(str(self.out/SYSTEM/'数据'),text);self.assertIn(str(self.out/SYSTEM/'项目源码.zip'),text)
    def test_clean_drops_whole_metadata_columns_preserves_other_cells(self):
        src=self.csv('full.csv',[['编号','值','生成数据',' 数据 来源 ','生成时间'],['001','1.2300','是','输入','2026-10-12'],['002','带,逗号\n换行','否','其他','']])
        before=digest(src);r=self.clean([self.entry('full.csv',min_rows=2)])
        with (self.out/SYSTEM/'数据/full.csv').open(encoding='utf-8-sig',newline='') as f:rows=list(csv.reader(f))
        self.assertEqual(rows,[['编号','值','生成时间'],['001','1.2300','2026-10-12'],['002','带,逗号\n换行','']])
        self.assertEqual(before,digest(src));self.assertEqual(r['files'][0]['rows'],2)
    def test_only_important_allowlist_is_exported(self):
        self.csv('main.csv',[['编号','值'],['1','2']]);self.csv('debug.csv',[['编号'],['2']]);(self.work/'data.json').write_text('{}')
        self.clean([self.entry('main.csv')]);self.assertEqual([p.name for p in (self.out/SYSTEM/'数据').iterdir()],['main.csv'])
    def test_english_column_aliases_removed(self):
        self.csv('a.csv',[['编号','data_source','is_generated','值'],['1','x','true','8']]);self.clean([self.entry('a.csv')])
        self.assertNotIn('data_source',(self.out/SYSTEM/'数据/a.csv').read_text(encoding='utf-8-sig'))
    def test_gb18030_and_semicolon(self):
        self.csv('a.csv',[['编号','名称'],['1','运行']],encoding='gb18030',delimiter=';')
        self.clean([self.entry('a.csv',encoding='gb18030',delimiter=';')]);self.assertTrue((self.out/SYSTEM/'数据/a.csv').read_bytes().startswith(b'\xef\xbb\xbf'))
    def test_failure_does_not_publish_partial_data(self):
        self.csv('a.csv',[['编号','值'],['1','模拟']])
        with self.assertRaises(ValueError):self.clean([self.entry('a.csv')])
        self.assertFalse((self.out/SYSTEM/'数据').exists());self.assertEqual(list((self.out/SYSTEM).iterdir()),[])
    def test_duplicate_keys_rejected(self):
        self.csv('a.csv',[['编号','值'],['1','2'],['1','3']])
        with self.assertRaises(ValueError):self.clean([self.entry('a.csv')])
    def test_duplicate_headers_rejected(self):
        self.csv('a.csv',[['编号','值',' 值 '],['1','2','3']])
        with self.assertRaises(ValueError):self.clean([self.entry('a.csv')])
    def test_ragged_rows_rejected(self):
        self.csv('a.csv',[['编号','值'],['1']])
        with self.assertRaises(ValueError):self.clean([self.entry('a.csv')])
    def test_insufficient_rows_rejected(self):
        self.csv('a.csv',[['编号'],['1']])
        with self.assertRaises(ValueError):self.clean([self.entry('a.csv',min_rows=100)])
    def test_path_escape_rejected(self):
        (self.root/'secret.csv').write_text('编号\n1')
        with self.assertRaises(ValueError):self.clean([self.entry('../secret.csv')])
    def test_existing_data_preserved(self):
        self.csv('a.csv',[['编号'],['1']]);self.clean([self.entry('a.csv')]);before=digest(self.out/SYSTEM/'数据/a.csv')
        with self.assertRaises(ValueError):self.clean([self.entry('a.csv')])
        self.assertEqual(before,digest(self.out/SYSTEM/'数据/a.csv'))
    def test_pack_excludes_readmes_and_analysis_but_keeps_business_parser(self):
        files={'app/main.py':'print(1)','app/parser.py':'def parse(value): return value',
               'README.md':'keep locally','app/ReadMe.txt':'keep locally',
               'docx-extract/document.xml':'internal','evidence/log.json':'{}',
               'extracted_text.txt':'internal','app/.env':'secret','app/.env.example':'PORT=8000'}
        for rel,text in files.items():
            p=self.work/rel;p.parent.mkdir(parents=True,exist_ok=True);p.write_text(text,encoding='utf8')
        before={r:digest(self.work/r) for r in files}
        receipt=pack_source(self.work,self.out,self.manifest('package',{'files':list(files)}))
        with zipfile.ZipFile(self.out/SYSTEM/'项目源码.zip') as z:self.assertEqual(set(z.namelist()),{'app/main.py','app/parser.py','app/.env.example'})
        self.assertEqual(before,{r:digest(self.work/r) for r in files});self.assertEqual(len(receipt['excluded']),6)
    def test_archive_unicode_escaped_word_detected(self):
        p=self.work/'app.py';p.write_text(r'x="\u6a21\u62df"',encoding='utf8')
        with self.assertRaisesRegex(ValueError,'semantic fix before packing'):
            pack_source(self.work,self.out,self.manifest('package',{'files':['app.py']}))
        self.assertFalse((self.out/'模拟系统/项目源码.zip').exists())
        (self.out/'模拟系统').mkdir(exist_ok=True)
        with zipfile.ZipFile(self.out/'模拟系统/项目源码.zip','w') as archive:
            archive.writestr('app.py',(self.work/'app.py').read_bytes())
        self.assertFalse(scan_delivery(self.out)['passed'])
    def test_fixed_container_name_allowed(self):
        (self.work/'app.py').write_text('print("运行")',encoding='utf8')
        pack_source(self.work,self.out,self.manifest('package',{'files':['app.py']}))
        self.assertTrue(scan_delivery(self.out)['passed'])
    def test_readme_in_handmade_archive_is_blocked(self):
        target=self.out/SYSTEM;target.mkdir()
        with zipfile.ZipFile(target/'项目源码.zip','w') as z:z.writestr('nested/README.MD','text')
        self.assertFalse(scan_delivery(self.out)['passed'])
    def test_nested_archive_and_traversal_are_blocked(self):
        target=self.out/SYSTEM;target.mkdir()
        with zipfile.ZipFile(target/'项目源码.zip','w') as z:z.writestr('../a.py','print(1)');z.writestr('payload.zip','bytes')
        self.assertEqual(len(scan_delivery(self.out)['hits']),2)
    def test_preserve_draft_retains_identical_bytes_for_retry(self):
        self.csv('a.csv',[['编号'],['1']]);self.clean([self.entry('a.csv')]);before=digest(self.out/SYSTEM/'数据/a.csv')
        r=preserve_draft(self.work,self.out,'data');self.assertEqual(before,digest(Path(r['preserved'])/'a.csv'))
        self.clean([self.entry('a.csv')]);self.assertTrue((self.out/SYSTEM/'数据/a.csv').exists())
    def test_no_generic_runtime_ownership(self):
        self.assertFalse(command_owned(self.work,'node.exe server.js'))
        self.assertFalse(command_owned(self.work,str(self.work)+'-other/server.py'))
        self.assertTrue(command_owned(self.work,'python.exe "'+str(self.work/'server.py')+'"'))
    def test_codex_and_ancestors_protected(self):
        self.assertTrue(protected({'name':'Codex.exe','command':'abc','pid':3},set()))
        self.assertTrue(protected({'name':'python.exe','command':'abc','pid':3},{3}))
    def test_reused_pid_not_same_process(self):
        self.assertFalse(same({'pid':1,'created_ticks':2,'command_sha256':'x'},{'pid':1,'created_ticks':3,'command_sha256':'x'}))

if __name__=='__main__':unittest.main()
