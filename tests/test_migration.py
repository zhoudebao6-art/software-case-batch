"""Offline migration keeps checkpoints, originals and refuses live owners."""
import importlib.util
import json
import time
import unittest
from pathlib import Path
from unittest.mock import patch

import test_caseflow as fixtures
from test_caseflow import FakeExecutor, flow, put

spec = importlib.util.spec_from_file_location('migration', fixtures.MODULE.with_name('migrate_batch.py'))
migration = importlib.util.module_from_spec(spec)
spec.loader.exec_module(migration)


class MigrationTests(unittest.TestCase):
    setUp = fixtures.CaseflowTests.setUp
    tearDown = fixtures.CaseflowTests.tearDown
    make_source = fixtures.CaseflowTests.make_source
    run_fake = fixtures.CaseflowTests.run_fake

    def legacy(self):
        original = self.make_source('技术项目优化说明书控制方法.docx')
        m = flow.manifest_for(self.source)
        folder = self.cfg['_root'] / m['batch_id']
        flow.atomic_json(folder / 'manifest.json', m)
        e = m['cases'][0]
        case = folder / e['case_id']
        put(case / 'source' / original.name, original.read_bytes())
        put(case / 'src/keep.py', b'# existing implementation')
        FakeExecutor()(self.cfg, case, 'build', {'source_docx': str(original), 'source_sha256': e['source_sha256']})
        flow.atomic_json(flow.state_at(folder, e['case_id']), {'case_id': e['case_id'], 'stage': 'built',
                         'active_stage': 'video', 'calls': [{'stage': 'build', 'token_usage': {'input_tokens': 42}}],
                         'review_mode': 'combined_final', 'astra_calls_started': 1,
                         'final_review': {'verdict': 'pass'}, 'controlled_word': {'stale': True}})
        self.cfg['runner'].update(review_mode='combined_final', max_astra_calls_per_case=None,
                                  max_final_review_repairs=None)
        return m, folder, case

    def migrate(self):
        with patch.object(migration, 'owned_processes', return_value=[]):
            return migration.migrate(self.cfg, str(self.source), flow)

    def test_migrate_resume_without_rebuild_preserves_original_code_and_usage(self):
        m, folder, old = self.legacy()
        result = self.migrate()
        case = Path(result['workspaces'][0]['workspace'])
        self.assertEqual(case, self.cfg['_root'] / time.strftime('%Y-%m') / '控制方法')
        self.assertFalse(old.exists())
        self.assertEqual((case / 'src/keep.py').read_bytes(), b'# existing implementation')
        self.assertEqual(flow.sha256(next((case / 'source').iterdir())), m['cases'][0]['source_sha256'])
        state = flow.read_json(flow.state_at(folder, m['cases'][0]['case_id']))
        self.assertNotIn('active_stage', state)
        self.assertNotIn('final_review', state)
        self.assertTrue(state['needs_workspace_repair'])
        self.assertEqual(state['astra_calls_started'], 1)
        self.assertEqual(self.migrate(), result)
        fake = FakeExecutor()
        completed = self.run_fake(fake)
        self.assertEqual(completed['status'], 'complete', completed)
        self.assertEqual([s for _, s in fake.stages], ['repair_visual', 'video', 'review_final'])
        self.assertEqual(completed['cases'][0]['calls'][0]['token_usage']['input_tokens'], 42)

    def test_locked_batch_and_live_case_process_are_refused(self):
        m, folder, case = self.legacy()
        with flow.BatchLock(folder), self.assertRaises(flow.Busy):
            self.migrate()
        with patch.object(migration, 'owned_processes', return_value=[{'ProcessId': 123, 'Name': 'owned-service'}]):
            with self.assertRaisesRegex(flow.Blocked, 'Stop verified case processes'):
                migration.migrate(self.cfg, str(self.source), flow)
        self.assertTrue(case.exists())
        self.assertFalse((folder / 'workspace-migration.json').exists())

    def test_interrupted_rename_resumes_journal_and_blocks_execution_in_between(self):
        m, folder, old = self.legacy()
        real_rename = Path.rename
        def interrupt_after_rename(src, dst):
            result = real_rename(src, dst)
            raise OSError('fixture process interrupted after atomic rename')
        with patch.object(Path, 'rename', interrupt_after_rename), self.assertRaises(OSError):
            self.migrate()
        with self.assertRaisesRegex(flow.Blocked, 'migration incomplete'):
            self.run_fake(FakeExecutor())
        self.assertEqual(self.migrate()['status'], 'migrated')
        self.assertFalse(old.exists())
        self.assertEqual(flow.read_json(folder / 'workspace-migration.json')['status'], 'complete')

    def test_existing_named_case_is_preserved_and_suffix_reserved(self):
        m, folder, old = self.legacy()
        existing = self.cfg['_root'] / time.strftime('%Y-%m') / '控制方法'
        put(existing / 'keep.txt', b'unrelated')
        result = self.migrate()
        self.assertEqual(Path(result['workspaces'][0]['workspace']).name, '控制方法（2）')
        self.assertEqual((existing / 'keep.txt').read_bytes(), b'unrelated')

    def test_journal_destination_cannot_escape_root(self):
        m, folder, old = self.legacy()
        with patch.object(Path, 'rename', side_effect=OSError('stop before rename')), self.assertRaises(OSError):
            self.migrate()
        path = folder / 'workspace-migration.json'
        journal = flow.read_json(path)
        journal['moves'][0]['to'] = str(self.root / 'outside')
        flow.atomic_json(path, journal)
        with self.assertRaises(flow.Blocked):
            self.migrate()
        self.assertTrue(old.exists())


