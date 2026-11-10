"""Existing first-review coverage, no new audit round or production fixtures."""
import copy
import unittest
from PIL import Image
from common import digest, read_json, write_json
from evidence_index import validate_review_coverage
from review_packet import draft
from system_diagrams import POLICY, LEGACY_POLICY, validate_affected_review, validate_first_notes
import test_review_coverage as fixtures


class SystemDiagramReviewTests(unittest.TestCase):
    setUp = fixtures.ReviewCoverageTests.setUp
    prepared = fixtures.ReviewCoverageTests.prepared
    rewrite_index = fixtures.ReviewCoverageTests.rewrite_index

    def diagrams(self, include=True, policy=POLICY):
        self.run['system_diagram_policy']=policy
        write_json(self.control/'run.json',self.run)
        self.diagram_paths=[]
        for name,color in [('设计图','navy'),('时序图','green')]:
            path=self.work/(name+'.png')
            Image.new('RGB',(400,300),color).save(path)
            (self.out/'模拟系统'/path.name).write_bytes(path.read_bytes())
            self.diagram_paths.append(path.name)
        if include:
            manifest=read_json(self.manifest)
            manifest['files']+=self.diagram_paths
            write_json(self.manifest,manifest)

    def test_missing_diagrams_fail_before_review_without_creating_partial_draft(self):
        self.diagrams(False)
        report=draft(self.work,self.execution,self.target,manifest=self.manifest)
        self.assertEqual(report['status'],'blocked')
        self.assertTrue(any('System diagram missing' in e['message'] for e in report['errors']))
        self.assertFalse(self.target.exists())

    def test_current_final_pngs_join_existing_required_ids_without_marking_read(self):
        self.diagrams();proof,stage=self.prepared()
        rows={r['path']:r for r in self.spec['evidence']}
        for name in self.diagram_paths:
            self.assertIn(rows[name]['id'],self.spec['required_evidence'])
            self.assertEqual(rows[name]['sha256'],digest(self.out/'模拟系统'/name))
        self.assertEqual(read_json(self.target/'review-draft.json')['reviewed_evidence'],[])
        for current in (True,False):
            self.assertTrue(validate_review_coverage(self.work,self.run,proof,stage,current=current)['required'])

    def test_unread_or_removed_system_diagram_cannot_be_hidden_in_frozen_review(self):
        self.diagrams();proof,stage=self.prepared()
        row=next(r for r in self.spec['evidence'] if r['path']=='设计图.png')
        unread=copy.deepcopy(proof);unread['reviewed_evidence'].remove(row['id'])
        for current in (True,False):
            with self.assertRaises(ValueError):
                validate_review_coverage(self.work,self.run,unread,stage,current=current)
        spec=copy.deepcopy(self.spec);spec['required_evidence'].remove(row['id'])
        spec['evidence']=[r for r in spec['evidence'] if r['id']!=row['id']]
        self.rewrite_index(unread,stage,spec)
        for current in (True,False):
            with self.assertRaisesRegex(ValueError,'System diagram missing'):
                validate_review_coverage(self.work,self.run,unread,stage,current=current)

    def test_changed_output_cannot_reuse_an_old_workspace_render(self):
        self.diagrams()
        Image.new('RGB',(400,300),'red').save(self.out/'模拟系统/设计图.png')
        result=draft(self.work,self.execution,self.target,manifest=self.manifest)
        self.assertEqual(result['status'],'blocked')
        self.assertFalse(self.target.exists())

    def test_historical_v1_preserves_original_coverage(self):
        self.diagrams(False,LEGACY_POLICY);proof,stage=self.prepared()
        self.assertTrue(validate_review_coverage(self.work,self.run,proof,stage)['required'])

    def test_new_policy_cannot_omit_existing_coverage_contract(self):
        self.diagrams();self.run.pop('review_coverage_policy');write_json(self.control/'run.json',self.run)
        result=draft(self.work,self.execution,self.target,manifest=self.manifest)
        self.assertEqual(result['status'],'blocked')
        self.assertTrue(any('existing first-review' in e['message'] for e in result['errors']))

    def test_targeted_fix_reuses_unchanged_diagram_and_requires_only_changed_visual(self):
        self.diagrams();proof,stage=self.prepared()
        artifacts=proof['reviewed_files'];name='模拟系统/设计图.png'
        validate_affected_review(self.run,artifacts,[],{})
        with self.assertRaisesRegex(ValueError,'affected visual'):
            validate_affected_review(self.run,artifacts,[name],{})
        check={'artifact_hashes':{name:artifacts[name]},'exit_code':0,'visual_notes':['Checked corrected arrow direction against source paragraph.']}
        validate_affected_review(self.run,artifacts,[name],{'diagram_visual':check})
        for notes in (True,123,{},[' '],' ',['Not viewed']):
            with self.subTest(notes=notes),self.assertRaises(ValueError):
                validate_affected_review(self.run,artifacts,[name],{'diagram_visual':dict(check,visual_notes=notes)})
        check['artifact_hashes'][name]='0'*64
        with self.assertRaises(ValueError):validate_affected_review(self.run,artifacts,[name],{'diagram_visual':check})

    def test_first_review_cannot_use_boolean_in_place_of_visual_findings(self):
        for notes in (True,123,{},[' '],' '):
            with self.subTest(notes=notes),self.assertRaises(ValueError):
                validate_first_notes({'system_diagram_policy':POLICY},notes)
        validate_first_notes({'system_diagram_policy':POLICY},['Viewed source-linked actors, direction and return conditions.'])
        validate_first_notes({'system_diagram_policy':LEGACY_POLICY},True)


if __name__=='__main__':unittest.main()
