"""Monthly names, real concurrent scheduling and shared resource gates."""
import json
import threading
import time
import unittest
from pathlib import Path
from unittest.mock import patch

import test_caseflow as fixtures
from test_caseflow import FakeExecutor, flow, put


class ParallelTests(unittest.TestCase):
    setUp = fixtures.CaseflowTests.setUp
    tearDown = fixtures.CaseflowTests.tearDown
    make_source = fixtures.CaseflowTests.make_source
    run_fake = fixtures.CaseflowTests.run_fake

    def configure(self):
        self.cfg['execution'] = {'case_concurrency': 3, 'review_concurrency': 1, 'recording_concurrency': 1, 'evidence_concurrency': 1}
        self.cfg['runner'].update(review_mode='combined_final', max_astra_calls_per_case=None, max_final_review_repairs=None)

    def test_monthly_named_workspaces_and_name_reservation_across_batches(self):
        self.make_source('技术项目优化说明书控制方法.docx')
        first = flow.plan(self.cfg, self.source)
        folder = flow.batch_folder(self.cfg, first)
        self.assertEqual(folder.parent.name, '.batches')
        case = flow.case_workspace(folder, first['cases'][0])
        self.assertEqual(case.name, '控制方法')
        self.assertEqual(case.parent.name, time.strftime('%Y-%m'))
        self.assertEqual(case.parent.parent, self.cfg['_root'])
        self.assertFalse(case.exists())
        other = self.root / 'second-batch'; other.mkdir()
        fixtures.docx(other / '技术项目优化说明书控制方法.docx')
        second = flow.plan(self.cfg, other)
        self.assertEqual(second['cases'][0]['workspace_name'], '控制方法（2）')
        self.assertEqual(flow.plan(self.cfg, self.source)['cases'], first['cases'])
        self.assertEqual(flow.load_batch(self.cfg, first['batch_id'])[1], folder)

    def test_windows_reserved_and_colliding_names(self):
        self.make_source('技术项目优化说明书+CON.docx')
        self.make_source('技术项目优化说明书+state.docx')
        self.make_source('技术项目优化说明书+控制.docx')
        self.make_source('技术项目优化说明书控制.docx')
        manifest = flow.plan(self.cfg, self.source)
        names = {e['workspace_name'] for e in manifest['cases']}
        self.assertEqual(names, {'案件_CON', 'state（2）', '控制', '控制（2）'})
        folder = flow.batch_folder(self.cfg, manifest)
        with self.assertRaises(flow.Blocked):
            flow.case_workspace(folder, {'case_id': 'id', 'workspace_name': '控制', 'workspace_relative': '../控制'})

    def test_started_legacy_workspace_is_preserved_and_remaining_case_is_named(self):
        self.make_source('a.docx'); self.make_source('b.docx')
        manifest = flow.manifest_for(self.source)
        folder = self.cfg['_root'] / manifest['batch_id']
        flow.atomic_json(folder / 'manifest.json', manifest)
        first = folder / manifest['cases'][0]['case_id']
        put(first / 'existing-code.py', b'# keep existing path')
        with flow.BatchLock(folder):
            with self.assertRaises(flow.Busy):
                self.run_fake(FakeExecutor())
        result = self.run_fake(FakeExecutor())
        self.assertEqual(result['status'], 'complete')
        updated = flow.read_json(folder / 'manifest.json')
        self.assertEqual(flow.case_workspace(folder, updated['cases'][0]), first)
        self.assertEqual((first / 'existing-code.py').read_bytes(), b'# keep existing path')
        second = flow.case_workspace(folder, updated['cases'][1])
        self.assertEqual(second.name, 'b')
        self.assertEqual(second.parent.name, time.strftime('%Y-%m'))

    def test_three_builders_overlap_reviews_and_recordings_serialize_and_publish(self):
        self.configure()
        for name in ('a', 'b', 'c', 'd'):
            self.make_source(name + '.docx')
        manifest = flow.plan(self.cfg, self.source)
        lock = threading.Lock()
        barrier = threading.Barrier(3, timeout=15)
        active = {'build': 0, 'review': 0, 'video': 0}
        peak = dict(active)
        builders = []
        observed_resources = {}
        fake = FakeExecutor()
        def execute(cfg, case, stage, context, output=None):
            group = 'review' if stage.startswith('review_') else stage if stage in {'build', 'video'} else None
            with lock:
                observed_resources[case.name] = context['case_resources']
                if group:
                    active[group] += 1
                    peak[group] = max(peak[group], active[group])
                if stage == 'build':
                    builders.append(case.name)
                    first_wave = len(builders) <= 3
            try:
                if stage == 'build' and first_wave:
                    barrier.wait()
                time.sleep(.04)
                return fake(cfg, case, stage, context, output)
            finally:
                with lock:
                    if group:
                        active[group] -= 1
        result = self.run_fake(execute)
        self.assertEqual(result['status'], 'complete', [(x['case_name'], x.get('reason')) for x in result['cases']])
        self.assertEqual(peak, {'build': 3, 'review': 1, 'video': 1})
        self.assertEqual(len({p for x in observed_resources.values() for p in x['ports']}), 16)
        self.assertEqual(len({x['browser_profile'] for x in observed_resources.values()}), 4)
        self.assertEqual(len(list(Path(manifest['output_root']).iterdir())), 4)
        counts = len(fake.stages)
        again = self.run_fake(execute)
        self.assertEqual(again['status'], 'complete')
        self.assertEqual(len(fake.stages), counts)

    def test_one_worker_failure_does_not_stop_other_cases(self):
        self.configure()
        for name in ('good', 'bad', 'third'):
            self.make_source(name + '.docx')
        flow.plan(self.cfg, self.source)
        result = self.run_fake(FakeExecutor(bad_build=True))
        self.assertEqual(sorted(s['stage'] for s in result['cases']), ['blocked', 'delivered', 'delivered'],
                         [(s['case_name'], s.get('reason')) for s in result['cases']])

    def test_configuration_rejects_invalid_parallelism(self):
        data = flow.read_json(self.config_path)
        for invalid in (0, -1, 1.5, True, 20):
            data['execution'] = {'case_concurrency': invalid}
            flow.atomic_json(self.config_path, data)
            with self.assertRaises(flow.Blocked):
                flow.config_at(self.config_path)

    def test_runtime_profile_changes_do_not_invalidate_evidence(self):
        case = self.root / 'case'
        put(case / 'src/app.py', b'pass')
        before = flow.snapshot(case, video=True)
        put(case / '.runtime/browser/Cache/active', b'changing browser state')
        self.assertEqual(flow.snapshot(case, video=True), before)

    def test_new_month_changes_only_new_batch_placement(self):
        self.make_source('控制方法.docx')
        original = flow.plan(self.cfg, self.source)
        other = self.root / 'next-month'; other.mkdir()
        fixtures.docx(other / '控制方法.docx')
        actual_strftime = flow.time.strftime
        current_month = actual_strftime('%Y-%m')
        future_month = '2099-12' if current_month != '2099-12' else '2099-11'
        def next_month(fmt, *args):
            return future_month if fmt == '%Y-%m' else actual_strftime(fmt, *args)
        with patch.object(flow.time, 'strftime', side_effect=next_month):
            new = flow.plan(self.cfg, other)
            resumed = flow.plan(self.cfg, self.source)
        self.assertEqual(new['cases'][0]['workspace_relative'], future_month + '/控制方法')
        self.assertEqual(resumed['cases'][0]['workspace_relative'], original['cases'][0]['workspace_relative'])

    def test_recording_slot_contention_does_not_fail_waiters(self):
        self.configure()
        active = 0
        peak = 0
        completed = []
        mutex = threading.Lock()
        def enter(index):
            nonlocal active, peak
            with flow.stage_slot(self.cfg, 'recording'):
                with mutex:
                    active += 1
                    peak = max(peak, active)
                time.sleep(.01)
                with mutex:
                    completed.append(index)
                    active -= 1
        with flow.ThreadPoolExecutor(max_workers=5) as pool:
            list(pool.map(enter, range(20)))
        self.assertEqual(peak, 1)
        self.assertEqual(len(completed), 20)
