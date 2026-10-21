"""Gate integration fixtures, not live case acceptance or browser evidence."""
import copy
from pathlib import Path
import sys
import unittest
import zipfile

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
from common import digest, read_json, write_json
from contracts import CONSTRUCTION_KINDS, CONSTRUCTION_POLICY, construction_checks
from evidence_index import _required_review_paths
from proflow import prepare
import test_web_contract as web_fixtures


class WebIntegrationTests(unittest.TestCase):
    file=web_fixtures.WebContractTests.file
    image=web_fixtures.WebContractTests.image
    assertion=web_fixtures.WebContractTests.assertion
    save=web_fixtures.WebContractTests.save
    def setUp(self):web_fixtures.WebContractTests.setUp(self)
    def tearDown(self):web_fixtures.WebContractTests.tearDown(self)
    def integrated(self):
        self.run['construction_check_policy_version']=CONSTRUCTION_POLICY
        control=self.work/'.product-v2';control.mkdir(exist_ok=True)
        write_json(control/'source-manifest.json',{'files':['app.py']})
        write_json(control/'record-plan.json',{'input_files':['app.py']})
        self.file('test_browser.py',b'# TEST_ONLY deterministic integration fixture')
        self.save()
        for kind in CONSTRUCTION_KINDS:
            inputs=(self.spec['checks']['browser']['input_files'].copy() if kind=='browser' else
                    {path:digest(self.work/path) for path in ('app.py','test_browser.py')})
            self.spec['checks'][kind]={'command':'TEST_ONLY fixture; no real execution',
                'exit_code':0,'log':'execution.log','sha256':digest(self.work/'execution.log'),
                'test_files':['test_browser.py'],'input_files':inputs}
        write_json(control/'build-checks.json',self.spec)
        return control

    def test_existing_construction_gate_enforces_current_web(self):
        control=self.integrated()
        checked=construction_checks(self.work,self.run)
        self.assertTrue(checked['web_experience']['required'])
        self.spec.pop('web_experience');write_json(control/'build-checks.json',self.spec)
        with self.assertRaisesRegex(ValueError,'web_experience'):
            construction_checks(self.work,self.run)

    def test_changed_or_missing_page_blocks_admission(self):
        self.integrated()
        self.file('screen.png',b'changed or damaged screenshot')
        with self.assertRaises(ValueError):construction_checks(self.work,self.run)

    def test_fresh_prepare_freezes_policy_and_generation_instructions(self):
        source=self.work/'technical.docx'
        with zipfile.ZipFile(source,'w') as package:
            package.writestr('word/document.xml','<document/>')
        work=self.work/'prepared';work.mkdir();out=self.work/'output'
        run=prepare(work,out,'检测工作台',source)
        self.assertEqual(run['web_experience_policy'],'case-workflow-v1')
        prompt=(work/'.product-v2/深化命令词.txt').read_text(encoding='utf-8')
        self.assertIn('三页',prompt);self.assertIn('合法真实图片',prompt)

    def test_frozen_review_requires_web_scope_and_all_paths_without_live_read(self):
        scope={'word':{'sha256':'1'*64,'page_count':1,'pages':[{'page':1,'path':'old-page.png'}]},
               'source_mappings':['old-map.json'],
               'video':{'timeline':{'path':'old-timeline.json'},
                        'contact_sheets':[{'path':'old-contact.png'}],
                        'endpoints':[{'type':'first','path':'old-first.png'},{'type':'last','path':'old-last.png'}],
                        'interaction_frames':[{'path':'old-action.png'}]}}
        run=dict(self.run,word_name='original.docx')
        with self.assertRaisesRegex(ValueError,'complete Web'):
            _required_review_paths(self.work,run,scope,[],{'original.docx':'1'*64},current=False)
        scope['web']={'policy':'case-workflow-v1','page_ids':['tasks'],'workflow_ids':['execute'],
                      'evidence_hashes':{'old-ui.png':'2'*64,'old-browser.json':'3'*64}}
        required,_=_required_review_paths(self.work,run,scope,[],{'original.docx':'1'*64},current=False)
        self.assertTrue({'old-ui.png','old-browser.json','.product-v2/build-checks.json'}.issubset(required))

    def test_document_only_revision_does_not_reopen_historical_web(self):
        run=dict(self.run,revision_of={'run_id':'prior'},revision_scope='document',word_name='original.docx')
        scope={'word':{'sha256':'1'*64,'page_count':1,'pages':[{'page':1,'path':'old-page.png'}]},
               'source_mappings':['old-map.json']}
        required,_=_required_review_paths(self.work,run,scope,[],{'original.docx':'1'*64},current=False)
        self.assertNotIn('.product-v2/build-checks.json',required)


if __name__=='__main__':unittest.main()
