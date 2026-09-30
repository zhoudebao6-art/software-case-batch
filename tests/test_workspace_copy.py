import sys
import unittest
from pathlib import Path
from unittest.mock import patch

import test_caseflow as fixtures
from test_caseflow import flow, put

sys.path.insert(0, str(fixtures.MODULE.parent))
import workspace_copy


class FreshWorkspaceTests(unittest.TestCase):
    setUp = fixtures.CaseflowTests.setUp
    tearDown = fixtures.CaseflowTests.tearDown
    make_source = fixtures.CaseflowTests.make_source

    def setup_case(self):
        self.make_source()
        m = flow.plan(self.cfg, self.source)
        folder = flow.batch_folder(self.cfg, m)
        e = m['cases'][0]
        case = flow.case_workspace(folder, e)
        put(case / 'source/a.docx', Path(e['source_path']).read_bytes())
        put(case / 'web/app.js', b'existing code')
        put(case / 'logs/previous.jsonl', b'historical calls')
        flow.atomic_json(flow.state_at(folder, e['case_id']), {'stage': 'blocked', 'previous_stage': 'built',
            'calls': [{'stage': 'build'}], 'case_id': e['case_id']})
        return m, folder, e, case

    def test_same_path_copy_preserves_all_bytes_backup_and_state(self):
        m, folder, e, case = self.setup_case()
        before = workspace_copy.tree_hashes(case, flow)
        result = workspace_copy.refresh(self.cfg, m['batch_id'], e['case_id'], flow, process_guard=lambda _: [])
        self.assertEqual(workspace_copy.tree_hashes(case, flow), before)
        self.assertEqual(workspace_copy.tree_hashes(Path(result['backup']), flow), before)
        state = flow.read_json(flow.state_at(folder, e['case_id']))
        self.assertEqual(state['calls'], [{'stage': 'build'}])
        self.assertTrue(state['needs_workspace_repair'])
        again = workspace_copy.refresh(self.cfg, m['batch_id'], e['case_id'], flow, process_guard=lambda _: [])
        self.assertEqual(again, result)

    def test_interrupted_swap_recovers_without_deleting_old_copy(self):
        m, folder, e, case = self.setup_case()
        rename = Path.rename
        def stop(src, dst):
            result = rename(src, dst)
            if src == case:
                raise OSError('interrupted')
            return result
        with patch.object(Path, 'rename', stop), self.assertRaises(OSError):
            workspace_copy.refresh(self.cfg, m['batch_id'], e['case_id'], flow, process_guard=lambda _: [])
        self.assertFalse(case.exists())
        result = workspace_copy.refresh(self.cfg, m['batch_id'], e['case_id'], flow, process_guard=lambda _: [])
        self.assertEqual((case / 'web/app.js').read_bytes(), b'existing code')
        self.assertTrue(Path(result['backup']).is_dir())

    def test_active_stage_or_process_refused(self):
        m, folder, e, case = self.setup_case()
        with self.assertRaisesRegex(flow.Blocked, 'stopped case processes'):
            workspace_copy.refresh(self.cfg, m['batch_id'], e['case_id'], flow, process_guard=lambda _: [{'pid': 10}])
        state_path = flow.state_at(folder, e['case_id'])
        state = flow.read_json(state_path); state['active_stage'] = 'repair_visual'
        flow.atomic_json(state_path, state)
        with self.assertRaisesRegex(flow.Blocked, 'stopped blocked case'):
            workspace_copy.refresh(self.cfg, m['batch_id'], e['case_id'], flow, process_guard=lambda _: [])
        self.assertTrue(case.is_dir())

    def test_success_exit_with_environment_blocker_stops_without_paid_retry(self):
        self.make_source()
        m = flow.plan(self.cfg, self.source)
        fake = fixtures.FakeExecutor()
        def execute(cfg, case, stage, context, output=None):
            result = fake(cfg, case, stage, context, output)
            flow.atomic_json(case / '.caseflow-environment.json', {'status': 'blocked',
                'requires_environment_repair': True, 'reason': 'fixture write denied'})
            return result
        result = flow.run_batch(self.cfg, m['batch_id'], executor=execute)
        self.assertEqual(result['cases'][0]['stage'], 'blocked')
        self.assertIn('environment needs repair', result['cases'][0]['reason'])
        self.assertEqual([s for _, s in fake.stages], ['build'])

    def test_protected_acl_is_not_silently_replaced(self):
        m, folder, e, case = self.setup_case()
        with patch.object(workspace_copy, 'assert_normal_inheritance', side_effect=flow.Blocked('Protected ACL')):
            with self.assertRaisesRegex(flow.Blocked, 'Protected ACL'):
                workspace_copy.refresh(self.cfg, m['batch_id'], e['case_id'], flow, process_guard=lambda _: [])
        self.assertTrue((case / 'web/app.js').is_file())

    def test_unreadable_runtime_temp_stays_in_old_backup(self):
        m, folder, e, case = self.setup_case()
        omitted = '.runtime/tmp/pip-build-tracker-test'
        put(case / omitted / 'sentinel.txt', b'old runtime scratch')
        with patch.object(workspace_copy, 'inaccessible_runtime_temps', return_value=[omitted]):
            result = workspace_copy.refresh(self.cfg, m['batch_id'], e['case_id'], flow,
                                            process_guard=lambda _: [])
        self.assertFalse((case / omitted).exists())
        self.assertEqual((Path(result['backup']) / omitted / 'sentinel.txt').read_bytes(),
                         b'old runtime scratch')
        self.assertEqual(result['omitted_unreadable_runtime_dirs'], [omitted])

    def test_non_runtime_enumeration_error_is_refused(self):
        m, folder, e, case = self.setup_case()
        def fail_walk(*args, **kwargs):
            kwargs['onerror'](PermissionError(13, 'denied', str(case / 'source')))
            yield case, [], []
        with patch.object(workspace_copy.os, 'walk', side_effect=fail_walk):
            with self.assertRaisesRegex(flow.Blocked, 'Unreadable non-temp workspace path'):
                workspace_copy.inaccessible_runtime_temps(case, flow)

    def test_explicitly_omitted_scratch_is_not_enumerated(self):
        m, folder, e, case = self.setup_case()
        scratch = case / '.runtime' / 'tmp'
        def walk(*args, **kwargs):
            yield case, ['.runtime'], []
            runtime_dirs = ['tmp']
            yield case / '.runtime', runtime_dirs, []
            if 'tmp' in runtime_dirs:
                kwargs['onerror'](PermissionError(13, 'denied', str(scratch / 'ffmpeg-binaries' / 'bin')))
        with patch.object(workspace_copy.os, 'walk', side_effect=walk):
            self.assertEqual(workspace_copy.inaccessible_runtime_temps(
                case, flow, omitted_dirs=['.runtime/tmp']), [])

    def test_runtime_scratch_is_archived_while_database_is_copied(self):
        m, folder, e, case = self.setup_case()
        put(case / '.runtime/browser/Default/chrome_debug.log', b'old browser')
        put(case / '.runtime/tmp/.tmp123/diagnostics.js', b'old scratch')
        put(case / '.runtime/case.db', b'business database')
        result = workspace_copy.refresh(self.cfg, m['batch_id'], e['case_id'], flow,
                                        process_guard=lambda _: [], omit_runtime_scratch=True)
        backup = Path(result['backup'])
        self.assertEqual((case / '.runtime/case.db').read_bytes(), b'business database')
        self.assertFalse((case / '.runtime/browser').exists())
        self.assertFalse((case / '.runtime/tmp').exists())
        self.assertEqual((backup / '.runtime/browser/Default/chrome_debug.log').read_bytes(), b'old browser')
        self.assertEqual((backup / '.runtime/tmp/.tmp123/diagnostics.js').read_bytes(), b'old scratch')
        self.assertIsNone(result['archived_runtime_file_count'])
