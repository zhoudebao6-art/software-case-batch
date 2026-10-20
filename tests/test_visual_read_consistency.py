"""Explicit missing visual reading cannot coexist with a submitted pass."""
import copy
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import test_contracts as fixtures
from contracts import chart_records, reject_unread_visual_evidence
from test_build_policy import figure


class VisualReadConsistencyTests(unittest.TestCase):
    def setUp(self):
        self.f = fixtures.ContractTests()
        self.f.setUp()

    def tearDown(self):
        self.f.tearDown()

    def test_ordinary_pass_rejects_explicit_unread_notes_and_flags(self):
        original = copy.deepcopy(self.f.proof)
        for field, value in [('visual_notes',['Word pages were not viewed.']),
                             ('limitations',['最终Word全部页未查看。']),
                             ('coverage','Word pages were not viewed.'),
                             ('unread_evidence',['E001']), ('visual_read_complete',False)]:
            with self.subTest(field=field):
                self.f.proof = copy.deepcopy(original)
                self.f.proof[field] = value
                self.f.save_proof()
                with self.assertRaisesRegex(ValueError, 'explicitly unread'):
                    self.f.verify_models()

    def test_ordinary_pass_rejects_unread_individual_chart_evidence(self):
        for field in ('layout','explanation'):
            with self.subTest(field=field):
                self.f.proof['chart_reviews'][0][field]['evidence'] = 'PNG was not viewed.'
                self.f.save_proof()
                with self.assertRaisesRegex(ValueError, 'explicitly unread'):
                    self.f.verify_models()

    def test_required_no_title_review_cannot_say_not_viewed(self):
        self.f.proof['chart_reviews'][0]['no_title_header_evidence'] = '图表未实际查看。'
        self.f.save_proof()
        with self.assertRaisesRegex(ValueError, 'explicitly unread'):
            self.f.verify_models()

    def test_legitimate_out_of_scope_deployment_limit_does_not_block_visual_reading(self):
        self.f.proof['visual_notes'] = ['已查看所有Word页面和PNG；原文及说明衔接一致。']
        self.f.proof['limitations'] = ['Production deployment was not reviewed; it is outside the scope.']
        self.f.save_proof()
        self.assertTrue(self.f.verify_models())
        reject_unread_visual_evidence({'visual_notes':['检查完全部PNG，结构校验不代表视觉保证。'],
                                      'limitations':['现场部署未检查，属于本案范围外。']})

    def test_new_chart_build_check_rejects_explicit_unread_despite_inspected_true(self):
        spec = {'figures':[figure(1,'baseline_result','monochrome')]+[figure(i) for i in (2,3,4)]}
        spec['figures'][0]['build_selfcheck']['visual_review']['evidence'] = 'PNG was not viewed.'
        with self.assertRaisesRegex(ValueError, 'actual visual self-check'):
            chart_records(spec, {'chart_policy':'analytical-v2'})

    def test_retained_result_build_check_rejects_explicit_unread(self):
        baseline = figure(1,'baseline_result','monochrome')
        spec = {'figures':[figure(i) for i in (2,3,4)], 'retained_results':[{
            'figure_id':1,'sha256':baseline['sha256'],'analysis_role':'baseline_result','palette':'monochrome',
            'result_reason':'原统计结果可定位并与当前问题一致。',
            'visual_review':{'inspected':True,'png_sha256':baseline['sha256'],'evidence':'原图未查看。'}}]}
        with self.assertRaisesRegex(ValueError, 'Actually inspect'):
            chart_records(spec, {'chart_policy':'analytical-v2'})


if __name__ == '__main__':
    unittest.main()
