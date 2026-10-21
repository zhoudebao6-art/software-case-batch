"""Dependency admission and receipt-only next-action regressions, no media work."""
import copy
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
import zipfile

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
from common import digest,read_json,write_json,file_map
from contracts import construction_checks,CONSTRUCTION_POLICY,CONSTRUCTION_KINDS
from proflow import prepare,workflow_status,finalize


class DependencyFixture(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name)
        self.work=self.root/'case';self.work.mkdir();self.out=self.root/'delivery'
        self.control=self.work/'.product-v2'
        self.source=self.work/'原技术材料.docx'
        with zipfile.ZipFile(self.source,'w') as package:package.writestr('word/document.xml','<document/>')
        self.run=prepare(self.work,self.out,'运行管理',self.source)
        self.run.pop('web_experience_policy',None)  # Frozen pre-r31 dependency fixture.
        write_json(self.control/'run.json',self.run)
        self.file('app.py','engine');self.file('web/app.js','web');self.file('LICENSES/license.txt','license')
        self.file('data/input.csv','编号,值\n001,10\n')
        self.plan=self.control/'record-plan.json';write_json(self.plan,{'input_files':['app.py','data/input.csv']})
        self.manifest=self.control/'source-manifest.json'
        self.members=['app.py','web/app.js','LICENSES/license.txt']
        write_json(self.manifest,{'files':self.members})
        self.checks={'run_id':self.run['run_id'],'source_docx_sha256':self.run['source_docx_sha256'],
                     'implementation_hashes':{p:digest(self.work/p) for p in self.members},'checks':{}}
        dependencies={'algorithm':['app.py','data/input.csv'],'api':['app.py'],
                      'persistence':['app.py'],'browser':['web/app.js'],'build':['LICENSES/license.txt']}
        for kind in CONSTRUCTION_KINDS:
            test='tools/check_'+kind+'.py';log='evidence/'+kind+'.log'
            self.file(test,'assert True  # fixture only');self.file(log,'actual fixture output '+kind)
            self.checks['checks'][kind]={'command':'python '+test,'exit_code':0,'log':log,'sha256':digest(self.work/log),
                'test_files':[test],'input_files':{p:digest(self.work/p) for p in dependencies[kind]+[test]}}
        self.checks_path=self.control/'build-checks.json';self.save_checks()
    def tearDown(self):self.temp.cleanup()
    def file(self,relative,text):
        path=self.work/relative;path.parent.mkdir(parents=True,exist_ok=True);path.write_text(text,encoding='utf-8');return path
    def save_checks(self):write_json(self.checks_path,self.checks)
    def gate(self):return construction_checks(self.work,self.run,self.plan)
    def status(self,evidence=None):
        with patch('subprocess.run',side_effect=AssertionError('Status must not run stages')),patch('subprocess.Popen',side_effect=AssertionError('Status must not start services')):
            return workflow_status(self.work,self.out,self.run,self.plan,evidence)
    def recorded(self,technical=True):
        system=self.out/'系统材料';system.mkdir(exist_ok=True)
        (system/'数据').mkdir(exist_ok=True)
        video=system/'操作视频.mp4';video.write_bytes(b'unit fixture representing recorded video')
        raw=self.file('evidence/original.webm','original continuous capture fixture')
        capture_path=self.control/'capture.json'
        write_json(capture_path,{'status':'captured','errors':[],'workspace':str(self.work),'run_id':self.run['run_id'],
            'rawPath':str(raw),'raw_sha256':digest(raw),'inputs':{'app.py':digest(self.work/'app.py'),'data/input.csv':digest(self.work/'data/input.csv')},
            'plan_path':str(self.plan),'plan_sha256':digest(self.plan),'construction_checks':self.gate()})
        write_json(self.control/'capture-pending.json',{'path':str(capture_path),'sha256':digest(capture_path)})
        recording={'passed':True,'sha256':digest(video),'input_files':{'app.py':digest(self.work/'app.py'),'data/input.csv':digest(self.work/'data/input.csv')},
                   'plan_path':str(self.plan),'plan_sha256':digest(self.plan),'construction_checks':self.gate()}
        write_json(self.control/'recording.json',recording)
        if technical:
            timeline=self.work/'evidence/timeline.json'
            write_json(timeline,{'video_sha256':recording['sha256'],'decode_ok':True,'sample_fps':5,
                'recording_receipt':{'path':str(self.control/'recording.json'),'sha256':digest(self.control/'recording.json')},
                'frames':[{'file':str(self.work/'never-read-frame.png')} ]})
            write_json(self.control/'controlled-video.json',{'timeline':str(timeline),'sha256':digest(timeline)})
        return recording


