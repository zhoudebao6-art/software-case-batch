"""Read-I/O and stdout regressions; no claim of production throughput."""
import io,json,sys,tempfile,unittest,shutil
from collections import Counter
from contextlib import redirect_stdout,redirect_stderr
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
from check_io import CheckedHashes,compact_result
from common import digest
from contracts import construction_checks
from proflow import main
import test_construction_progress as fixtures
import test_web_contract as web_fixtures


class HashTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.path=Path(self.temp.name)/'input';self.path.write_bytes(b'one')
    def tearDown(self):self.temp.cleanup()
    def test_read_once_and_new_invocation_hashes_again(self):
        with patch(__name__+'.digest',wraps=digest) as reader:
            h=CheckedHashes(reader);self.assertEqual(h(self.path),h(self.path));h.finish()
            self.assertEqual(reader.call_count,1)
            self.path.write_bytes(b'next value')
            self.assertNotEqual(CheckedHashes(reader)(self.path),h.values[next(iter(h.values))][2])
            self.assertEqual(reader.call_count,2)
    def test_changes_between_uses_or_before_completion_rejected(self):
        for finish in (False,True):
            h=CheckedHashes(digest);h(self.path);self.path.write_bytes(self.path.read_bytes()+b'x')
            with self.assertRaisesRegex(ValueError,'changed'): h.finish() if finish else h(self.path)
    def test_change_during_read_rejected(self):
        def changing(p):
            result=digest(p);p.write_bytes(b'longer changed file');return result
        with self.assertRaisesRegex(ValueError,'while being hashed'):CheckedHashes(changing)(self.path)
    def test_deleted_file_cannot_use_stored_hash(self):
        h=CheckedHashes(digest);h(self.path);self.path.unlink()
        with self.assertRaises(OSError):h.finish()


class ConstructionIOTests(unittest.TestCase):
    def setUp(self):self.f=fixtures.DependencyFixture();self.f.setUp()
    def tearDown(self):self.f.tearDown()
    def test_dependencies_deduplicated_without_changing_result(self):
        seen=Counter()
        def read(p):seen[str(p)]+=1;return digest(p)
        with patch('contracts.digest',side_effect=read):value=self.f.gate()
        self.assertTrue(seen);self.assertEqual(max(seen.values()),1)
        self.assertEqual(value['status'],'ready');self.assertEqual(set(value['checks']),fixtures.CONSTRUCTION_KINDS)
    def test_changed_dependency_on_next_call_still_fails(self):
        self.f.gate();self.f.file('app.py','changed implementation')
        with self.assertRaises(ValueError):self.f.gate()
    def test_compact_cli_runs_full_gate_and_default_output_unchanged(self):
        original=self.f.gate();before=self.f.checks_path.read_bytes()
        args=['check-build','--workspace',str(self.f.work),'--plan',str(self.f.plan)]
        raw=io.StringIO()
        with redirect_stdout(raw):code=main(args)
        self.assertEqual(code,0);self.assertEqual(json.loads(raw.getvalue()),original)
        out=io.StringIO()
        with redirect_stdout(out):code=main(args+['--compact'])
        summary=json.loads(out.getvalue());self.assertEqual(code,0)
        self.assertEqual(summary['result']['status'],'ready')
        self.assertEqual(summary['result']['implementation_hashes']['omitted_items'],len(original['implementation_hashes']))
        self.assertEqual(before,self.f.checks_path.read_bytes())
        self.f.file('app.py','changed implementation')
        with redirect_stderr(io.StringIO()):self.assertEqual(main(args+['--compact']),2)
    def test_snapshot_change_during_web_check_fails(self):
        def mutate(*a,**kwargs):self.f.file('app.py','changed during web validation');return {}
        with patch('web_contract.validate_web_experience',side_effect=mutate):
            with self.assertRaisesRegex(ValueError,'before check completed'):self.f.gate()

    def test_json_read_before_web_cannot_bind_a_later_changed_file(self):
        for path in (self.f.checks_path,self.f.manifest,self.f.plan):
            before=path.read_bytes()
            def mutate(*args,**kwargs):path.write_bytes(before+b' ');return {}
            try:
                with patch('web_contract.validate_web_experience',side_effect=mutate):
                    with self.assertRaisesRegex(ValueError,'changed'):self.f.gate()
            finally:path.write_bytes(before)

    def test_real_web_path_uses_the_same_invocation_hashes(self):
        w=web_fixtures.WebContractTests();w.setUp()
        try:
            names=['mapping.json','execution.log','screen.png','browser-report.json']
            w.report.update(run_id=self.f.run['run_id'],source_docx_sha256=self.f.run['source_docx_sha256'])
            w.save()
            for name in names:shutil.copy2(w.work/name,self.f.work/name)
            self.f.run['web_experience_policy']='case-workflow-v1'
            self.f.checks['web_experience']=w.web
            self.f.checks['checks']['browser']['input_files'].update({name:digest(self.f.work/name) for name in names})
            self.f.checks['checks']['browser']['input_files']['app.py']=digest(self.f.work/'app.py')
            self.f.save_checks();seen=Counter()
            def reader(path):seen[str(path)]+=1;return digest(path)
            with patch('contracts.digest',side_effect=reader),patch('web_contract.digest',side_effect=AssertionError('must share reader')):
                value=self.f.gate()
            self.assertEqual(value['web_experience']['status'],'ready')
            self.assertEqual(max(seen.values()),1)
        finally:w.tearDown()


class SummaryTests(unittest.TestCase):
    def test_states_errors_and_next_actions_are_retained(self):
        value={'steps':{'source':{'state':'stale','changed_dependencies':['a']}},
               'errors':[{'input_files':{'bad':'value'},'reason':'must repair'}],
               'next_actions':['repair-source'],'implementation_hashes':{'x':'0'*64},
               'review_pointers':[{'path':'original-proof','sha256':'1'*64,'reviewed_evidence':['E1','E2']}]}
        encoded=json.dumps(value);r=compact_result(value,'status','W',evidence='evidence.json')
        self.assertEqual(r['result']['errors'],value['errors']);self.assertEqual(r['result']['steps'],value['steps'])
        self.assertEqual(r['result']['next_actions'],value['next_actions']);self.assertEqual(json.dumps(value),encoded)
        self.assertEqual(r['detail_argv'][-2:],['--evidence','evidence.json'])
        self.assertEqual(r['result']['review_pointers'][0]['path'],'original-proof')
    def test_large_dependency_maps_shrink_stdout_without_an_evidence_claim(self):
        value={'status':'ready','checks':{k:{'log':k+'.log','input_files':{str(i):'a'*64 for i in range(1000)}} for k in ['algorithm','api','browser']}}
        r=compact_result(value,'check-build','W')
        self.assertLess(len(json.dumps(r)),len(json.dumps(value))/20)
        self.assertEqual(r['output_mode'],'compact-not-proof')

if __name__=='__main__':unittest.main()
