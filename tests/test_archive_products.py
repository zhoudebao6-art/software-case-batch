import hashlib
import json
import os
from pathlib import Path
import shutil
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import archive_products as archive
from common import digest, read_json, write_json
from batch_control import identity


class ArchiveTests(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp(prefix='archive-test-'))
        self.source_root = self.root / 'daily'
        self.destination_root = self.root / 'weekly'
        self.batch_root = self.root / 'batches'
        self.state_root = self.root / 'archive-state'
        self.source = self.source_root / '批次' / 'batch-a' / 'case-a'
        self.destination = self.destination_root / '批次' / 'batch-a' / 'case-a'
        self.work = self.root / 'case-work'
        self.destination_root.mkdir()
        self.source.mkdir(parents=True)
        self.work.mkdir()
        for rel, data in {'原名.docx': b'word', '模拟系统/演示视频.mp4': b'video',
                          '模拟系统/项目源码.zip': b'zip', '模拟系统/数据/明细.csv': b'a,b\n1,2\n'}.items():
            path = self.source / rel
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(data)
        self.files = archive.hashes(archive.snapshot(self.source))
        self.proof = self.work / 'independent.json'
        write_json(self.proof, {'reviewed_files': self.files, 'passed': True})
        self.final = self.work / '.product-v2/final-receipt.json'
        self.publish = self.work / '.product-v2/publish-receipt.json'
        write_json(self.final, {'status': 'complete', 'delivery_state': 'verified-candidate',
                   'files': self.files, 'execution_evidence': str(self.proof),
                   'evidence_sha256': digest(self.proof)})
        write_json(self.publish, {'status': 'published', 'destination': str(self.source),
                   'files': self.files, 'source_receipt_sha256': digest(self.final)})
        write_json(self.work / '.product-v2/run.json', {'workspace': str(self.work),
                   'status': 'published', 'output': str(self.source), 'run_id': 'run-a'})
        self.target = self.batch_root / 'batch-a'
        write_json(self.target / 'manifest.json', {'batch_id': 'batch-a',
                   'cases': [{'case_id': 'case-a', 'workspace': str(self.work)}]})
        write_json(self.target / 'state.json', {'cases': {'case-a': {'phase': 'delivered'}}})
        write_json(self.batch_root / 'queue.json', [])
        self.args = (self.source_root, self.destination_root, self.batch_root, self.state_root)

    def tearDown(self):
        shutil.rmtree(self.root)

    def completed_sibling(self, batch_id='batch-a', case_id='case-b'):
        work = self.root / (case_id + '-work')
        source = self.source_root / '批次' / batch_id / case_id
        shutil.copytree(self.source, source)
        files = archive.hashes(archive.snapshot(source))
        proof = work / 'review.json'
        final = work / '.product-v2/final-receipt.json'
        write_json(proof, {'fixture_only': True, 'reviewed_files': files})
        write_json(final, {'status': 'complete', 'delivery_state': 'verified-candidate',
                   'files': files, 'execution_evidence': str(proof), 'evidence_sha256': digest(proof)})
        write_json(work / '.product-v2/publish-receipt.json', {'status': 'published',
                   'destination': str(source), 'files': files, 'source_receipt_sha256': digest(final)})
        run_path = work / '.product-v2/run.json'
        write_json(run_path, {'workspace': str(work), 'status': 'published',
                   'output': str(source), 'run_id': case_id + '-run'})
        target = self.batch_root / batch_id
        manifest_path, state_path = target / 'manifest.json', target / 'state.json'
        manifest = read_json(manifest_path) if manifest_path.exists() else {'batch_id': batch_id, 'cases': []}
        state = read_json(state_path) if state_path.exists() else {'cases': {}}
        manifest['cases'].append({'case_id': case_id, 'workspace': str(work)})
        state['cases'][case_id] = {'phase': 'delivered'}
        write_json(manifest_path, manifest)
        write_json(state_path, state)
        return source, state_path, run_path

    def test_entire_batch_requires_every_sibling_delivered_and_published(self):
        sibling, state_path, run_path = self.completed_sibling()
        batch_state = read_json(state_path)
        for phase in ('building', 'repairing', 'paused', 'cancelled'):
            with self.subTest(phase=phase):
                batch_state['cases']['case-b']['phase'] = phase
                write_json(state_path, batch_state)
                report = archive.apply(*self.args)
                self.assertEqual(report['archived'], [])
                self.assertEqual({row['case_id'] for row in report['retained']}, {'case-a', 'case-b'})
                self.assertTrue(self.source.exists())
                self.assertTrue(sibling.exists())
        batch_state['cases']['case-b']['phase'] = 'delivered'
        write_json(state_path, batch_state)
        run = read_json(run_path)
        run['status'] = 'prepared'
        write_json(run_path, run)
        self.assertEqual(archive.plan(*self.args)['eligible'], [])
        run['status'] = 'published'
        write_json(run_path, run)
        self.assertEqual(len(archive.plan(*self.args)['eligible']), 2)
        self.assertEqual(len(archive.apply(*self.args)['archived']), 2)

    def test_active_sibling_blocks_whole_batch_but_unrelated_idle_batch_does_not(self):
        sibling, _, _ = self.completed_sibling()
        ticket = {'batch_id': 'batch-a', 'case_id': 'case-b', 'status': 'active',
                  'stage': 'build', 'owner': identity(os.getpid())}
        write_json(self.batch_root / 'queue.json', [ticket])
        self.assertEqual(archive.plan(*self.args)['eligible'], [])
        self.assertEqual(archive.apply(*self.args)['archived'], [])
        self.assertTrue(self.source.exists())
        self.assertTrue(sibling.exists())
        idle, state_path, _ = self.completed_sibling('idle-batch', 'idle-case')
        write_json(state_path, {'cases': {'idle-case': {'phase': 'waiting'}}})
        write_json(self.batch_root / 'queue.json', [dict(ticket, batch_id='idle-batch', case_id='idle-case', status='waiting')])
        report = archive.plan(*self.args)
        self.assertEqual({row['batch_id'] for row in report['eligible']}, {'batch-a'})
        self.assertEqual(len(report['eligible']), 2)
        report = archive.apply(*self.args)
        self.assertEqual(len(report['archived']), 2)
        self.assertTrue(idle.exists())

    def test_plan_is_read_only_and_requires_actual_published_hashes(self):
        self.assertEqual(len(archive.plan(*self.args)['eligible']), 1)
        self.assertFalse(self.state_root.exists())
        (self.source / '原名.docx').write_bytes(b'revised')
        result = archive.plan(*self.args)
        self.assertFalse(result['eligible'])
        self.assertIn('frozen receipt', result['retained'][0]['reason'])

    def test_receipt_and_independent_proof_changes_retain_product(self):
        self.proof.write_text('{}')
        self.assertIn('proof changed', archive.plan(*self.args)['retained'][0]['reason'])
        self.assertTrue(self.source.exists())

    def test_unfinished_case_and_missing_publication_are_not_archived(self):
        write_json(self.target / 'state.json', {'cases': {'case-a': {'phase': 'repairing'}}})
        self.assertFalse(archive.plan(*self.args)['eligible'])
        write_json(self.target / 'state.json', {'cases': {'case-a': {'phase': 'delivered'}}})
        self.publish.unlink()
        self.assertFalse(archive.plan(*self.args)['eligible'])

    def test_explicit_roots_and_missing_destination_fail_without_creating_it(self):
        self.destination_root.rmdir()
        with self.assertRaisesRegex(ValueError, 'disconnected'):
            archive.apply(*self.args)
        self.assertFalse(self.destination_root.exists())
        self.assertTrue(self.source.exists())
        with self.assertRaisesRegex(ValueError, 'absolute'):
            archive.roots('daily', *self.args[1:])
        with self.assertRaisesRegex(ValueError, 'disjoint'):
            archive.roots(self.source_root, self.source_root / 'bad', *self.args[2:])

    def test_outside_product_and_unregistered_source_never_touched(self):
        unrelated = self.source_root / 'private.txt'
        unrelated.write_bytes(b'private')
        destination = self.root / 'unrelated'
        destination.mkdir()
        published = read_json(self.publish)
        published['destination'] = str(destination)
        write_json(self.publish, published)
        run = read_json(self.work / '.product-v2/run.json')
        run['output'] = str(destination)
        write_json(self.work / '.product-v2/run.json', run)
        result = archive.plan(*self.args)
        self.assertIn('outside', result['retained'][0]['reason'])
        self.assertEqual(unrelated.read_bytes(), b'private')
        self.assertTrue(destination.exists())

    def test_missing_authoritative_queue_fails_closed(self):
        (self.batch_root / 'queue.json').unlink()
        with self.assertRaises(ValueError):
            archive.plan(*self.args)
        self.assertTrue(self.source.exists())

    @unittest.skipUnless(os.name == 'nt', 'native Windows handles')
    def test_verified_active_media_blocks_but_unrelated_build_and_waiting_do_not(self):
        owner = identity(os.getpid())
        ticket = {'batch_id': 'other', 'case_id': 'other', 'status': 'active',
                  'stage': 'build', 'owner': owner}
        write_json(self.batch_root / 'queue.json', [ticket, dict(ticket, status='waiting', stage='record')])
        self.assertEqual(len(archive.plan(*self.args)['eligible']), 1)
        write_json(self.batch_root / 'queue.json', [dict(ticket, stage='record')])
        self.assertFalse(archive.plan(*self.args)['eligible'])
        write_json(self.batch_root / 'queue.json', [dict(ticket, batch_id='batch-a', case_id='case-a')])
        self.assertFalse(archive.plan(*self.args)['eligible'])

    def test_links_are_not_followed_at_roots_or_inside_product(self):
        outside = self.root / 'outside'
        outside.mkdir()
        private = outside / 'secret.txt'
        private.write_bytes(b'secret')
        link = self.source / '模拟系统' / 'escape'
        try:
            link.symlink_to(outside, target_is_directory=True)
        except OSError as exc:
            self.skipTest(str(exc))
        result = archive.plan(*self.args)
        self.assertFalse(result['eligible'])
        self.assertEqual(private.read_bytes(), b'secret')
        link.unlink()
        root_link = self.root / 'root-link'
        root_link.symlink_to(self.destination_root, target_is_directory=True)
        with self.assertRaisesRegex(ValueError, 'link/reparse'):
            archive.roots(self.source_root, root_link, self.batch_root, self.state_root)
        root_link.unlink()

    @unittest.skipUnless(os.name == 'nt', 'native Windows handles')
    def test_success_archives_complete_structure_freezes_receipts_and_resolves(self):
        frozen = {path: path.read_bytes() for path in (self.final, self.publish,
                  self.work / '.product-v2/run.json')}
        result = archive.apply(*self.args)
        self.assertEqual(result['retained'], [])
        self.assertEqual(len(result['archived']), 1)
        self.assertFalse(self.source.exists())
        self.assertEqual(archive.hashes(archive.snapshot(self.destination)), self.files)
        self.assertEqual(archive.resolve_location(self.state_root, self.source, self.files), self.destination)
        for path, data in frozen.items():
            self.assertEqual(path.read_bytes(), data)
        self.assertEqual(set(p.name for p in self.destination.iterdir()), {'原名.docx', '模拟系统'})
        self.assertEqual(len(archive.plan(*self.args)['already_archived']), 1)

    @unittest.skipUnless(os.name == 'nt', 'native Windows handles')
    def test_existing_destination_even_matching_is_conflict_without_owned_intent(self):
        shutil.copytree(self.source, self.destination)
        result = archive.apply(*self.args)
        self.assertIn('conflict', result['retained'][0]['reason'])
        self.assertTrue(self.source.exists())
        self.assertEqual(archive.hashes(archive.snapshot(self.destination)), self.files)

    @unittest.skipUnless(os.name == 'nt', 'native Windows handles')
    def test_copy_interruption_resumes_and_reverifies_every_file(self):
        original = archive.copy_stage
        def interrupted(source, stage, expected):
            stage.mkdir(parents=True, exist_ok=True)
            (stage / '原名.docx').write_bytes(b'partial')
            raise OSError('copy interrupted')
        with patch.object(archive, 'copy_stage', side_effect=interrupted):
            result = archive.apply(*self.args)
        self.assertTrue(result['retained'])
        self.assertTrue(self.source.exists())
        self.assertFalse(self.destination.exists())
        self.assertEqual(archive.apply(*self.args)['retained'], [])
        self.assertFalse(self.source.exists())

    @unittest.skipUnless(os.name == 'nt', 'native Windows handles')
    def test_crash_after_atomic_publish_resumes_without_overwriting(self):
        real_write = archive.write_json
        def interrupted(path, value):
            if value.get('status') == 'published':
                raise RuntimeError('simulated crash after rename')
            return real_write(path, value)
        with patch.object(archive, 'write_json', side_effect=interrupted):
            with self.assertRaisesRegex(RuntimeError, 'simulated crash'):
                archive.apply(*self.args)
        self.assertTrue(self.source.exists())
        self.assertTrue(self.destination.exists())
        self.assertFalse((self.state_root / 'current-locations.json').exists())
        self.assertEqual(archive.apply(*self.args)['retained'], [])
        self.assertFalse(self.source.exists())

    @unittest.skipUnless(os.name == 'nt', 'native Windows handles')
    def test_revision_before_cleanup_preserves_source_and_locator(self):
        real_write = archive.write_json
        def revision(path, value):
            result = real_write(path, value)
            if Path(path).name == 'current-locations.json':
                real_write(self.target / 'state.json', {'cases': {'case-a': {'phase': 'repairing'}}})
            return result
        with patch.object(archive, 'write_json', side_effect=revision):
            report = archive.apply(*self.args)
        self.assertTrue(report['retained'])
        self.assertEqual(archive.hashes(archive.snapshot(self.source)), self.files)
        self.assertEqual(archive.resolve_location(self.state_root, self.source, self.files), self.destination)

    @unittest.skipUnless(os.name == 'nt', 'native Windows handles')
    def test_source_change_during_copy_prevents_publication_and_deletion(self):
        real_copy = archive.copy_stage
        def changed(source, stage, expected):
            (source / '原名.docx').write_bytes(b'changed')
            return real_copy(source, stage, expected)
        with patch.object(archive, 'copy_stage', side_effect=changed):
            report = archive.apply(*self.args)
        self.assertTrue(report['retained'])
        self.assertEqual((self.source / '原名.docx').read_bytes(), b'changed')
        self.assertFalse(self.destination.exists())

    @unittest.skipUnless(os.name == 'nt', 'native Windows handles')
    def test_protected_file_handles_refuse_edit_replace_and_rename(self):
        path = self.source / '原名.docx'
        with archive.WindowsHandle(path, delete=True) as held:
            with self.assertRaises(OSError):
                path.write_bytes(b'revised')
            with self.assertRaises(OSError):
                path.rename(path.with_name('renamed.docx'))
            self.assertEqual(held.sha256(), self.files['原名.docx'])
        self.assertEqual(path.read_bytes(), b'word')

    @unittest.skipUnless(os.name == 'nt', 'native Windows handles')
    def test_boundary_swap_is_blocked_during_copy(self):
        real_copy = archive.copy_stage
        def swap(source, stage, expected):
            with self.assertRaises(OSError):
                self.source.parent.rename(self.source.parent.with_name('swapped'))
            return real_copy(source, stage, expected)
        with patch.object(archive, 'copy_stage', side_effect=swap):
            report = archive.apply(*self.args)
        self.assertEqual(report['retained'], [])

    @unittest.skipUnless(os.name == 'nt', 'native Windows handles')
    def test_destination_space_failure_keeps_complete_source(self):
        with patch.object(archive.shutil, 'disk_usage', return_value=SimpleNamespace(free=0)):
            report = archive.apply(*self.args)
        self.assertIn('space insufficient', report['retained'][0]['reason'])
        self.assertEqual(archive.hashes(archive.snapshot(self.source)), self.files)

    @unittest.skipUnless(os.name == 'nt', 'native Windows handles')
    def test_partial_protected_cleanup_resumes_only_original_unchanged_objects(self):
        real_delete = archive.WindowsHandle.delete
        calls = []
        def interrupted(handle):
            if handle.path.is_file() and self.source in handle.path.parents:
                calls.append(handle.path)
                if len(calls) == 2:
                    raise OSError('interrupted cleanup')
            return real_delete(handle)
        with patch.object(archive.WindowsHandle, 'delete', interrupted):
            report = archive.apply(*self.args)
        self.assertTrue(report['retained'])
        self.assertTrue(self.source.exists())
        self.assertEqual(archive.hashes(archive.snapshot(self.destination)), self.files)
        self.assertEqual(archive.apply(*self.args)['retained'], [])
        self.assertFalse(self.source.exists())

    @unittest.skipUnless(os.name == 'nt', 'native Windows handles')
    def test_occupied_source_prevents_any_deletion(self):
        path = self.source / '原名.docx'
        with path.open('rb') as busy:
            report = archive.apply(*self.args)
            self.assertTrue(report['retained'])
            self.assertEqual(archive.hashes(archive.snapshot(self.source)), self.files)

    @unittest.skipUnless(os.name == 'nt', 'native Windows handles')
    def test_empty_directories_are_preserved_and_empty_stage_can_resume(self):
        empty = self.source / '模拟系统' / '数据' / '空目录'
        empty.mkdir()
        original = archive.copy_stage
        with patch.object(archive, 'copy_stage', side_effect=OSError('before first byte')):
            self.assertTrue(archive.apply(*self.args)['retained'])
        self.assertEqual(archive.apply(*self.args)['retained'], [])
        self.assertTrue((self.destination / '模拟系统' / '数据' / '空目录').is_dir())
        self.assertFalse(self.source.exists())

    @unittest.skipUnless(os.name == 'nt', 'native Windows handles')
    def test_recreated_source_after_partial_cleanup_is_not_deleted(self):
        real_delete = archive.WindowsHandle.delete
        deleted = []
        def interrupted(handle):
            if handle.path.is_file() and self.source in handle.path.parents:
                if deleted:
                    raise OSError('interrupt')
                deleted.append(handle.path)
            return real_delete(handle)
        with patch.object(archive.WindowsHandle, 'delete', interrupted):
            self.assertTrue(archive.apply(*self.args)['retained'])
        deleted[0].write_bytes(b'new revision at old name')
        result = archive.apply(*self.args)
        self.assertTrue(result['retained'])
        self.assertEqual(deleted[0].read_bytes(), b'new revision at old name')
        self.assertEqual(archive.hashes(archive.snapshot(self.destination)), self.files)

    @unittest.skipUnless(os.name == 'nt', 'native Windows handles')
    def test_changed_archived_destination_never_triggers_source_cleanup_on_resume(self):
        real_write = archive.write_json
        def interrupted(path, value):
            if value.get('status') == 'published':
                raise RuntimeError('crash')
            return real_write(path, value)
        with patch.object(archive, 'write_json', side_effect=interrupted):
            with self.assertRaises(RuntimeError):
                archive.apply(*self.args)
        (self.destination / '原名.docx').write_bytes(b'destination changed')
        result = archive.apply(*self.args)
        self.assertTrue(result['retained'])
        self.assertEqual(archive.hashes(archive.snapshot(self.source)), self.files)

    @unittest.skipUnless(os.name == 'nt', 'native Windows handles')
    def test_native_job_lock_releases_after_scope_without_deleting_lock_file(self):
        self.state_root.mkdir()
        with archive.job_guard(self.state_root):
            with self.assertRaises(OSError):
                with archive.job_guard(self.state_root):
                    pass
        self.assertTrue((self.state_root / 'archive-job.lock').is_file())
        with archive.job_guard(self.state_root):
            pass

    @unittest.skipUnless(os.name == 'nt', 'native Windows handles')
    def test_exact_media_job_children_block_after_root_and_owner_exit(self):
        from media_job import job_name
        job = job_name(self.batch_root, 'other', 'media-token')
        dead = {'pid': 123, 'created_ticks': 456}
        ticket = {'batch_id': 'other', 'case_id': 'other', 'status': 'active', 'stage': 'record',
                  'token': 'media-token', 'owner': dead,
                  'media_runtime': {'pid': 123, 'identity': dead, 'job_name': job}}
        write_json(self.batch_root / 'queue.json', [ticket])
        with patch.object(archive, 'identity', return_value=None), patch('media_job.job_pids', return_value=[999]):
            self.assertFalse(archive.plan(*self.args)['eligible'])
        with patch.object(archive, 'identity', return_value=None), patch('media_job.job_pids', return_value=[]):
            self.assertEqual(len(archive.plan(*self.args)['eligible']), 1)

    @unittest.skipUnless(os.name == 'nt', 'native Windows handles')
    def test_new_entries_created_during_cleanup_are_retained_without_recursive_delete(self):
        real_delete = archive.WindowsHandle.delete
        added = self.source / 'new-revision.txt'
        def addition(handle):
            if handle.path.is_file() and self.source in handle.path.parents and not added.exists():
                added.write_bytes(b'keep new revision')
            return real_delete(handle)
        with patch.object(archive.WindowsHandle, 'delete', addition):
            result = archive.apply(*self.args)
        self.assertTrue(result['retained'])
        self.assertEqual(added.read_bytes(), b'keep new revision')
        self.assertEqual(archive.hashes(archive.snapshot(self.destination)), self.files)
        self.assertTrue(archive.apply(*self.args)['retained'])
        self.assertEqual(added.read_bytes(), b'keep new revision')


if __name__ == '__main__':
    unittest.main()