class VisibleCopyTests(unittest.TestCase):
    setUp = fixtures.CaseflowTests.setUp
    tearDown = fixtures.CaseflowTests.tearDown
    make_source = fixtures.CaseflowTests.make_source
    run_fake = fixtures.CaseflowTests.run_fake

    def test_readme_and_audit_are_reviewed_and_readme_is_delivered(self):
        self.make_source()
        flow.plan(self.cfg, self.source)
        self.cfg['runner'].update(require_ui_text_audit=True, review_mode='combined_final')
        fake = FakeExecutor()
        def execute(cfg, case, stage, context, output=None):
            result = fake(cfg, case, stage, context, output)
            if stage == 'build':
                put(case / 'README.md', '数据来源与未验证范围：工程计算，非实测。'.encode())
                path = case / 'evidence/artifact-manifest.json'
                a = flow.read_json(path)
                a.update(readme='README.md', ui_text_audit='evidence/ui-visible-text.json')
                flow.atomic_json(path, a)
                flow.atomic_json(case / a['ui_text_audit'], {'rules_version': flow.VISIBLE_COPY_VERSION,
                    'pages': [{'url': 'http://127.0.0.1:18000/tasks', 'state': 'list', 'visible_text': '任务列表',
                               'screenshot': p, 'screenshot_sha256': flow.sha256(case / p)} for p in a['ui_screenshots']]})
            elif stage == 'review_final':
                self.assertIn('README.md', context['required_review_files'])
                self.assertIn('evidence/ui-visible-text.json', context['required_review_files'])
            return result
        result = self.run_fake(execute)
        self.assertEqual(result['status'], 'complete', result)
        self.assertTrue((Path(result['cases'][0]['delivery']) / 'README.md').is_file())

    def audit(self, text='任务列表 计算结果 运行记录'):
        case = self.root / 'case'
        put(case / 'README.md', '来源：工程样本模拟数据，非实测。'.encode())
        put(case / 'evidence/ui/list.png', fixtures.PNG)
        a = {'readme': 'README.md', 'ui_text_audit': 'evidence/ui-visible-text.json', 'ui_screenshots': ['evidence/ui/list.png']}
        report = {'rules_version': flow.VISIBLE_COPY_VERSION, 'pages': [{'url': 'http://127.0.0.1:18000/tasks',
                  'state': 'list', 'visible_text': text, 'screenshot': a['ui_screenshots'][0],
                  'screenshot_sha256': flow.sha256(case / a['ui_screenshots'][0])}]}
        flow.atomic_json(case / a['ui_text_audit'], report)
        return case, a

    def test_internal_readme_is_allowed_and_in_review_evidence(self):
        case, a = self.audit()
        self.assertEqual(flow.validate_visible_copy(case, a), {'README.md', a['ui_text_audit']})

    def test_forbidden_labels_cannot_be_visible(self):
        for text in ('模拟数据', '工程样本', '工程示例', '虚拟', '物理仿真', '模\n拟 数据', 'synthetic data', 'Demo data'):
            case, a = self.audit(text)
            with self.assertRaisesRegex(flow.Blocked, 'Forbidden visible web text'):
                flow.validate_visible_copy(case, a)

    def test_stale_or_omitted_screenshot_fails(self):
        case, a = self.audit()
        put(case / a['ui_screenshots'][0], fixtures.PNG + b'changed')
        with self.assertRaisesRegex(flow.Blocked, 'stale'):
            flow.validate_visible_copy(case, a)
        case, a = self.audit()
        a['ui_screenshots'].append('evidence/ui/omitted.png')
        with self.assertRaisesRegex(flow.Blocked, 'every current UI screenshot'):
            flow.validate_visible_copy(case, a)