class ConstructionTests(DependencyFixture):
    def test_new_run_freezes_policy_and_unchanged_checks_are_current(self):
        self.assertEqual(self.run['construction_check_policy_version'],CONSTRUCTION_POLICY)
        before=file_map(self.work);result=self.gate()
        self.assertEqual(result['status'],'ready');self.assertEqual(file_map(self.work),before)
    def test_missing_failed_and_changed_log_reject(self):
        original=copy.deepcopy(self.checks)
        changes=[lambda x:x['checks'].pop('api'),lambda x:x['checks']['api'].update(exit_code=1),
                 lambda x:x['checks']['api'].update(exit_code=False),lambda x:x['checks']['api'].update(sha256='0'*64),
                 lambda x:x['checks']['api'].update(input_files={}),lambda x:x['checks']['api'].update(test_files=[]),
                 lambda x:x.update(run_id='other'),lambda x:x.update(source_docx_sha256='0'*64)]
        for change in changes:
            with self.subTest(change=change):
                self.checks=copy.deepcopy(original);change(self.checks);self.save_checks()
                with self.assertRaises(ValueError):self.gate()
    def test_source_member_addition_and_missing_recording_dependency_reject(self):
        self.file('new.py','new');write_json(self.manifest,{'files':self.members+['new.py']})
        with self.assertRaisesRegex(ValueError,'implementation'):self.gate()
        write_json(self.manifest,{'files':self.members})
        self.checks['checks']['algorithm']['input_files'].pop('data/input.csv');self.save_checks()
        with self.assertRaisesRegex(ValueError,'omit'):self.gate()
    def test_repaired_browser_dependency_keeps_unaffected_algorithm_log(self):
        algorithm=copy.deepcopy(self.checks['checks']['algorithm'])
        self.file('web/app.js','changed web')
        self.checks['implementation_hashes']['web/app.js']=digest(self.work/'web/app.js');self.save_checks()
        with self.assertRaisesRegex(ValueError,'browser / web/app.js'):self.gate()
        self.checks['checks']['browser']['input_files']['web/app.js']=digest(self.work/'web/app.js');self.save_checks()
        self.assertEqual(self.gate()['status'],'ready');self.assertEqual(self.checks['checks']['algorithm'],algorithm)
    def test_test_script_change_needs_recheck_but_does_not_change_recording_dependencies(self):
        self.recorded();self.file('tools/check_algorithm.py','new final consumer boundary assertion')
        with self.assertRaisesRegex(ValueError,'algorithm / tools'):self.gate()
        self.assertEqual(self.status()['steps']['recording']['state'],'technical_ready')
        self.checks['checks']['algorithm']['input_files']['tools/check_algorithm.py']=digest(self.work/'tools/check_algorithm.py');self.save_checks()
        self.assertEqual(self.gate()['status'],'ready');self.assertNotIn('capture',self.status()['next_actions'])
    def test_unsafe_dependency_or_unknown_policy_reject(self):
        self.checks['checks']['algorithm']['input_files']['../outside.py']='0'*64;self.save_checks()
        with self.assertRaisesRegex(ValueError,'Unsafe'):self.gate()
        for policy in ['unknown',None]:
            self.run['construction_check_policy_version']=policy
            with self.assertRaisesRegex(ValueError,'Unknown'):self.gate()
    def test_absent_policy_preserves_old_run_without_changing_it(self):
        self.run.pop('construction_check_policy_version');before=copy.deepcopy(self.run)
        self.checks_path.unlink()
        self.assertFalse(self.gate()['required']);self.assertEqual(self.run,before)
    def test_finalize_rechecks_gate_before_artifact_work(self):
        self.recorded();self.checks['checks']['api']['exit_code']=1;self.save_checks()
        checks=[]
        for kind in ('algorithm','api','persistence','browser','build','package_startup'):
            log=self.file('evidence/final-'+kind+'.log','isolated execution fixture '+kind)
            checks.append({'kind':kind,'command':'isolated-check '+kind,'exit_code':0,
                           'log':str(log.relative_to(self.work)),'sha256':digest(log)})
        proof=self.control/'execution-for-failed-construction.json';write_json(proof,{'checks':checks})
        with patch('contracts.chart_snapshot',side_effect=AssertionError('Expensive artifacts reached')) as artifacts:
            with self.assertRaisesRegex(ValueError,'construction execution log: api'):
                finalize(self.work,self.out,proof)
            artifacts.assert_not_called()


