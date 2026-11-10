"""Real contract/ZIP behavior on synthetic fixtures; no production acceptance claims."""
import copy
import sys
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
from common import read_json,write_json,digest,delivery_paths
from source_delivery import MAIN_CODE_POLICY, DIRECTORY_POLICY, RETAINED_DIRECTORY_POLICY, RUNTIME_CACHE_POLICY
import proflow
import package_probe
import review_packet
import test_product_flow as flow
import test_review_packet as packet
import test_contracts as contracts
import test_simplified_closure as closure
import test_construction_progress as progress

class MainCodeTests(unittest.TestCase):
    def fixture(self,cls):
        f=cls();f.setUp()
        self.addCleanup(f.doCleanups)
        self.addCleanup(f.tearDown)
        return f
    def enable(self,f):
        p=f.work/'.product-v2/run.json';r=read_json(p);r['source_delivery_policy']=MAIN_CODE_POLICY;write_json(p,r)
        if hasattr(f,'run'):f.run=r
        return r
    def test_new_prepare_freezes_policy_and_prompt_without_startup(self):
        f=self.fixture(flow.FlowTests)
        work=f.root/'new';work.mkdir()
        run=proflow.prepare(work,f.root/'new-output','业务控制',f.source)
        self.assertEqual(run['source_delivery_policy'],RUNTIME_CACHE_POLICY)
        self.assertEqual(run['system_diagram_policy'],'source-system-png-v2')
        before=digest(work/'.product-v2/run.json')
        proflow.prepare(work,f.root/'new-output','业务控制',f.source)
        self.assertEqual(before,digest(work/'.product-v2/run.json'))
        prompt=(work/'.product-v2/深化命令词.txt').read_text(encoding='utf8')
        for word in ('source_roots','delivery_files','完整','clean-source-cache-directory-v4'):self.assertIn(word,prompt)
        self.assertIn('manifest.files',prompt)
        self.assertIn('原draft自动将它们纳入必读ID',prompt)
        for word in ('当前包启动','真实包启动','压缩包不得依赖被排除文件或旧绝对路径'):self.assertNotIn(word,prompt)
        self.assertNotIn('source_delivery_policy',read_json(f.work/'.product-v2/run.json'))
    def test_selected_complete_modules_pack_without_runtime_dependencies(self):
        f=self.fixture(flow.FlowTests);self.enable(f)
        files={'backend/service.py':'def calculate(records):\n    return sum(records)\n',
               'backend/repository.py':'class Repository:\n    def save(self, value):\n        self.value = value\n',
               'web/app.js':'export const load = () => fetch("/api/items");',
               'requirements.txt':'not-installed-package==0.0.1',
               'start.ps1':'throw "must not run"','LICENSE':'Permission notice'}
        for name,value in files.items():
            p=f.work/name;p.parent.mkdir(parents=True,exist_ok=True);p.write_text(value,encoding='utf8')
        selected=['backend/service.py','backend/repository.py','web/app.js']
        manifest=f.manifest('source',{'files':list(files),'delivery_files':selected})
        with patch('subprocess.Popen',side_effect=AssertionError('no service start')),patch('subprocess.run',side_effect=AssertionError('no installation')):
            receipt=proflow.pack_source(f.work,f.out,manifest)
        with zipfile.ZipFile(receipt['archive']) as z:
            self.assertIsNone(z.testzip());self.assertEqual(set(z.namelist()),set(selected+['LICENSE']))
            for name in z.namelist():self.assertEqual(z.read(name),(f.work/name).read_bytes())
        self.assertFalse(receipt['standalone_startup_required']);self.assertTrue((f.work/'start.ps1').exists())
    def test_missing_or_unlisted_selection_and_excluded_source_rejected(self):
        f=self.fixture(flow.FlowTests);self.enable(f);(f.work/'app.py').write_text('print(1)')
        for spec in ({'files':['app.py']},{'files':['app.py'],'delivery_files':['other.py']},
                     {'files':['app.py'],'delivery_files':['app.py','app.py']},
                     {'files':['app.py'],'delivery_files':['app.py'],'exclude':['app.py']}):
            with self.assertRaises(ValueError):proflow.pack_source(f.work,f.out,f.manifest('source',spec))
        self.assertFalse(delivery_paths(f.run)['source_zip'].exists())
    def test_new_review_accepts_five_but_still_checks_logs_and_archive(self):
        f=self.fixture(packet.ReviewPacketTests);self.enable(f)
        f.proof['checks']=f.checks[:-1];write_json(f.execution,f.proof)
        self.assertEqual(review_packet.inspect(f.work,f.execution)['status'],'inputs_ready')
        f.proof['checks'][0]['sha256']='0'*64;write_json(f.execution,f.proof)
        self.assertNotEqual(review_packet.inspect(f.work,f.execution)['status'],'inputs_ready')
        f.proof['checks'][0]['sha256']=digest(f.work/'algorithm.log');f.proof['source_zip_sha256']='0'*64;write_json(f.execution,f.proof)
        self.assertNotEqual(review_packet.inspect(f.work,f.execution)['status'],'inputs_ready')
    def test_generated_review_instructions_do_not_reintroduce_package_startup(self):
        f=self.fixture(packet.ReviewPacketTests);self.enable(f)
        f.proof['checks']=f.checks[:-1];write_json(f.execution,f.proof)
        report=review_packet.draft(f.work,f.execution,f.target)
        self.assertEqual(report['status'],'draft_created')
        facts=read_json(f.target/'facts.json');draft=read_json(f.target/'review-draft.json')
        self.assertNotIn('package-startup',str(facts['review_sequence']))
        self.assertIn('main algorithm/backend',facts['review_sequence']['first'])
        self.assertIn('Reject excerpt-only',draft['instruction'])
        self.assertEqual(len(draft['checks']),5)
    def test_new_finalization_five_checks_and_no_fake_startup(self):
        f=self.fixture(contracts.ContractTests);self.enable(f)
        f.proof.update(checks=f.runtime_records(f.work,f.out)[:-1],reviewed_files=f.files,
                       visual_notes=['fixture'],limitations=['contract fixture only'],source_zip_sha256=digest(f.system/'项目源码.zip'))
        f.make_media_fixture(f.work,f.out);f.proof['video_timeline_sha256']=read_json(f.work/'.product-v2/controlled-video.json')['sha256'];f.save_proof()
        with patch('proflow.cleanup_ready'),patch('contracts.SESSION_ROOT',f.sessions):
            result=proflow.finalize(f.work,f.out,f.proof_path)
        self.assertEqual(result['status'],'complete');self.assertEqual(len(result['checks']),5)
        self.assertNotIn('package_startup',[c['kind'] for c in result['checks']])
    def test_main_code_probe_stops_before_any_extraction_or_process(self):
        f=self.fixture(flow.FlowTests);self.enable(f)
        with patch('package_probe.unpack',side_effect=AssertionError('no extraction')),patch('package_probe.execute',side_effect=AssertionError('no runtime')):
            with self.assertRaisesRegex(ValueError,'main-code-v1'):
                package_probe.probe(f.work,f.work/'nonexistent.py',f.work/'probe.json')
        self.assertFalse((f.work/'probe.json').exists())
    def test_simplified_repair_reuses_five_checks_without_package_startup(self):
        f=self.fixture(closure.SimplifiedClosureTests);self.enable(f.f)
        f.f.proof['checks']=[c for c in f.f.proof['checks'] if c['kind']!='package_startup']
        f.f.proof['issues'][0]['required_checks']=['browser']
        f.proof['checks']=[c for c in f.proof['checks'] if c['kind']!='package_startup']
        f.proof['resolutions'][0]['checks']=['browser'];f.refresh_first()
        result=f.close();self.assertTrue(f.archive.is_file())
    def test_progress_reuses_business_checks_without_startup_stage(self):
        f=self.fixture(progress.DependencyFixture);self.enable(f);f.recorded()
        write_json(f.control/'cleanup.json',{'status':'stopped','workspace':str(f.work),'remaining':[]})
        exported=f.out/'系统材料/数据/input.csv';exported.write_bytes((f.work/'data/input.csv').read_bytes())
        write_json(f.control/'data-cleaning.json',{'status':'cleaned','quality':{'policy':'neutral-expanded-v1','audit':{'data_status':'pass','files':{'input.csv':{'sha256':digest(exported)}}},'expansion':{'expansion_status':'pass'}},'files':[{'input':str(f.work/'data/input.csv'),
                   'input_sha256':digest(f.work/'data/input.csv'),'name':'input.csv','sha256':digest(exported)}]})
        archive=f.out/'系统材料/源代码.zip';archive.write_bytes(b'fixture')
        write_json(f.control/'source-package.json',{'sha256':digest(archive),'files':{'app.py':digest(f.work/'app.py')}})
        result=f.status()
        self.assertNotIn('final-zip-startup-and-execution-evidence',result['remaining_stages'])
        self.assertEqual(result['next_actions'],['independent-review-changed-or-unread-evidence'])
    def test_document_revision_inherits_five_business_checks(self):
        f=self.fixture(contracts.ContractTests);base,out,receipt=f.revision_fixture()
        r=read_json(base/'.product-v2/run.json');r['source_delivery_policy']=MAIN_CODE_POLICY;write_json(base/'.product-v2/run.json',r)
        proof_path=base/'.product-v2/old-review.json';proof=read_json(proof_path);proof['checks']=proof['checks'][:-1];write_json(proof_path,proof)
        original=read_json(receipt);original['evidence_sha256']=digest(proof_path);write_json(receipt,original)
        f.run['revision_of']['receipt_sha256']=digest(receipt);f.run['source_delivery_policy']=MAIN_CODE_POLICY;write_json(f.work/'.product-v2/run.json',f.run)
        before=digest(receipt)
        with patch('proflow.cleanup_ready'),patch('contracts.SESSION_ROOT',f.sessions):
            result=proflow.finalize_document_revision(f.work,f.out,f.proof_path)
        self.assertEqual(len(result['inherited_checks']),5);self.assertEqual(digest(receipt),before)
    def test_unknown_policy_does_not_bypass_review(self):
        f=self.fixture(packet.ReviewPacketTests)
        p=f.control/'run.json';r=read_json(p);r['source_delivery_policy']='future';write_json(p,r)
        self.assertNotEqual(review_packet.inspect(f.work,f.execution)['status'],'inputs_ready')

if __name__=='__main__':unittest.main()
