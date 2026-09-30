"""Output-focused pipeline: no model/network calls and no live case mutation."""
import copy
import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import test_caseflow as fixtures
import test_chart_quality as quality
import caseflow as flow
from capture_runner import CaptureError, validate_plan


class OutputRouteTests(unittest.TestCase):
    setUp = fixtures.CaseflowTests.setUp
    tearDown = fixtures.CaseflowTests.tearDown
    make_source = fixtures.CaseflowTests.make_source

    def test_new_builder_route_keeps_high_and_review_route(self):
        cfg = flow.read_json(self.config_path)
        cfg['models']['builder']['model'] = 'gpt-6.1-sol'
        cfg['models']['repairer'] = {'model': 'gpt-6.1-sol', 'reasoning_effort': 'ultra'}
        cfg['runner']['pipeline_profile'] = 'deliverable-first-v1'
        flow.atomic_json(self.config_path, cfg)
        loaded = flow.config_at(self.config_path)
        case = self.root / 'case'; case.mkdir()
        for stage in ('build', 'repair_visual', 'repair_final', 'prepare_video'):
            command = flow.command_for(loaded, case, stage, dry_run=True)
            self.assertIn('gpt-6.1-sol', command)
            expected = 'high' if stage == 'build' else 'ultra'
            self.assertIn('model_reasoning_effort=' + expected, command)
        command = flow.command_for(loaded, case, 'review_final', self.root / 'review.json', dry_run=True)
        self.assertIn('gpt-6-sol', command)
        self.assertIn('model_reasoning_effort=ultra', command)
        cfg['models']['builder']['reasoning_effort'] = 'low'
        flow.atomic_json(self.config_path, cfg)
        with self.assertRaises(flow.Blocked): flow.config_at(self.config_path)

    def test_new_default_does_not_migrate_registered_batches(self):
        self.make_source(); old = flow.plan(self.cfg, self.source)
        self.cfg['runner']['pipeline_profile'] = 'deliverable-first-v1'
        self.assertEqual(flow.plan(self.cfg, self.source)['pipeline_profile'], 'legacy')
        other = self.root / 'new'; other.mkdir(); fixtures.docx(other / 'b.docx')
        fresh = flow.plan(self.cfg, other)
        self.assertEqual(fresh['pipeline_profile'], 'deliverable-first-v1')
        cmds = flow.run_batch(self.cfg, fresh['batch_id'], dry_run=True)['cases'][0]['commands']
        self.assertNotIn('video', cmds)
        self.assertIsNone(cmds['capture_video']['model'])

    def test_new_prompts_remove_full_system_scope_and_keep_complete_shell(self):
        cfg = dict(self.cfg, _prompts=Path(__file__).resolve().parents[1] / 'prompts')
        cfg['models']['builder']['model'] = 'gpt-6.1-sol'
        for stage in ('build', 'repair_final', 'prepare_video', 'review_final'):
            old = flow.prompt(cfg, stage, {'pipeline_profile': 'efficient-v1'})
            new = flow.prompt(cfg, stage, {'pipeline_profile': 'deliverable-first-v1'})
            self.assertNotIn('完整后端与业务UI', new)
            self.assertNotIn('完整系统和关键交互要有实际验证证据', new)
            self.assertIn('完整侧栏/导航', new)
            self.assertIn('其他模块可以暂时留空', new)
            self.assertIn('gpt-6.1-sol/high', new)

    def test_parent_uses_script_capture_once_across_document_chart_repair(self):
        self._script_capture_fixture()

    def test_bad_capture_plan_can_be_repaired_before_recording(self):
        self._script_capture_fixture(bad_initial_plan=True)

    def _script_capture_fixture(self, bad_initial_plan=False):
        self.cfg['runtime'] = fixtures.fake_runtime(self.root)
        self.cfg['runner'].update(pipeline_profile='deliverable-first-v1', review_mode='combined_final')
        self.cfg['models']['builder']['model'] = 'gpt-6.1-sol'
        self.cfg['models']['repairer'] = {'model': 'gpt-6.1-sol', 'reasoning_effort': 'ultra'}
        self.make_source(); batch = flow.plan(self.cfg, self.source)
        fake = fixtures.FakeExecutor(revise_visual=True); contexts = {}
        def execute(cfg, case, stage, context, output=None):
            contexts[str(case)] = context
            result = fake(cfg, case, stage, context, output)
            if stage in ('build', 'prepare_video'):
                fixtures.put(case / 'web/app.js', b'fixture recording app')
                fixtures.put(case / 'data/scene.json', b'{"value":1}')
                flow.atomic_json(case / 'evidence/capture-plan.json', {
                    'schema_version': 2, 'case_id': context['case_id'], 'version': 'fixture',
                    'base_url': 'http://127.0.0.1:' + str(context['case_resources']['ports'][0]), 'health_path': '/health',
                    'application_files': {'web/app.js': flow.sha256(case / 'web/app.js')},
                    'scene_data_files': {'data/scene.json': flow.sha256(case / 'data/scene.json')},
                    'modules': [{'name': 'A', 'heading': 'A', 'route': '/a', 'ready_selectors': ['#ready']},
                                {'name': 'B', 'heading': 'B', 'route': '/b', 'ready_selectors': ['#ready'], 'enter_selector': '#b'}]})
                if bad_initial_plan and stage == 'build':
                    plan = flow.read_json(case / 'evidence/capture-plan.json')
                    plan['schema_version'] = 1
                    flow.atomic_json(case / 'evidence/capture-plan.json', plan)
            if stage == 'review_final':
                report = flow.read_json(output)
                for chart in report['chart_reviews']:
                    chart['evidence_files'] = [p for p in chart['evidence_files'] if p != 'evidence/ui/overview.png']
                for issue in report['issues']: issue['artifact'] = 'exports/fig.png'
                flow.atomic_json(output, report)
            if stage == 'repair_final':
                fixtures.put(case / 'exports/fig.png', fixtures.PNG + b'fixed Word-only figure')
                design = flow.read_json(case / 'evidence/chart-design.json')
                design['figures'][0]['png_sha256'] = flow.sha256(case / 'exports/fig.png')
                flow.atomic_json(case / 'evidence/chart-design.json', design)
            return result
        def scripted(cfg, case, cid, resources):
            fake(cfg, case, 'video', contexts[str(case)])
            return {'video_sha256': flow.current_video_hash(case), 'duration_seconds': .01,
                    'mode': 'record', 'raw_video': 'fixture-only.webm'}
        def process(args, **kwargs):
            value = {'files': {}, 'manifest_fields': {}} if any('controlled_evidence.py' in str(a) for a in args) else {
                'format': {'duration': '8.0'}, 'streams': [{'codec_name': 'h264', 'width': 1920, 'height': 1080, 'avg_frame_rate': '30/1'}]}
            return SimpleNamespace(returncode=0, stdout=json.dumps(value), stderr='')
        with patch.object(flow, 'invoke', execute), patch.object(flow, 'native_codex'), \
             patch.object(flow.subprocess, 'run', side_effect=process), \
             patch('capture_runner.service_ready', return_value={}), patch('capture_runner.capture', side_effect=scripted):
            state = flow.run_batch(self.cfg, batch['batch_id'], executor=execute)['cases'][0]
        self.assertEqual(state['stage'], 'delivered', state.get('reason'))
        self.assertEqual([c['stage'] for c in state['script_calls']], ['capture_video'])
        expected = ['build', 'prepare_video'] if bad_initial_plan else ['build']
        self.assertEqual([c['stage'] for c in state['calls']], expected + ['review_final', 'repair_final', 'review_final'])
        self.assertEqual(next(c for c in state['calls'] if c['stage'] == 'repair_final')['model'], 'gpt-6.1-sol')
        self.assertEqual(next(c for c in state['calls'] if c['stage'] == 'repair_final')['reasoning_effort'], 'ultra')


class SceneDependenciesTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.case = Path(self.tmp.name).resolve()
        for directory in ('evidence', 'exports', 'web', 'data', 'deliverable'):
            (self.case / directory).mkdir()
        for name in ('web/app.js', 'data/scene.json', 'exports/figure.png', 'evidence/ui.png', 'deliverable/out.docx'):
            (self.case / name).write_text('initial')
        self.plan = {'schema_version': 2, 'case_id': 'case', 'base_url': 'http://127.0.0.1:12345',
                     'health_path': '/health', 'version': 'v1',
                     'application_files': {'web/app.js': flow.sha256(self.case / 'web/app.js')},
                     'scene_data_files': {'data/scene.json': flow.sha256(self.case / 'data/scene.json')},
                     'modules': [{'name': 'Tasks', 'route': '/tasks', 'heading': 'Tasks', 'ready_selectors': ['#ready']},
                                 {'name': 'Results', 'route': '/results', 'heading': 'Results', 'ready_selectors': ['#ready'], 'enter_selector': '#results'}]}
        self.save()
        flow.atomic_json(self.case / 'evidence/artifact-manifest.json', {'charts': [{'png': 'exports/figure.png'}], 'ui_screenshots': ['evidence/ui.png']})

    def tearDown(self): self.tmp.cleanup()
    def save(self): flow.atomic_json(self.case / 'evidence/capture-plan.json', self.plan)
    def inputs(self): return flow.recording_inputs(self.case, pipeline_profile='deliverable-first-v1')

    def test_docx_only_chart_and_new_evidence_do_not_invalidate_video(self):
        before = self.inputs()
        for name in ('exports/figure.png', 'evidence/ui.png', 'deliverable/out.docx'):
            (self.case / name).write_text('improved document/evidence')
        self.assertEqual(before, self.inputs())

    def test_visible_code_data_and_route_changes_invalidate_video(self):
        before = self.inputs()
        for name in ('web/app.js', 'data/scene.json'):
            p = self.case / name; old = p.read_text(); p.write_text('new visible result')
            self.assertNotEqual(before, self.inputs()); p.write_text(old)
        self.plan['modules'][1]['route'] = '/new-results'; self.save()
        self.assertNotEqual(before, self.inputs())

    def test_a_chart_used_by_recorded_page_is_tracked(self):
        self.plan['scene_data_files']['exports/figure.png'] = flow.sha256(self.case / 'exports/figure.png'); self.save()
        before = self.inputs(); (self.case / 'exports/figure.png').write_text('changed visible chart')
        self.assertNotEqual(before, self.inputs())

    def test_missing_or_escaped_scene_input_is_not_silently_ignored(self):
        for files in ({}, {'../foreign.json': '0' * 64}, {'data/missing.json': '0' * 64}):
            self.plan['scene_data_files'] = files; self.save()
            with self.assertRaises((flow.Blocked, CaptureError)): self.inputs()

    def test_two_distinct_scenes_and_frozen_data_required(self):
        self.assertEqual(validate_plan(self.case, 'case', [12345]), self.plan)
        original = copy.deepcopy(self.plan)
        for mutate in (lambda p: p.update(modules=p['modules'][:1]),
                       lambda p: p['modules'][1].update(route='/tasks'),
                       lambda p: p.update(scene_data_files={}),
                       lambda p: p['scene_data_files'].update({'data/scene.json': '0' * 64})):
            self.plan = copy.deepcopy(original); mutate(self.plan); self.save()
            with self.assertRaises(CaptureError): validate_plan(self.case, 'case', [12345])

    def test_malformed_route_is_reported_as_a_capture_error(self):
        self.plan['modules'][1]['route'] = ['/results']; self.save()
        with self.assertRaises((flow.Blocked, CaptureError)): self.inputs()

    def test_legacy_change_detection_remains_conservative(self):
        before = flow.recording_inputs(self.case)
        (self.case / 'exports/figure.png').write_text('changed')
        self.assertNotEqual(before, flow.recording_inputs(self.case))