class ProgressTests(DependencyFixture):
    def test_next_action_respects_media_cleanup_package_and_final_startup_order(self):
        result=self.status();self.assertEqual(result['next_actions'],['check-build then capture'])
        self.assertIn('clean-data',result['remaining_stages'])
        self.recorded();self.assertEqual(self.status()['next_actions'],['cleanup-after-required-online-work'])
        write_json(self.control/'cleanup.json',{'status':'stopped','workspace':str(self.work),'remaining':[]})
        self.assertEqual(self.status()['next_actions'],['preserve-data-draft then clean-data'])
        exported=self.out/'系统材料/数据/input.csv';exported.write_bytes((self.work/'data/input.csv').read_bytes())
        write_json(self.control/'data-cleaning.json',{'status':'cleaned','files':[{'input':str(self.work/'data/input.csv'),
            'input_sha256':digest(self.work/'data/input.csv'),'name':'input.csv','sha256':digest(exported)}]})
        self.assertEqual(self.status()['next_actions'],['check-data'])
        cleaned=read_json(self.control/'data-cleaning.json')
        cleaned['quality']={'policy':'neutral-expanded-v1','audit':{'data_status':'pass','files':{'input.csv':{'sha256':digest(exported)}}},
                            'expansion':{'expansion_status':'pass'}}
        write_json(self.control/'data-cleaning.json',cleaned)
        self.assertEqual(self.status()['next_actions'],['pack-source'])
        archive=self.out/'系统材料/源代码.zip';archive.write_bytes(b'final package fixture')
        write_json(self.control/'source-package.json',{'sha256':digest(archive),'files':{'app.py':digest(self.work/'app.py')}})
        self.assertEqual(self.status()['next_actions'],['verify-final-zip-startup-and-execution-evidence'])
        startup=self.file('evidence/package-startup.log','isolated final zip startup fixture')
        facts=self.control/'execution-facts.json';checks=copy.deepcopy(self.checks['checks'])
        checks['package_startup']={'command':'run final package fixture','exit_code':0,'log':'evidence/package-startup.log','sha256':digest(startup)}
        write_json(facts,{'checks':checks,'source_zip_sha256':digest(archive)})
        result=self.status(facts)
        self.assertEqual(result['next_actions'],['independent-review-changed-or-unread-evidence'])
        self.assertEqual(result['independent_visual_review'],'pending')
        self.assertEqual(result['review_pointers'][0]['status'],'pointer-only-not-authenticated')
    def test_captured_only_recommends_evidence_and_never_replays_business(self):
        raw=self.file('evidence/raw.webm','original raw fixture')
        capture_path=self.control/'capture.json'
        write_json(capture_path,{'status':'captured','errors':[],'workspace':str(self.work),'run_id':self.run['run_id'],
            'rawPath':str(raw),'raw_sha256':digest(raw),'inputs':{'app.py':digest(self.work/'app.py')},
            'plan_sha256':digest(self.plan),'construction_checks':self.gate()})
        write_json(self.control/'capture-pending.json',{'path':str(capture_path),'sha256':digest(capture_path)})
        result=self.status();self.assertEqual(result['steps']['recording']['state'],'captured')
        self.assertIn('evidence',result['next_actions']);self.assertNotIn('check-build then capture',result['next_actions'])
    def test_technical_ready_pending_first_independent_visual_is_not_recording_failure(self):
        self.recorded();before=file_map(self.work);result=self.status()
        self.assertEqual(result['steps']['recording']['state'],'technical_ready')
        self.assertEqual(result['independent_visual_review'],'pending')
        self.assertNotIn('evidence',result['next_actions']);self.assertNotIn('check-build then capture',result['next_actions'])
        self.assertEqual(file_map(self.work),before)
        self.assertIn('frame files were not rechecked',result['steps']['recording']['verification_scope'])
    def test_word_license_and_new_test_log_do_not_invalidate_video(self):
        self.recorded();Path(self.run['word']).write_text('changed Word only',encoding='utf8')
        self.file('LICENSES/license.txt','changed lawful packaging notice')
        self.file('evidence/algorithm-new.log','new check evidence')
        self.assertEqual(self.status()['steps']['recording']['state'],'technical_ready')
    def test_changed_current_business_dependency_keeps_completed_video(self):
        self.recorded();self.file('app.py','changed shared engine')
        result=self.status();self.assertEqual(result['steps']['recording']['state'],'technical_ready')
        self.assertTrue(result['steps']['recording']['video_completed'])
        self.assertNotIn('check-build then capture',result['next_actions'])
    def test_only_missing_technical_timeline_recommends_evidence(self):
        self.recorded();(self.work/'evidence/timeline.json').unlink()
        result=self.status();self.assertEqual(result['steps']['recording']['state'],'captured')
        self.assertIn('evidence',result['next_actions']);self.assertNotIn('check-build then capture',result['next_actions'])
    def test_only_missing_or_changed_mp4_reuses_original_capture_without_business_replay(self):
        self.recorded();video=Path(self.run['video']);video.unlink()
        result=self.status();self.assertEqual(result['steps']['recording']['state'],'captured')
        self.assertIn('evidence',result['next_actions']);self.assertNotIn('check-build then capture',result['next_actions'])
        video.write_bytes(b'changed encoded artifact')
        result=self.status();self.assertEqual(result['steps']['recording']['next_action'],'preserve-video-draft then evidence')
        self.assertNotIn('check-build then capture',result['next_actions'])
        (self.work/'evidence/original.webm').unlink()
        result=self.status();self.assertEqual(result['steps']['recording']['state'],'unknown')
        self.assertNotIn('check-build then capture',result['next_actions'])
    def test_failed_and_unfinished_capture_are_not_reusable(self):
        write_json(self.control/'capture-pending.json',{'status':'capturing','sha256':None})
        result=self.status();self.assertEqual(result['steps']['recording']['state'],'unknown')
        self.assertNotIn('check-build then capture',result['next_actions'])
        self.recorded();value=read_json(self.control/'recording.json');value['passed']=False;write_json(self.control/'recording.json',value)
        self.assertEqual(self.status()['steps']['recording']['state'],'failed')
        self.assertNotIn('check-build then capture',self.status()['next_actions'])
    def test_unreadable_receipts_report_unknown_without_stage_replay(self):
        (self.control/'recording.json').write_text('{broken',encoding='utf8')
        result=self.status();self.assertEqual(result['steps']['recording']['state'],'unknown')
        self.assertNotIn('check-build then capture',result['next_actions'])
    def test_data_and_package_hash_changes_are_local(self):
        self.recorded();system=self.out/'系统材料'
        exported=system/'数据/input.csv';exported.write_text('编号,值\n001,10\n',encoding='utf8')
        archive=system/'源代码.zip';archive.write_bytes(b'package fixture')
        write_json(self.control/'data-cleaning.json',{'status':'cleaned','files':[{'input':str(self.work/'data/input.csv'),
            'input_sha256':digest(self.work/'data/input.csv'),'name':'input.csv','sha256':digest(exported)}]})
        write_json(self.control/'source-package.json',{'sha256':digest(archive),'files':{'app.py':digest(self.work/'app.py')}})
        cleaned=read_json(self.control/'data-cleaning.json')
        cleaned['quality']={'policy':'neutral-expanded-v1','audit':{'data_status':'pass','files':{'input.csv':{'sha256':digest(exported)}}},
                            'expansion':{'expansion_status':'pass'}}
        write_json(self.control/'data-cleaning.json',cleaned)
        result=self.status();self.assertEqual(result['steps']['data']['state'],'completed');self.assertEqual(result['steps']['source_package']['state'],'completed')
        exported.write_text('new exported bytes',encoding='utf8');archive.write_bytes(b'new packaging bytes')
        result=self.status();self.assertEqual(result['steps']['data']['state'],'stale');self.assertEqual(result['steps']['source_package']['state'],'stale')
        self.assertEqual(result['steps']['recording']['state'],'technical_ready')
    def test_incomplete_self_signed_final_never_attests_independent_acceptance(self):
        self.recorded();system=self.out/'系统材料'
        Path(self.run['word']).write_bytes(self.source.read_bytes());(system/'源代码.zip').write_bytes(b'zip fixture')
        (system/'数据/records.csv').write_text('编号\n1\n',encoding='utf8')
        proof=self.control/'review.json';write_json(proof,{'reviewer_agent_id':'fixture-independent','reviewed_evidence':['E001']})
        final={'status':'complete','files':file_map(self.out),'verified_dispatch':{'review':{'agent_id':'fixture-independent'}},
               'execution_evidence':str(proof),'evidence_sha256':digest(proof)}
        write_json(self.control/'final-receipt.json',final)
        write_json(self.control/'publish-receipt.json',{'status':'published','files':final['files'],
                   'source_receipt_sha256':digest(self.control/'final-receipt.json')})
        self.run['status']='published'
        before=file_map(self.work);result=self.status()
        self.assertNotEqual(result.get('state'),'published')
        self.assertNotEqual(result['independent_visual_review'],'verified')
        self.assertNotEqual(result['next_actions'],[])
        self.assertEqual(file_map(self.work),before)
        self.assertEqual(result['review_pointers'][0]['reviewed_evidence'],['E001'])
    def test_foreign_or_missing_media_admission_never_reuses_capture(self):
        for field,value in [('status','failed'),('run_id','foreign-case-run'),('source_docx_sha256','0'*64)]:
            with self.subTest(field=field):
                self.recorded();record=read_json(self.control/'recording.json')
                record['construction_checks'][field]=value;write_json(self.control/'recording.json',record)
                timeline=self.work/'evidence/timeline.json';facts=read_json(timeline)
                facts['recording_receipt']['sha256']=digest(self.control/'recording.json');write_json(timeline,facts)
                write_json(self.control/'controlled-video.json',{'timeline':str(timeline),'sha256':digest(timeline)})
                before=file_map(self.work);result=self.status()
                self.assertEqual(result['steps']['recording']['state'],'unknown')
                self.assertNotIn('check-build then capture',result['next_actions'])
                self.assertEqual(file_map(self.work),before)
        self.recorded();capture_path=self.control/'capture.json';capture=read_json(capture_path)
        capture['construction_checks']['run_id']='foreign-case-run';write_json(capture_path,capture)
        write_json(self.control/'capture-pending.json',{'path':str(capture_path),'sha256':digest(capture_path)})
        (self.control/'recording.json').unlink()
        self.assertEqual(self.status()['steps']['recording']['state'],'unknown')
        self.run.pop('construction_check_policy_version')
        self.assertEqual(self.status()['steps']['recording']['state'],'captured')
    def test_strict_historical_published_snapshot_authenticates_only_review_call(self):
        from test_contracts import ContractTests
        from contracts import model_review, _dispatch_events
        fixture=ContractTests();fixture.setUp()
        try:
            control=fixture.work/'.product-v2';checks=[]
            for kind in ['algorithm','api','persistence','browser','build','package_startup']:
                log=fixture.work/'evidence'/(kind+'.log');log.parent.mkdir(exist_ok=True)
                log.write_text('isolated execution fixture '+kind,encoding='utf-8')
                checks.append({'kind':kind,'command':'fixture '+kind,'exit_code':0,
                               'log':log.relative_to(fixture.work).as_posix(),'sha256':digest(log)})
            recording={'passed':True,'sha256':digest(fixture.system/'演示视频.mp4'),
                       'input_files':{fixture.source.name:digest(fixture.source)}}
            write_json(control/'recording.json',recording)
            timeline=fixture.work/'evidence/timeline.json'
            write_json(timeline,{'video_sha256':recording['sha256'],'decode_ok':True,'sample_fps':5,
                'recording_receipt':{'path':str(control/'recording.json'),'sha256':digest(control/'recording.json')}})
            write_json(control/'controlled-video.json',{'timeline':str(timeline),'sha256':digest(timeline)})
            fixture.proof.update(checks=checks,reviewed_files=fixture.files,visual_notes=['fixture review notes'],
                limitations=['fixture only'],source_zip_sha256=digest(fixture.system/'项目源码.zip'),
                video_timeline_sha256=digest(timeline),reviewed_evidence=['E001'])
            fixture.save_proof()
            with patch('contracts.SESSION_ROOT',fixture.sessions):
                dispatch=model_review(fixture.work,fixture.proof,fixture.files,fixture.charts,fixture.proof_path)
            final={'status':'complete','files':fixture.files,'verified_dispatch':dispatch,'chart_snapshot':fixture.charts,
                   'checks':checks,'execution_evidence':str(fixture.proof_path),'evidence_sha256':digest(fixture.proof_path)}
            write_json(control/'final-receipt.json',final)
            write_json(control/'publish-receipt.json',{'status':'published','files':final['files'],
                       'source_receipt_sha256':digest(control/'final-receipt.json')})
            fixture.run['status']='published';before=file_map(fixture.work)
            with patch('contracts.SESSION_ROOT',fixture.sessions),patch('contracts._dispatch_events',wraps=_dispatch_events) as calls,\
                    patch('contracts.chart_snapshot',side_effect=AssertionError('Status must not inspect charts')),\
                    patch('subprocess.run',side_effect=AssertionError('Status must not run stages')):
                result=workflow_status(fixture.work,fixture.out,fixture.run)
                self.assertEqual(calls.call_count,1);self.assertEqual(calls.call_args.args[1],'review')
            self.assertEqual(result['state'],'published');self.assertEqual(result['next_actions'],[])
            self.assertEqual(result['independent_visual_review'],'verified');self.assertEqual(file_map(fixture.work),before)
            fixture.word.write_bytes(b'changed Word')
            result=workflow_status(fixture.work,fixture.out,fixture.run)
            self.assertEqual(result['independent_visual_review'],'stale')
            self.assertEqual(result['steps']['recording']['state'],'technical_ready')
        finally:fixture.tearDown()


if __name__=='__main__':unittest.main()
