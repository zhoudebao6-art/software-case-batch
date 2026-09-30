"""Regression checks for real-project and structured-output boundaries."""
import json
import unittest
from pathlib import Path

import test_caseflow as fixtures
from test_caseflow import FakeExecutor, flow, put


class ContractTests(unittest.TestCase):
    setUp = fixtures.CaseflowTests.setUp
    tearDown = fixtures.CaseflowTests.tearDown
    make_source = fixtures.CaseflowTests.make_source
    run_fake = fixtures.CaseflowTests.run_fake
    def test_strict_review_schema(self):
        schema = json.loads((Path(__file__).resolve().parents[1] / 'schemas/review-verdict.schema.json').read_text(encoding='utf-8'))
        def visit(node):
            if isinstance(node, dict):
                if node.get('type') == 'object':
                    self.assertIs(node.get('additionalProperties'), False)
                    self.assertEqual(set(node.get('required', [])), set(node.get('properties', {})))
                for value in node.values():
                    visit(value)
            elif isinstance(node, list):
                for value in node:
                    visit(value)
        visit(schema)

    def test_snapshot_empty_source_and_dependency_pruning(self):
        case = self.root / 'working'
        put(case / 'backend/__init__.py', b'')
        put(case / 'frontend/node_modules/library/ignore.js', b'dependency')
        put(case / '.venv/ignore.py', b'dependency')
        put(case / 'src/app.py', b'print(1)')
        files = flow.snapshot(case, video=False)
        self.assertIn('backend/__init__.py', files)
        self.assertIn('src/app.py', files)
        self.assertFalse(any('node_modules' in p or '.venv' in p for p in files))

    def test_declared_test_logs_are_bound_without_tracking_worker_logs(self):
        case = self.root / 'working'
        flow.atomic_json(case / 'evidence/artifact-manifest.json', {'test_report': 'evidence/tests.json'})
        flow.atomic_json(case / 'evidence/tests.json', {'tests': [
            {'command': 'calculation-check', 'exit_code': 0, 'log': 'logs/calculation.log'}]})
        put(case / 'logs/calculation.log', b'calculation passed')
        put(case / 'logs/worker.jsonl', b'ongoing model output')
        for video in (False, True):
            before = flow.snapshot(case, video=video)
            self.assertEqual(before.get('logs/calculation.log'), flow.sha256(case / 'logs/calculation.log'))
            self.assertNotIn('logs/worker.jsonl', before)
            put(case / 'logs/worker.jsonl', b'additional model output')
            self.assertEqual(before, flow.snapshot(case, video=video))
        put(case / 'logs/calculation.log', b'changed test evidence')
        self.assertNotEqual(before, flow.snapshot(case, video=True))

    def test_real_log_directory_test_evidence_reaches_independent_review(self):
        self.make_source()
        flow.plan(self.cfg, self.source)
        self.cfg['runner'].update(review_mode='combined_final')
        fake = FakeExecutor()
        def executor(cfg, case, stage, context, output=None):
            rec = fake(cfg, case, stage, context, output)
            if stage == 'build':
                report_file = case / 'evidence/verification.json'
                report = flow.read_json(report_file)
                report['tests'][0]['log'] = 'logs/calculation.log'
                put(case / 'logs/calculation.log', b'actual fixture calculation output')
                flow.atomic_json(report_file, report)
            return rec
        state = self.run_fake(executor)['cases'][0]
        self.assertEqual(state['stage'], 'delivered', state.get('reason'))
        self.assertIn('logs/calculation.log', state['final_review']['snapshot_files'])

    def test_pass_with_major_issue_is_rejected(self):
        files = {'plot.png': 'abc'}
        report = {'verdict': 'pass', 'issues': [{'severity': 'major', 'artifact': 'plot.png', 'evidence': 'overlap', 'fix': 'move legend'}],
                  'coverage': 'fixture', 'limitations': [],
                  'reviewed_files': [{'path': 'plot.png', 'sha256': 'abc'}], 'snapshot_sha256': flow.snapshot_id(files)}
        with self.assertRaises(flow.Blocked):
            flow.verify_review(report, files, set(files))

    def test_foreign_output_blocks_before_model(self):
        self.make_source()
        m = flow.plan(self.cfg, self.source)
        output = Path(m['output_root'])
        put(output / 'existing.txt', b'do not overwrite')
        execute = FakeExecutor()
        with self.assertRaises(flow.Blocked):
            flow.run_batch(self.cfg, m['batch_id'], executor=execute)
        self.assertEqual(execute.stages, [])
        self.assertEqual((output / 'existing.txt').read_bytes(), b'do not overwrite')

    def test_repeated_early_failure_keeps_recovery_checkpoint(self):
        self.make_source()
        m = flow.plan(self.cfg, self.source)
        def unavailable(*args, **kwargs):
            raise OSError('fixture unavailable')
        for _ in range(2):
            state = self.run_fake(unavailable)['cases'][0]
            self.assertEqual(state['previous_stage'], 'new')
        recovered = self.run_fake(FakeExecutor())['cases'][0]
        self.assertEqual(recovered['stage'], 'delivered', recovered.get('reason'))

    def test_mechanical_csv_error_is_repaired(self):
        self.make_source()
        flow.plan(self.cfg, self.source)
        fake = FakeExecutor()
        def executor(cfg, case, stage, context, output=None):
            result = fake(cfg, case, stage, context, output)
            if stage == 'build':
                put(case / 'exports/fig.csv', b'x,y\n')
            if stage == 'repair_visual' and context.get('mechanical_validation_error'):
                put(case / 'exports/fig.csv', b'x,y\n1,2\n3,4\n')
                design_path = case / 'evidence/chart-design.json'
                design = flow.read_json(design_path)
                design['figures'][0]['csv_sha256'] = flow.sha256(case / 'exports/fig.csv')
                flow.atomic_json(design_path, design)
            return result
        state = self.run_fake(executor)['cases'][0]
        self.assertEqual(state['stage'], 'delivered', state.get('reason'))
        self.assertEqual(state['repairs_visual'], 1)

    def test_malformed_manifest_can_reach_repair_worker(self):
        self.make_source()
        flow.plan(self.cfg, self.source)
        fake = FakeExecutor()
        saved = {}
        def executor(cfg, case, stage, context, output=None):
            if stage == 'repair_visual' and context.get('mechanical_validation_error'):
                self.assertTrue(context['artifact_manifest_error'])
                self.assertIsNone(context['artifact_manifest'])
                flow.atomic_json(case / 'evidence/artifact-manifest.json', saved['manifest'])
            result = fake(cfg, case, stage, context, output)
            if stage == 'build':
                path = case / 'evidence/artifact-manifest.json'
                saved['manifest'] = flow.read_json(path)
                path.write_text('{broken-json', encoding='utf-8')
            return result
        state = self.run_fake(executor)['cases'][0]
        self.assertEqual(state['stage'], 'delivered', state.get('reason'))
        self.assertEqual(state['repairs_visual'], 1)

    def test_partial_video_gets_regenerated(self):
        self.make_source()
        flow.plan(self.cfg, self.source)
        fake = FakeExecutor()
        def executor(cfg, case, stage, context, output=None):
            if stage == 'repair_video' and context.get('mechanical_validation_error'):
                result = fake(cfg, case, 'video', context, output)
                result['stage'] = stage
                return result
            result = fake(cfg, case, stage, context, output)
            if stage == 'video':
                (case / 'recording/evidence/timeline.json').unlink()
            return result
        state = self.run_fake(executor)['cases'][0]
        self.assertEqual(state['stage'], 'delivered', state.get('reason'))
        self.assertEqual(state['repairs_video'], 1)

    def test_corrupt_png_and_later_csv_row_rejected(self):
        bad = self.root / 'bad.png'
        bad.write_bytes(b'\x89PNG\r\n\x1a\ninvalid')
        self.assertFalse(flow.good_image(bad))
        csv = self.root / 'bad.csv'
        csv.write_text('x,y\n1,2\n3\n')
        self.assertFalse(flow.good_csv(csv))

    def test_duplicate_render_pages_rejected(self):
        self.make_source()
        m = flow.plan(self.cfg, self.source)
        self.run_fake(FakeExecutor())
        case = flow.case_workspace(flow.batch_folder(self.cfg, m), m['cases'][0])
        manifest = case / 'evidence/artifact-manifest.json'
        a = flow.read_json(manifest)
        a['rendered_pages'] *= 2
        flow.atomic_json(manifest, a)
        with self.assertRaisesRegex(flow.Blocked, 'Repeated rendered_pages'):
            flow.validate_manifest(case, m['cases'][0]['source_sha256'], video=False, cfg=self.cfg)
