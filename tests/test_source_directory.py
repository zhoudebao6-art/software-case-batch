"""Real directory export/publication contracts on isolated synthetic fixtures."""
import copy
import json
import os
from pathlib import Path
import shutil
import sys
import unittest
from unittest.mock import patch
import zipfile
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
from common import digest, file_map, read_json, write_json, delivery_paths
from source_delivery import DIRECTORY_POLICY, source_digest, source_members, source_map_digest
import proflow
import review_packet
import test_product_flow as flow
import test_contracts as contracts
import test_review_packet as packet
import test_simplified_closure as closure

def set_directory(run):
    run.update(delivery_layout_version='system-code-directory-v5',source_delivery_policy=DIRECTORY_POLICY)
    for key in ('system','source_zip','data_dir','video','screenshot'):run.pop(key,None)
    paths=delivery_paths(run)
    for key in ('source_zip','data_dir','video','screenshot'):run[key]=str(paths[key])
    return paths

def convert_fixture(f):
    """Convert only test-owned ZIP fixture bytes; never a production migration."""
    paths=set_directory(f.run)
    old_system=f.system
    old_system.rename(paths['system']);f.system=paths['system']
    z=f.system/'项目源码.zip'
    with zipfile.ZipFile(z) as archive:members={n:archive.read(n) for n in archive.namelist()}
    z.unlink();paths['source_zip'].mkdir()
    for n,b in members.items():
        p=paths['source_zip']/n;p.parent.mkdir(parents=True,exist_ok=True);p.write_bytes(b)
    (f.system/'演示视频.mp4').rename(paths['video'])
    from PIL import Image
    Image.new('RGB',(1920,1080),'white').save(paths['screenshot'])
    write_json(f.work/'.product-v2/run.json',f.run)
    f.files=file_map(f.out)
    return paths

