"""Catch mechanical mistakes inside construction, before expensive render/review."""
import unittest
from unittest.mock import patch

import test_chart_quality as quality
import caseflow as flow


class BuildPreflightTests(unittest.TestCase):
    setUp = quality.ChartQualityTests.setUp
    tearDown = quality.ChartQualityTests.tearDown
    make_source = quality.ChartQualityTests.make_source
    build = quality.ChartQualityTests.build

    def test_all_bad_fields_are_named_in_one_diagnostic(self):
        case, digest, manifest = self.build()
        design = flow.read_json(case / manifest['chart_design'])
        design['figures'][0]['calculation_basis'] = {'formula': 'F01'}
        design['figures'][1]['scenario_coverage'] = ''
        design['figures'][1]['explanation_outline']['reading'] = []
        flow.atomic_json(case / manifest['chart_design'], design)
        with self.assertRaises(flow.Blocked) as caught:
            flow.validate_manifest(case, digest, video=False, cfg=self.cfg)
        for field in ('calculation_basis', 'scenario_coverage', 'reading'):
            self.assertIn(field, str(caught.exception))

    def test_preflight_needs_no_renderer_video_or_model(self):
        from build_preflight import check
        case, digest, manifest = self.build()
        manifest.pop('rendered_pages')
        manifest.pop('render_report')
        flow.atomic_json(case / 'evidence/artifact-manifest.json', manifest)
        with patch('build_preflight.verify', return_value={
            'structural_preservation_ok': True, 'all_requested_figures_embedded': True,
            'all_requested_figures_at_document_end': True,
            'all_requested_figures_referenced_in_body': True}), patch.object(flow, 'invoke') as model:
            result = check(case, self.source / 'a.docx', source_hash=digest)
        self.assertTrue(result['ok'], result)
        self.assertEqual(result['independent_review'], 'not_performed')
        model.assert_not_called()

    def test_preflight_aggregates_word_and_contract_failures(self):
        from build_preflight import check
        case, digest, manifest = self.build()
        design = flow.read_json(case / manifest['chart_design'])
        design['figures'][0]['calculation_basis'] = {}
        flow.atomic_json(case / manifest['chart_design'], design)
        with patch('build_preflight.verify', return_value={
            'structural_preservation_ok': True, 'all_requested_figures_embedded': True,
            'all_requested_figures_at_document_end': False,
            'all_requested_figures_referenced_in_body': False}):
            result = check(case, self.source / 'a.docx', source_hash=digest)
        self.assertFalse(result['ok'])
        self.assertIn('calculation_basis', str(result['errors']))
        self.assertIn('all_requested_figures_at_document_end', str(result['errors']))
        self.assertIn('all_requested_figures_referenced_in_body', str(result['errors']))
