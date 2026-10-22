"""Versioned module-count and real evidence-binding fixtures, not browser approval."""
import copy
from pathlib import Path
import sys
import unittest

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
from common import digest,read_json,write_json
from evidence_index import _required_review_paths,review_coverage_snapshot
from proflow import prepare
from web_contract import WEB_MODULE_POLICY,web_module_policy
import test_contracts as contracts_fixture
import test_rich_delivery as rich_fixtures


class TenModuleGateTests(unittest.TestCase):
    setUp=rich_fixtures.RichWebTests.setUp
    tearDown=rich_fixtures.RichWebTests.tearDown
    file=rich_fixtures.RichWebTests.file
    image=rich_fixtures.RichWebTests.image
    assertion=rich_fixtures.RichWebTests.assertion
    save=rich_fixtures.RichWebTests.save
    validate=rich_fixtures.RichWebTests.validate
    rich=rich_fixtures.RichWebTests.rich

    def ten(self,count=10):
        self.rich(count)
        self.run['web_module_policy']=WEB_MODULE_POLICY
        for module,assertion in zip(self.web['modules'],self.report['assertions']):
            module.update(entry_assertion_id=assertion['id'],screenshot='screen.png')
            assertion.update(entry_visible=True,ui_locator=module['ui_locator'])
            assertion['evidence_paths'].append('screen.png')
        self.save()

    def test_nine_is_rejected_under_new_policy(self):
        self.ten(9)
        with self.assertRaisesRegex(ValueError,'at least 10'):
            self.validate()

    def test_ten_and_more_are_allowed_without_upper_limit(self):
        for count in (10,17):
            with self.subTest(count=count):
                self.ten(count)
                result=self.validate()
                self.assertEqual(len(result['module_ids']),count)
                self.assertEqual(result['minimum_business_modules'],10)
                self.assertEqual(result['web_module_policy'],WEB_MODULE_POLICY)

    def test_historical_rich_delivery_six_module_contract_is_unchanged(self):
        self.rich(6)
        self.assertNotIn('web_module_policy',self.run)
        self.assertEqual(len(self.validate()['module_ids']),6)
        self.rich(5)
        with self.assertRaisesRegex(ValueError,'at least 6'):
            self.validate()

    def test_shared_actual_screenshot_is_allowed_for_simultaneously_visible_modules(self):
        self.ten()
        result=self.validate()
        self.assertEqual(set(result['module_screenshots'].values()),{'screen.png'})
        self.assertEqual(len(result['module_entry_assertions']),10)

    def test_missing_hidden_or_wrong_entry_and_foreign_assertion_reject(self):
        for mutation in ('missing','hidden','string_true','wrong_locator','foreign_assertion'):
            with self.subTest(mutation=mutation):
                self.ten()
                module=self.web['modules'][0];assertion=self.report['assertions'][0]
                if mutation=='missing':module.pop('entry_assertion_id')
                if mutation=='hidden':assertion['entry_visible']=False
                if mutation=='string_true':assertion['entry_visible']='true'
                if mutation=='wrong_locator':assertion['ui_locator']='#other-section'
                if mutation=='foreign_assertion':module['entry_assertion_id']='assertion-1'
                self.save()
                with self.assertRaisesRegex(ValueError,'visible entry/action assertion'):
                    self.validate()

    def test_missing_unbound_or_damaged_module_interface_image_rejects(self):
        for mutation in ('missing','unbound','damaged'):
            with self.subTest(mutation=mutation):
                self.ten()
                if mutation=='missing':self.web['modules'][0].pop('screenshot')
                if mutation=='unbound':self.report['assertions'][0]['evidence_paths'].remove('screen.png')
                if mutation=='damaged':self.file('screen.png',b'not an interface PNG')
                self.save()
                with self.assertRaises(ValueError):
                    self.validate()

    def test_empty_purposes_repeated_actions_and_duplicate_locations_do_not_count(self):
        for mutation in ('empty_purpose','repeated_action','duplicate_locator'):
            with self.subTest(mutation=mutation):
                self.ten()
                module=self.web['modules'][1]
                if mutation=='empty_purpose':module['purpose']=' '
                if mutation=='repeated_action':module['assertion_ids']=['assertion-0']
                if mutation=='duplicate_locator':module['ui_locator']=self.web['modules'][0]['ui_locator']
                self.save()
                with self.assertRaises(ValueError):
                    self.validate()

    def test_unknown_or_null_module_policy_cannot_relax_the_gate(self):
        for value in ('future','',None,True,{}):
            with self.subTest(value=value):
                self.ten()
                self.run['web_module_policy']=value
                with self.assertRaisesRegex(ValueError,'Unknown Web module policy'):
                    self.validate()

    def test_known_policy_cannot_silently_drop_the_web_contract(self):
        self.ten()
        self.run.pop('web_experience_policy')
        with self.assertRaises(ValueError):self.validate()
        self.run.pop('delivery_requirements_version')
        with self.assertRaises(ValueError):self.validate()

    def frozen_scope(self):
        return {'word':{'sha256':'1'*64,'page_count':1,'pages':[{'page':1,'path':'word-page.png'}]},
                'source_mappings':['mapping.json'],'web':self.validate(),
                'video':{'timeline':{'path':'timeline.json'},'contact_sheets':[{'path':'core-contact.png'}],
                         'endpoints':[{'type':'first','path':'first.png'},{'type':'last','path':'last.png'}],
                         'interaction_frames':[{'path':'core-action.png'}]}}

    def test_first_review_keeps_all_modules_but_video_can_cover_only_core_flow(self):
        self.ten()
        scope=self.frozen_scope()
        run=dict(self.run,word_name='original.docx')
        required,_=_required_review_paths(self.work,run,scope,[],{'original.docx':'1'*64},current=False)
        self.assertIn('screen.png',required)
        self.assertEqual(len(scope['web']['module_entry_assertions']),10)
        self.assertEqual(len(scope['video']['interaction_frames']),1)

    def test_frozen_first_review_cannot_omit_module_or_visible_entry_bindings(self):
        self.ten()
        original=self.frozen_scope();run=dict(self.run,word_name='original.docx')
        for field in ('module_ids','module_entry_assertions','module_screenshots','web_module_policy'):
            with self.subTest(field=field):
                scope=copy.deepcopy(original);scope['web'].pop(field)
                with self.assertRaisesRegex(ValueError,'all ten-policy modules'):
                    _required_review_paths(self.work,run,scope,[],{'original.docx':'1'*64},current=False)

    def test_document_revision_inherits_without_reopening_unchanged_web_or_video(self):
        self.ten()
        run=dict(self.run,revision_of={'run_id':'prior'},revision_scope='document',word_name='original.docx')
        scope={'word':{'sha256':'1'*64,'page_count':1,'pages':[{'page':1,'path':'word-page.png'}]},
               'source_mappings':['mapping.json']}
        required,_=_required_review_paths(self.work,run,scope,[],{'original.docx':'1'*64},current=False)
        self.assertNotIn('.product-v2/build-checks.json',required)

    def current_review_materials(self):
        """Minimal real scope/index inputs; these are explicitly structural fixtures."""
        self.ten()
        control=self.work/'.product-v2';control.mkdir(exist_ok=True)
        run=dict(self.run,word_name='original.docx',review_coverage_policy='required-evidence-v1')
        write_json(control/'run.json',run)
        write_json(control/'chart-manifest.json',{'figures':[]})
        write_json(control/'source-package.json',{'files':{'app.py':digest(self.work/'app.py')}})
        row={'file':'screen.png','sha256':digest(self.work/'screen.png')}
        timeline={'frames':[dict(row,type='first'),dict(row,type='last')],
                  'contact_sheets':[dict(row)],'interaction_frames':[dict(row)]}
        write_json(self.work/'timeline.json',timeline)
        write_json(control/'controlled-video.json',{'timeline':'timeline.json','sha256':digest(self.work/'timeline.json')})
        self.spec['checks']['browser']['log']='execution.log'
        write_json(control/'build-checks.json',self.spec)
        word_sha=digest(self.work/'original.docx')
        scope={'word':{'sha256':word_sha,'page_count':1,'pages':[{'page':1,'path':'screen.png'}]},
               'source_mappings':['mapping.json']}
        return run,scope,{'original.docx':word_sha}

    def test_current_scope_roundtrips_all_module_facts_into_frozen_validation(self):
        run,scope,artifacts=self.current_review_materials()
        _required_review_paths(self.work,run,scope,[],artifacts,current=True)
        expected=self.validate()
        for key in ('module_ids','web_module_policy','minimum_business_modules',
                    'module_entry_assertions','module_screenshots'):
            self.assertEqual(scope['web'][key],expected[key])
        required,_=_required_review_paths(self.work,run,scope,[],artifacts,current=False)
        self.assertIn('screen.png',required)
        self.assertEqual(len(scope['web']['module_ids']),10)

    def test_actual_current_review_index_keeps_module_facts_for_frozen_replay(self):
        run,scope,artifacts=self.current_review_materials()
        records=[{'id':'E'+str(i),'path':p.relative_to(self.work).as_posix(),'sha256':digest(p)}
                 for i,p in enumerate(sorted(p for p in self.work.rglob('*') if p.is_file()),1)]
        index=review_coverage_snapshot(self.work,run,records,scope,checks=[],artifacts=artifacts)
        frozen=index['review_scope']
        required,_=_required_review_paths(self.work,run,frozen,[],artifacts,current=False)
        self.assertEqual(frozen['web']['web_module_policy'],WEB_MODULE_POLICY)
        self.assertEqual(set(frozen['web']['module_ids']),set(frozen['web']['module_entry_assertions']))
        self.assertEqual(set(frozen['web']['module_ids']),set(frozen['web']['module_screenshots']))
        self.assertIn('screen.png',required)
        self.assertTrue(index['required_evidence'])


