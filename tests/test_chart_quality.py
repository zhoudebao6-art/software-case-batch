"""Quality gates: counting files must not stand in for reviewing figures."""
import copy
import unittest
from unittest.mock import patch
import test_caseflow as fixtures
from test_caseflow import flow, FakeExecutor, put


class ChartQualityTests(unittest.TestCase):
    setUp = fixtures.CaseflowTests.setUp
    tearDown = fixtures.CaseflowTests.tearDown
    make_source = fixtures.CaseflowTests.make_source

    def build(self):
        src = self.make_source()
        case = self.root / 'case'
        case.mkdir()
        digest = flow.sha256(src)
        FakeExecutor()(self.cfg, case, 'build', {'source_docx': str(src), 'source_sha256': digest, 'case_name': 'case'})
        return case, digest, flow.read_json(case / 'evidence/artifact-manifest.json')

    def test_one_figure_cannot_satisfy_a_case(self):
        case, digest, manifest = self.build()
        manifest['charts'] = manifest['charts'][:1]
        flow.atomic_json(case / 'evidence/artifact-manifest.json', manifest)
        with self.assertRaisesRegex(flow.Blocked, 'at least two'):
            flow.validate_manifest(case, digest, video=False, cfg=self.cfg)

    def test_duplicate_figure_is_not_a_second_figure(self):
        case, digest, manifest = self.build()
        manifest['charts'] = [manifest['charts'][0], copy.deepcopy(manifest['charts'][0])]
        flow.atomic_json(case / 'evidence/artifact-manifest.json', manifest)
        with self.assertRaisesRegex(flow.Blocked, 'Duplicate chart'):
            flow.validate_manifest(case, digest, video=False, cfg=self.cfg)

    def test_missing_chart_design_is_not_review_ready(self):
        case, digest, manifest = self.build()
        manifest.pop('chart_design', None)
        flow.atomic_json(case / 'evidence/artifact-manifest.json', manifest)
        with self.assertRaisesRegex(flow.Blocked, 'chart_design'):
            flow.validate_manifest(case, digest, video=False, cfg=self.cfg)

    def test_two_charts_without_formula_ids_are_valid(self):
        case, digest, manifest = self.build()
        self.assertTrue(all(c['formula_ids'] == [] for c in manifest['charts']))
        flow.validate_manifest(case, digest, video=False, cfg=self.cfg)
        self.assertGreaterEqual(len(manifest['charts']), 2)

    def review_fixture(self):
        case, _, manifest = self.build()
        files = flow.snapshot(case, video=False)
        out = self.root / 'review.json'
        FakeExecutor()(self.cfg, case, 'review_visual', {'artifact_manifest': manifest,
            'snapshot_files': files, 'snapshot_sha256': flow.snapshot_id(files), 'required_review_files': sorted(files)}, out)
        return flow.read_json(out), files, manifest

    def test_current_review_protocol_accepts_complete_evidence(self):
        report, files, manifest = self.review_fixture()
        self.assertEqual(flow.verify_review(report, files, set(files), manifest=manifest), 'pass')

    def test_overall_pass_cannot_override_bad_figure(self):
        report, files, manifest = self.review_fixture()
        report['chart_reviews'][0]['checks']['meaning'] = {'passed': False, 'evidence': 'Boolean truth table disguised as bars.'}
        with self.assertRaisesRegex(flow.Blocked, 'failed chart'):
            flow.verify_review(report, files, set(files), manifest=manifest)

    def test_review_must_cover_every_figure(self):
        report, files, manifest = self.review_fixture()
        report['chart_reviews'].pop()
        with self.assertRaisesRegex(flow.Blocked, 'every chart'):
            flow.verify_review(report, files, set(files), manifest=manifest)

    def test_large_png_only_does_not_prove_normal_size_legibility(self):
        report, files, manifest = self.review_fixture()
        c = manifest['charts'][0]
        report['chart_reviews'][0]['evidence_files'] = [c['png'], c['csv'], c['explanation']]
        with self.assertRaisesRegex(flow.Blocked, 'normal-size'):
            flow.verify_review(report, files, set(files), manifest=manifest)

    def test_changed_explanation_invalidates_design_evidence(self):
        case, digest, manifest = self.build()
        (case / manifest['charts'][0]['explanation']).write_text('Changed result', encoding='utf-8')
        with self.assertRaisesRegex(flow.Blocked, 'chart_design.*stale'):
            flow.validate_manifest(case, digest, video=False, cfg=self.cfg)

    def test_user_rejected_png_is_blocked_even_with_new_metadata(self):
        case, digest, manifest = self.build()
        catalog = self.root / 'rejected.json'
        flow.atomic_json(catalog, {'versions': [{'sha256': flow.sha256(case / manifest['charts'][0]['png']),
            'reason': 'Explicit user rejection', 'evidence': 'user-feedback.md'}]})
        with patch.object(flow, 'REJECTED_CHART_FILE', catalog, create=True):
            with self.assertRaisesRegex(flow.Blocked, 'Explicitly rejected chart'):
                flow.validate_manifest(case, digest, video=False, cfg=self.cfg)

    def test_professional_chart_set_has_a_six_figure_cap(self):
        case, digest, manifest = self.build()
        design = flow.read_json(case / manifest['chart_design'])
        design['quality_addenda'] = ['2026-09-28-professional-charts']
        extra = []
        for index in range(3, 8):
            png = f'exports/fig-{index}.png'; csv = f'exports/fig-{index}.csv'; explanation = f'exports/fig-{index}.md'
            put(case / png, fixtures.PNG + str(index).encode())
            put(case / csv, f'x,y\n1,{index}\n'.encode())
            put(case / explanation, f'Figure {index}'.encode())
            extra.append({'figure_id': f'fig-{index}', 'formula_ids': [], 'snapshot_id': 'fixture-1',
                          'png': png, 'csv': csv, 'explanation': explanation})
        manifest['charts'].extend(extra)
        for item in extra:
            design['figures'].append({'figure_id': item['figure_id'],
                **{k + '_sha256': flow.sha256(case / item[k]) for k in ('png', 'csv', 'explanation')},
                **{k: 'Fixture' for k in ('business_question', 'reader_takeaway', 'chart_type', 'selection_reason', 'scenario_coverage', 'calculation_basis')},
                'explanation_outline': {k: 'Fixture' for k in ('purpose', 'reading', 'calculation', 'findings', 'decision')}})
        flow.atomic_json(case / manifest['chart_design'], design)
        flow.atomic_json(case / 'evidence/artifact-manifest.json', manifest)
        with self.assertRaisesRegex(flow.Blocked, 'six independent result figures'):
            flow.validate_manifest(case, digest, video=False, cfg=self.cfg)

    def test_professional_diagram_type_is_blocked_early(self):
        case, digest, manifest = self.build()
        design = flow.read_json(case / manifest['chart_design'])
        design['quality_addenda'] = ['2026-09-28-professional-charts']
        design['figures'][0]['chart_type'] = '流程图'
        flow.atomic_json(case / manifest['chart_design'], design)
        with self.assertRaisesRegex(flow.Blocked, 'diagrammatic'):
            flow.validate_manifest(case, digest, video=False, cfg=self.cfg)


if __name__ == '__main__':
    unittest.main()