class DirectoryTests(unittest.TestCase):
    def fixture(self,cls):
        f=cls();f.setUp();self.addCleanup(f.doCleanups)
        if hasattr(f,'tearDown'):self.addCleanup(f.tearDown)
        return f

    def test_directory_layout_requires_its_frozen_policy(self):
        f=self.fixture(flow.FlowTests)
        r=copy.deepcopy(f.run);set_directory(r);r.pop('source_delivery_policy')
        with self.assertRaisesRegex(ValueError,'Source policy'):delivery_paths(r)
        r['source_delivery_policy']='main-code-v1'
        with self.assertRaisesRegex(ValueError,'Source policy'):delivery_paths(r)

    def test_export_cleans_internal_files_without_compression_or_source_mutation(self):
        f=self.fixture(flow.FlowTests);paths=set_directory(f.run);write_json(f.work/'.product-v2/run.json',f.run)
        files={'backend/service.py':'def analyze(records):\n    return sum(records)\n',
               'web/app.js':'export const load=()=>fetch("/api/items");',
               'source_analysis.py':'internal', 'prompts/build.txt':'internal',
               '材料.docx':'internal','evidence/check.json':'internal','README.md':'internal',
               'LICENSE':'Permission notice', 'analyze_source.py':'internal'}
        for name,value in files.items():
            p=f.work/name;p.parent.mkdir(parents=True,exist_ok=True);p.write_bytes(value.encode())
        before={k:digest(f.work/k) for k in files}
        manifest=f.manifest('source',{'files':list(files),'delivery_files':list(files)})
        with patch('zipfile.ZipFile',side_effect=AssertionError('no ZIP')),patch('subprocess.Popen',side_effect=AssertionError('no startup')):
            receipt=proflow.pack_source(f.work,f.out,manifest)
        self.assertEqual(receipt['format'],'directory');self.assertNotIn('archive',receipt)
        self.assertEqual(set(receipt['files']),{'backend/service.py','web/app.js','LICENSE'})
        self.assertEqual(source_members(paths['source_zip']),receipt['files'])
        self.assertEqual(before,{k:digest(f.work/k) for k in files})
        self.assertEqual(receipt['sha256'],source_map_digest(f.run,f.out,file_map(f.out)))
        self.assertTrue(proflow.scan_delivery(f.out,run=f.run)['passed'])
        (paths['source_zip']/'analysis.json').write_text('{}')
        self.assertFalse(proflow.scan_delivery(f.out,run=f.run)['passed'])
        self.assertNotEqual(source_digest(paths['source_zip']),receipt['sha256'])
        with self.assertRaisesRegex(ValueError,'exists'):proflow.pack_source(f.work,f.out,manifest)

    def test_empty_and_unsafe_selection_fail(self):
        for selection in (['README.md'],['../escape.py']):
            f=self.fixture(flow.FlowTests);set_directory(f.run);write_json(f.work/'.product-v2/run.json',f.run)
            (f.work/'README.md').write_text('internal')
            with self.assertRaises(ValueError):
                proflow.pack_source(f.work,f.out,f.manifest('source',{'files':selection,'delivery_files':selection}))

    def test_review_draft_binds_directory_members_and_rejects_tampering(self):
        f=self.fixture(packet.ReviewPacketTests)
        r=read_json(f.control/'run.json');paths=set_directory(r);write_json(f.control/'run.json',r)
        paths['source_zip'].mkdir(parents=True);shutil.copyfile(f.source,paths['source_zip']/'app.py')
        f.archive.unlink();f.archive.parent.rmdir()
        receipt={'sha256':source_digest(paths['source_zip']),'files':source_members(paths['source_zip']),
                 'format':'directory','hash_kind':'source-tree-v1'}
        write_json(f.control/'source-package.json',receipt)
        f.proof.update(checks=f.checks[:-1],source_zip_sha256=receipt['sha256']);write_json(f.execution,f.proof)
        report=review_packet.draft(f.work,f.execution,f.target)
        self.assertEqual(report['status'],'draft_created',report)
        draft=read_json(f.target/'review-draft.json')
        self.assertEqual(draft['source_package']['format'],'directory')
        self.assertEqual(draft['source_package']['files'],receipt['files'])
        (paths['source_zip']/'app.py').write_text('changed')
        self.assertNotEqual(review_packet.inspect(f.work,f.execution)['status'],'inputs_ready')

    def test_first_review_finalize_and_atomic_publication_with_real_file_map(self):
        f=self.fixture(contracts.ContractTests)
        checks=f.runtime_records(f.work,f.out)[:-1];f.make_media_fixture(f.work,f.out)
        paths=convert_fixture(f)
        write_json(f.work/'.product-v2/source-package.json',{'sha256':source_digest(paths['source_zip']),
                   'format':'directory','hash_kind':'source-tree-v1','files':source_members(paths['source_zip'])})
        for stage in f.dispatch['stages'].values():stage['artifact_hashes']=f.files
        f.save_dispatch()
        # Recording fixture originally names the old path; actual MP4 bytes unchanged.
        f.proof.update(checks=checks,reviewed_files=f.files,visual_notes=['Synthetic fully read fixture'],limitations=['Test only'],
                       source_zip_sha256=source_digest(paths['source_zip']),
                       video_timeline_sha256=read_json(f.work/'.product-v2/controlled-video.json')['sha256'])
        f.save_proof()
        with patch('proflow.cleanup_ready'),patch('contracts.SESSION_ROOT',f.sessions):
            result=proflow.finalize(f.work,f.out,f.proof_path)
            self.assertEqual(result['status'],'complete')
            status=proflow.workflow_status(f.work,f.out,f.run,evidence_path=f.proof_path)
            self.assertEqual(status['steps']['source_package']['state'],'completed')
            self.assertEqual(status['steps']['execution_evidence']['state'],'completed')
            published=proflow.publish(f.work,f.root/'published')
        self.assertEqual(published['status'],'published')
        self.assertIn('系统代码/主要代码/app.py',published['files'])
        self.assertNotIn('系统代码/主要代码',published['files'])
        self.assertFalse(any(k.endswith('.zip') for k in published['files']))
        revision=f.root/'revision';revision.mkdir();out=f.root/'revision-output'
        shutil.copytree(f.root/'published',out)
        r=proflow.prepare(revision,out,f.run['title'],f.source,revision_of=f.work,adopt_draft=True)
        self.assertEqual(r['source_delivery_policy'],DIRECTORY_POLICY)
        self.assertEqual(source_members(delivery_paths(r)['source_zip']),{'app.py':digest(f.work/'app.py')})
        from delivery_index import case_entry
        self.assertEqual(case_entry(f.root/'published','test')['source'],str(f.root/'published/系统代码/主要代码'))
        # Exercise source-only revision IO with inherited business evidence.
        # Visual/model checks were covered above; mocks here isolate revision format.
        repair=f.root/'source-revision';repair.mkdir();repair_out=f.root/'source-revision-output'
        shutil.copytree(f.root/'published',repair_out)
        rr=proflow.prepare(repair,repair_out,f.run['title'],f.source,revision_of=f.work,adopt_draft=True,revision_scope='package')
        for name in ('.product-v2/chart-manifest.json','.product-v2/source-package.json','app.py'):
            target=repair/name;target.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(f.work/name,target)
        shutil.copytree(f.work/'.product-v2/charts',repair/'.product-v2/charts')
        timeline=repair/'.product-v2/inherited-timeline.json'
        shutil.copyfile(read_json(f.work/'.product-v2/controlled-video.json')['timeline'],timeline)
        chain=proflow.revision_chain(repair,rr['revision_of'])
        proof=dict(f.proof,checks=[],reviewed_files=file_map(repair_out),video_timeline=timeline.relative_to(repair).as_posix(),
                   video_timeline_sha256=digest(timeline),inherited_evidence_chain=[
                       {'workspace':str(e['workspace']),'receipt_sha256':e['receipt_sha256'],'proof_sha256':e['proof_sha256']} for e in chain])
        rp=repair/'.product-v2/review.json';write_json(rp,proof)
        with patch('proflow.cleanup_ready'),patch('media_evidence.validate',return_value={'fixture_only':True}),patch('contracts.model_review',return_value={'fixture_only':True}):
            result=proflow.finalize_package_revision(repair,repair_out,rp)
        self.assertEqual(result['scope'],'package-revision');self.assertEqual(result['checks'],[])
        self.assertEqual(len(result['inherited_checks']),5)

    def closure_fixture(self):
        c=self.fixture(closure.SimplifiedClosureTests);f=c.f
        user_events=[row for row in f.parent_log.read_text(encoding='utf-8').splitlines() if 'user_message' in row]
        paths=convert_fixture(f);prefix='系统代码/主要代码/app.py'
        old_map={k.replace('模拟系统/','系统代码/').replace('演示视频.mp4','操作视频.mp4'):v
                 for k,v in f.proof['reviewed_files'].items() if not k.endswith('项目源码.zip')}
        old_map[prefix]=__import__('hashlib').sha256(b'print(1)').hexdigest()
        old_map['系统代码/界面截图.png']=digest(paths['screenshot'])
        f.proof.update(reviewed_files=old_map,checks=f.proof['checks'][:-1],
                       source_zip_sha256=source_map_digest(f.run,f.out,old_map))
        f.proof['issues'][0]['required_checks']=['browser']
        f.proof['source_package']={'format':'directory','hash_kind':'source-tree-v1',
            'sha256':f.proof['source_zip_sha256'],'files':{'app.py':old_map[prefix]}}
        for check in f.proof['checks']:
            check['artifact_hashes']={k.replace('模拟系统/','系统代码/'):v for k,v in check.get('artifact_hashes',{}).items()}
        for stage in f.dispatch['stages'].values():stage['artifact_hashes']=old_map
        f.save_dispatch();write_json(f.work/'.product-v2/first-dispatch.json',f.dispatch)
        with f.parent_log.open('a',encoding='utf-8') as stream:stream.write('\n'.join(user_events)+'\n')
        f.save_proof()
        c.proof.update(files=f.files,changed_files=[prefix],checks=copy.deepcopy(f.proof['checks']),
                       source_zip_sha256=source_digest(paths['source_zip']))
        browser=next(x for x in c.proof['checks'] if x['kind']=='browser')
        browser.update(log='.product-v2/repair-browser.log',sha256=digest(f.work/'.product-v2/repair-browser.log'),artifact_hashes={prefix:f.files[prefix]})
        c.proof['resolutions'][0].update(affected_files=[prefix],checks=['browser'])
        c.proof['first_dispatch']=closure.closure.reference(f.work/'.product-v2/first-dispatch.json')
        write_json(f.work/'.product-v2/source-package.json',{'sha256':source_digest(paths['source_zip']),'files':source_members(paths['source_zip'])})
        c.refresh_first()
        return c,paths,prefix

    def test_simplified_code_repair_uses_members_not_directory_as_fake_file(self):
        c,paths,prefix=self.closure_fixture()
        result=c.close()
        self.assertTrue(c.archive.is_file());self.assertEqual(result['status'],'delivered')
        with zipfile.ZipFile(c.archive) as z:self.assertTrue(any(n.endswith('/主要代码/app.py') for n in z.namelist()))

    def test_removed_member_binds_old_bytes_and_current_absence_in_existing_check(self):
        c,paths,prefix=self.closure_fixture();f=c.f
        removed='系统代码/主要代码/optional.py';old_sha=__import__('hashlib').sha256(b'old optional code').hexdigest()
        f.proof['reviewed_files'][removed]=old_sha
        f.proof['source_package']['files']['optional.py']=old_sha
        f.proof['source_package']['sha256']=source_map_digest(f.run,f.out,f.proof['reviewed_files'])
        f.proof['source_zip_sha256']=f.proof['source_package']['sha256']
        f.proof['issues'][0].update(severity='minor',required_checks=[])
        # Fixture reviewer and repairer attest their actual different member maps.
        for stage in f.dispatch['stages'].values():stage['artifact_hashes']=f.proof['reviewed_files']
        events=[row for row in f.parent_log.read_text(encoding='utf-8').splitlines() if 'user_message' in row]
        f.save_dispatch()
        with f.parent_log.open('a',encoding='utf-8') as stream:stream.write('\n'.join(events)+'\n')
        write_json(f.work/'.product-v2/first-dispatch.json',f.dispatch)
        c.proof['first_dispatch']=closure.closure.reference(f.work/'.product-v2/first-dispatch.json')
        browser=next(x for x in c.proof['checks'] if x['kind']=='browser')
        browser['removed_artifacts']={removed:old_sha}
        c.proof['changed_files']=sorted([prefix,removed])
        c.proof['resolutions'][0].update(status='removed',affected_files=[prefix,removed])
        c.refresh_first()
        browser['removed_artifacts'][removed]='0'*64;c.save()
        with self.assertRaisesRegex(ValueError,'Removed source evidence'):c.close()
        browser['removed_artifacts'][removed]=old_sha;c.save()
        self.assertEqual(c.close()['status'],'delivered')

    def test_business_prompt_code_is_not_removed_as_production_instruction(self):
        self.assertIsNone(proflow.excluded_source('prompts/retrieval.py'))
        self.assertIsNotNone(proflow.excluded_source('prompts/build.txt'))

if __name__=='__main__':unittest.main()