class PrepareModulePolicyTests(unittest.TestCase):
    def setUp(self):
        self.f=contracts_fixture.ContractTests();self.f.setUp()

    def tearDown(self):self.f.tearDown()

    def test_new_complete_prepare_freezes_policy_and_is_idempotent(self):
        work=self.f.root/'fresh-ten';work.mkdir();output=self.f.root/'fresh-ten-output'
        run=prepare(work,output,'设备运行管理',self.f.source)
        self.assertEqual(run['web_module_policy'],WEB_MODULE_POLICY)
        self.assertEqual(run['delivery_requirements_version'],'rich-delivery-v1')
        self.assertEqual(run['recording_policy_version'],'flow-complete-v2')
        frozen=digest(work/'.product-v2/run.json')
        self.assertEqual(prepare(work,output,'设备运行管理',self.f.source),run)
        self.assertEqual(digest(work/'.product-v2/run.json'),frozen)

    def test_existing_pre_r36_prepare_does_not_gain_policy(self):
        self.assertNotIn('web_module_policy',self.f.run)
        frozen=digest(self.f.work/'.product-v2/run.json')
        result=prepare(self.f.work,self.f.out,'设备运行控制',self.f.source)
        self.assertNotIn('web_module_policy',result)
        self.assertEqual(digest(self.f.work/'.product-v2/run.json'),frozen)

    def test_both_revision_scopes_inherit_present_or_absent_parent_policy(self):
        base,_,_=self.f.revision_fixture();path=base/'.product-v2/run.json';original=read_json(path)
        for i,policy in enumerate((None,WEB_MODULE_POLICY)):
            parent=dict(original)
            if policy:parent['web_module_policy']=policy
            write_json(path,parent);before=digest(path)
            for scope in ('document','package'):
                work=self.f.root/f'revision-ten-{i}-{scope}';work.mkdir();output=self.f.root/f'out-ten-{i}-{scope}'
                run=prepare(work,output,'设备运行控制',self.f.source,base,revision_scope=scope)
                self.assertEqual(run.get('web_module_policy'),policy)
                frozen=digest(work/'.product-v2/run.json')
                prepare(work,output,'设备运行控制',self.f.source,base,revision_scope=scope)
                self.assertEqual(digest(work/'.product-v2/run.json'),frozen)
                self.assertEqual(digest(path),before)

    def test_unknown_existing_and_parent_policy_fail_before_new_output(self):
        bad=dict(self.f.run,web_module_policy='unknown')
        write_json(self.f.work/'.product-v2/run.json',bad)
        with self.assertRaisesRegex(ValueError,'Unknown Web module policy'):
            prepare(self.f.work,self.f.out,'设备运行控制',self.f.source)
        base,_,_=self.f.revision_fixture();path=base/'.product-v2/run.json'
        bad=read_json(path);bad['web_module_policy']='unknown';write_json(path,bad)
        work=self.f.root/'bad-revision';work.mkdir();output=self.f.root/'bad-revision-output'
        with self.assertRaisesRegex(ValueError,'Unknown Web module policy'):
            prepare(work,output,'设备运行控制',self.f.source,base,revision_scope='package')
        self.assertFalse(output.exists())


if __name__=='__main__':unittest.main()