class StatusSummaryTests(unittest.TestCase):
    def test_status_keeps_control_fields_but_not_full_transcripts(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / 'state.json'
            state = {'case_id': 'case', 'stage': 'built', 'active_stage': 'video', 'reason': None,
                     'calls': [{'stage': 'build', 'exit_code': 0, 'final_message': 'x' * 1000000}],
                     'final_review': {'verdict': 'revise', 'snapshot_files': {'a': 'x' * 1000000}}}
            flow.atomic_json(path, state)
            summary = flow.compact_case_state(state, path)
            self.assertEqual(summary['active_stage'], 'video')
            self.assertEqual(summary['call_count'], 1)
            self.assertEqual(summary['state_file'], str(path))
            self.assertLess(len(json.dumps(summary)), 5000)
            self.assertEqual(flow.read_json(path), state)


class WordOnlyChartReviewTests(unittest.TestCase):
    setUp = fixtures.CaseflowTests.setUp
    tearDown = fixtures.CaseflowTests.tearDown
    make_source = fixtures.CaseflowTests.make_source
    build = quality.ChartQualityTests.build
    review_fixture = quality.ChartQualityTests.review_fixture

    def test_word_chart_needs_word_evidence_without_per_chart_web_evidence(self):
        report, files, manifest = self.review_fixture()
        for chart in report['chart_reviews']:
            chart['evidence_files'] = [p for p in chart['evidence_files'] if p not in manifest['ui_screenshots']]
        self.assertEqual(flow.verify_review(report, files, set(files), manifest=manifest,
                                           pipeline_profile='deliverable-first-v1'), 'pass')
        with self.assertRaisesRegex(flow.Blocked, 'normal-size'):
            flow.verify_review(report, files, set(files), manifest=manifest)
        chart = report['chart_reviews'][0]
        chart['evidence_files'] = [p for p in chart['evidence_files'] if p not in manifest['rendered_pages']]
        with self.assertRaisesRegex(flow.Blocked, 'normal-size'):
            flow.verify_review(report, files, set(files), manifest=manifest, pipeline_profile='deliverable-first-v1')

    def test_evidence_id_binding_keeps_global_ui_coverage(self):
        report, files, manifest = self.review_fixture()
        required = set(files)
        request = flow.review_request(files, required)
        ids = {p: i for i, p in request['evidence'].items()}
        raw = {k: report[k] for k in ('verdict', 'issues', 'coverage', 'limitations')}
        raw.update(protocol=request['protocol'], review_id=request['review_id'], reviewed_evidence=list(ids.values()),
                   chart_reviews=[{'figure_id': c['figure_id'], 'checks': c['checks'],
                                   'evidence_ids': [ids[p] for p in c['evidence_files'] if p not in manifest['ui_screenshots']]}
                                  for c in report['chart_reviews']])
        bound = flow.bind_review_response(raw, request, files, required, manifest, pipeline_profile='deliverable-first-v1')
        self.assertEqual(bound['verdict'], 'pass')
        raw['reviewed_evidence'].remove(ids[manifest['ui_screenshots'][0]])
        with self.assertRaisesRegex(flow.Blocked, 'required evidence'):
            flow.bind_review_response(raw, request, files, required, manifest, pipeline_profile='deliverable-first-v1')


if __name__ == '__main__': unittest.main()
