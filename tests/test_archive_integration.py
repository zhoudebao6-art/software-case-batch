"""Receipt-bound locator inheritance and unattended wrapper fixtures only."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import unittest
from unittest.mock import patch
import zipfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import archive_products as archive
import test_archive_products as archive_fixtures
from common import digest, file_map, read_json, state, write_json
from proflow import finalized_snapshot, prepare, revision_chain


class SmokeHelperBoundaryTests(unittest.TestCase):
    def test_invalid_smoke_identity_is_rejected_before_any_root_access(self):
        import archive_smoke_helper as helper
        with patch.object(helper, 'no_links', side_effect=AssertionError('must not access a root')):
            for value in ('../business', '', 'f' * 31, 'G' * 32, None):
                with self.subTest(value=value), self.assertRaises(ValueError):
                    helper.run_cross_volume_smoke(value)


class ArchiveIntegrationTests(unittest.TestCase):
    setUp = archive_fixtures.ArchiveTests.setUp
    tearDown = archive_fixtures.ArchiveTests.tearDown

    def archive_fixture(self):
        self.assertEqual(archive.apply(*self.args)['retained'], [])

    def base_link(self):
        return {'workspace': str(self.work), 'output': str(self.source),
                'receipt_sha256': digest(self.final),
                'system_files': {k[len('模拟系统/'):]: v for k, v in self.files.items()
                                 if k.startswith('模拟系统/')}}

    def test_state_resolves_archived_bytes_without_rewriting_frozen_receipts(self):
        frozen = {p: digest(p) for p in (self.final, self.publish, self.work / '.product-v2/run.json')}
        self.archive_fixture()
        with patch.dict(os.environ, {'SCB_PRO_ARCHIVE_STATE_ROOT': str(self.state_root)}):
            workspace, output, run = state(self.work)
            self.assertEqual(output, self.destination)
            self.assertEqual(run['output'], str(self.source))
            self.assertEqual(finalized_snapshot(output, read_json(self.final), workspace=workspace), {})
        self.assertEqual(frozen, {p: digest(p) for p in frozen})

    def test_preexisting_inherited_parent_path_survives_archive(self):
        frozen_link = self.base_link()
        self.archive_fixture()
        child = self.root / 'pending-revision'
        child.mkdir()
        with patch.dict(os.environ, {'SCB_PRO_ARCHIVE_STATE_ROOT': str(self.state_root)}):
            chain = revision_chain(child, frozen_link)
            self.assertEqual(chain[0]['output'], self.destination)
            self.assertEqual(chain[0]['run']['output'], str(self.source))
            changed = dict(frozen_link, output=str(self.root / 'arbitrary-alias'))
            with self.assertRaisesRegex(ValueError, 'Frozen revision'):
                revision_chain(child, changed)

    def test_two_archived_generations_follow_the_unchanged_inherited_system_chain(self):
        root_link = self.base_link()
        child_work = self.root / 'completed-child-work'
        child_work.mkdir()
        child_source = self.source_root / '批次/batch-a/case-child'
        shutil.copytree(self.source, child_source)
        (child_source / '原名.docx').write_bytes(b'child word')
        child_files = file_map(child_source)
        child_proof = child_work / 'review.json'
        write_json(child_proof, {'reviewed_files': child_files, 'passed': True})
        child_final = child_work / '.product-v2/final-receipt.json'
        write_json(child_final, {'status': 'complete', 'delivery_state': 'verified-candidate',
                   'scope': 'document-revision', 'inherited_system': root_link,
                   'files': child_files, 'execution_evidence': str(child_proof),
                   'evidence_sha256': digest(child_proof)})
        write_json(child_work / '.product-v2/publish-receipt.json', {'status': 'published',
                   'destination': str(child_source), 'files': child_files,
                   'source_receipt_sha256': digest(child_final)})
        child_run = child_work / '.product-v2/run.json'
        write_json(child_run, {'workspace': str(child_work), 'status': 'published',
                   'output': str(child_source), 'run_id': 'child-run', 'revision_of': root_link})
        manifest = read_json(self.target / 'manifest.json')
        manifest['cases'].append({'case_id': 'case-child', 'workspace': str(child_work)})
        write_json(self.target / 'manifest.json', manifest)
        write_json(self.target / 'state.json', {'cases': {'case-a': {'phase': 'delivered'},
                   'case-child': {'phase': 'delivered'}}})
        child_link = {'workspace': str(child_work), 'output': str(child_source),
                      'receipt_sha256': digest(child_final), 'system_files': root_link['system_files']}
        receipt_sha = digest(child_final)
        self.archive_fixture()
        following = self.root / 'following-work'
        following.mkdir()
        with patch.dict(os.environ, {'SCB_PRO_ARCHIVE_STATE_ROOT': str(self.state_root)}):
            chain = revision_chain(following, child_link)
            self.assertEqual([entry['workspace'] for entry in chain], [child_work, self.work])
            self.assertEqual(chain[0]['output'], self.destination_root / '批次/batch-a/case-child')
            self.assertEqual(chain[1]['output'], self.destination)
        self.assertEqual(digest(child_final), receipt_sha)
        self.assertEqual(read_json(child_final)['inherited_system'], root_link)

    def test_new_document_and_package_revisions_prepare_from_archived_parent(self):
        source_docx = self.work / 'source.docx'
        with zipfile.ZipFile(source_docx, 'w') as package:
            package.writestr('word/document.xml', '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"><w:body><w:p><w:r><w:t>设备运行控制</w:t></w:r></w:p></w:body></w:document>')
        self.archive_fixture()
        with patch.dict(os.environ, {'SCB_PRO_ARCHIVE_STATE_ROOT': str(self.state_root)}):
            for scope in ('document', 'package'):
                child = self.root / ('revision-' + scope)
                child.mkdir()
                run = prepare(child, self.root / ('candidate-' + scope), '设备运行控制', source_docx,
                              self.work, revision_scope=scope)
                self.assertEqual(run['revision_of']['output'], str(self.destination))
                self.assertEqual(revision_chain(child, run['revision_of'])[0]['output'], self.destination)
                self.assertEqual(file_map(self.destination / '模拟系统'), run['revision_of']['system_files'])
        self.assertFalse(self.source.exists())

    def test_receipt_metadata_drift_cannot_reuse_same_file_hash_locator(self):
        self.archive_fixture()
        receipt = read_json(self.final)
        receipt['limitations'] = ['changed after archive']
        write_json(self.final, receipt)
        with patch.dict(os.environ, {'SCB_PRO_ARCHIVE_STATE_ROOT': str(self.state_root)}):
            with self.assertRaisesRegex(ValueError, 'frozen publication'):
                state(self.work)

    def test_publication_receipt_drift_is_rejected_even_if_files_unchanged(self):
        self.archive_fixture()
        publication = read_json(self.publish)
        publication['at'] = 'different metadata'
        write_json(self.publish, publication)
        with patch.dict(os.environ, {'SCB_PRO_ARCHIVE_STATE_ROOT': str(self.state_root)}):
            with self.assertRaisesRegex(ValueError, 'frozen publication'):
                state(self.work)

    def test_changed_archive_fails_and_never_falls_back_to_old_source(self):
        self.archive_fixture()
        (self.destination / '原名.docx').write_bytes(b'changed')
        with patch.dict(os.environ, {'SCB_PRO_ARCHIVE_STATE_ROOT': str(self.state_root)}):
            with self.assertRaisesRegex(ValueError, 'Archived product changed'):
                state(self.work)

    def test_partial_source_cleanup_is_resolvable_but_new_source_bytes_are_refused(self):
        self.archive_fixture()
        self.source.mkdir(parents=True)
        (self.source / '原名.docx').write_bytes(b'word')
        with patch.dict(os.environ, {'SCB_PRO_ARCHIVE_STATE_ROOT': str(self.state_root)}):
            self.assertEqual(state(self.work)[1], self.destination)
            added = self.source / 'new-version.txt'
            added.write_bytes(b'preserve new version')
            with self.assertRaisesRegex(ValueError, 'new or changed files'):
                state(self.work)
            self.assertEqual(added.read_bytes(), b'preserve new version')

    def test_nonpublished_run_and_unregistered_paths_do_not_use_locator(self):
        self.archive_fixture()
        run_path = self.work / '.product-v2/run.json'
        run = read_json(run_path)
        run['status'] = 'finalized'
        write_json(run_path, run)
        with patch.dict(os.environ, {'SCB_PRO_ARCHIVE_STATE_ROOT': str(self.state_root)}):
            self.assertEqual(state(self.work)[1], self.source)
        run['status'] = 'published'
        run['output'] = str(self.root / 'unregistered-output')
        write_json(run_path, run)
        with patch.dict(os.environ, {'SCB_PRO_ARCHIVE_STATE_ROOT': str(self.state_root)}):
            self.assertEqual(state(self.work)[1], self.root / 'unregistered-output')


@unittest.skipUnless(os.name == 'nt', 'Windows PowerShell 7 unattended runner')
class WeeklyArchiveWrapperTests(unittest.TestCase):
    setUp = archive_fixtures.ArchiveTests.setUp
    tearDown = archive_fixtures.ArchiveTests.tearDown

    def powershell(self, script, *extra, command=None):
        executable = shutil.which('pwsh.exe') or shutil.which('pwsh')
        if not executable:
            raise ValueError('The existing PowerShell 7 launcher is required; do not weaken Windows PowerShell 5.1 policy')
        args = [str(executable), '-NoProfile', '-NonInteractive', '-WindowStyle', 'Hidden']
        if command is not None:
            args += ['-Command', command]
        else:
            args += ['-File', str(script), *map(str, extra)]
        completed = subprocess.run(args, capture_output=True, text=True, encoding='utf-8', errors='replace',
                                   creationflags=subprocess.CREATE_NO_WINDOW, timeout=60)
        return completed

    def runner(self, mode='Plan'):
        return self.powershell(Path(__file__).resolve().parents[1] / 'scripts/Run-WeeklyArchive.ps1',
                               '-Mode', mode, '-SourceRoot', self.source_root, '-DestinationRoot', self.destination_root,
                               '-BatchRoot', self.batch_root, '-StateRoot', self.state_root, '-PythonPath', sys.executable)

    def summary(self):
        reports = list((self.state_root / 'logs').glob('*.runner.json'))
        self.assertEqual(len(reports), 1)
        return read_json(reports[0])

    def test_default_plan_creates_logs_but_leaves_products_unchanged(self):
        result = self.runner()
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        report = self.summary()
        self.assertEqual(report['status'], 'planned')
        self.assertTrue(self.source.exists())
        self.assertFalse(self.destination.exists())
        self.assertEqual(len(read_json(report['plan_log'])['eligible']), 1)
        self.assertEqual(report['python'], sys.executable)

    def test_apply_runs_both_cli_phases_and_records_verified_location(self):
        result = self.runner('Apply')
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        report = self.summary()
        self.assertEqual(report['status'], 'completed')
        self.assertEqual(report['plan_exit_code'], 0)
        self.assertEqual(report['apply_exit_code'], 0)
        self.assertFalse(self.source.exists())
        self.assertEqual(archive.resolve_location(self.state_root, self.source, self.files), self.destination)

    def test_disconnected_destination_is_logged_and_not_created(self):
        self.destination_root.rmdir()
        result = self.runner('Apply')
        self.assertEqual(result.returncode, 2, result.stdout + result.stderr)
        report = self.summary()
        self.assertEqual(report['status'], 'retained')
        self.assertIn('disconnected', report['reason'])
        self.assertNotIn('apply_log', report)
        self.assertFalse(self.destination_root.exists())
        self.assertTrue(self.source.exists())

    def test_active_case_is_retained_without_starting_apply(self):
        write_json(self.batch_root / 'queue.json', [{'batch_id': 'batch-a', 'case_id': 'case-a',
                   'stage': 'build', 'status': 'active', 'owner': archive.identity(os.getpid())}])
        result = self.runner('Apply')
        self.assertEqual(result.returncode, 2, result.stdout + result.stderr)
        report = self.summary()
        self.assertNotIn('apply_log', report)
        self.assertTrue(self.source.exists())

    def test_native_wrapper_lock_refuses_competing_run_without_deleting_lock(self):
        self.state_root.mkdir()
        lock = self.state_root / 'weekly-run.lock'
        lock.write_bytes(b'')
        with archive.WindowsHandle(lock):
            result = self.runner('Apply')
        self.assertEqual(result.returncode, 2)
        self.assertTrue(lock.exists())
        self.assertFalse(self.destination.exists())
        self.assertTrue(self.source.exists())
        result = self.runner('Plan')
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def installer(self, *extra):
        return self.powershell(Path(__file__).resolve().parents[1] / 'scripts/Install-WeeklyArchive.ps1',
                               '-SourceRoot', self.source_root, '-DestinationRoot', self.destination_root,
                               '-BatchRoot', self.batch_root, '-StateRoot', self.state_root,
                               '-PythonPath', sys.executable, *extra)

    def test_install_prepares_review_artifacts_without_registering_any_task(self):
        result = self.installer()
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        plan = read_json(self.state_root / 'weekly-task-plan.json')
        self.assertFalse(plan['registered'])
        self.assertEqual(plan['logon_type'], 'InteractiveToken')
        self.assertTrue(plan['hidden'])
        self.assertIn('-WindowStyle Hidden', plan['arguments'])
        self.assertNotIn('-ExecutionPolicy', plan['arguments'])
        self.assertEqual(Path(plan['execution']).name, 'pwsh.exe')
        self.assertIn('-Mode Apply', plan['arguments'])
        self.assertEqual(plan['day'], 'Sunday')
        self.assertEqual(plan['local_time'], '22:00')
        self.assertRegex(plan['user_sid'], r'^S-\d+(?:-\d+)+$')
        generated = self.state_root / 'Register-WeeklyArchive.ps1'
        result = self.powershell(generated)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertTrue(self.source.exists())
        self.assertFalse(self.destination.exists())

    def test_install_whatif_writes_nothing_and_never_overwrites_reviewed_plan(self):
        result = self.installer('-WhatIf')
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertFalse(self.state_root.exists())
        result = self.installer()
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        plan = self.state_root / 'weekly-task-plan.json'
        frozen = digest(plan)
        result = self.installer()
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(digest(plan), frozen)

    def test_review_script_whatif_and_unknown_existing_task_do_not_call_registration(self):
        self.assertEqual(self.installer().returncode, 0)
        script = str(self.state_root / 'Register-WeeklyArchive.ps1').replace("'", "''")
        # Stub discovery so tests neither read nor mutate the real Task Scheduler.
        command = "[Console]::OutputEncoding=[Text.UTF8Encoding]::new($false); function Get-ScheduledTask { return $null }; function Register-ScheduledTask { throw 'unexpected registration' }; & '" + script + "' -Register -WhatIf"
        result = self.powershell(None, command=command)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        command = "function Get-ScheduledTask { return [pscustomobject]@{Actions=@();Triggers=@();Principal=[pscustomobject]@{UserId='unknown'}} }; function Register-ScheduledTask { throw 'unexpected registration' }; & '" + script + "' -Register"
        result = self.powershell(None, command=command)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('will not be overwritten', result.stderr)

    def existing_task_stub(self, user_id, mutation='', forbid_discovery=False):
        script = str(self.state_root / 'Register-WeeklyArchive.ps1').replace("'", "''")
        plan_path = str(self.state_root / 'weekly-task-plan.json').replace("'", "''")
        user_id = user_id.replace("'", "''")
        stub = """
$ArchiveStubPlan=Get-Content -LiteralPath '__PLAN__' -Raw -Encoding UTF8 | ConvertFrom-Json
$ArchiveStubUser='__USER__'
function Get-ScheduledTask {
    $ArchiveTask=[pscustomobject]@{
        Actions=@([pscustomobject]@{Execute=$ArchiveStubPlan.execution;Arguments=$ArchiveStubPlan.arguments;WorkingDirectory=$ArchiveStubPlan.working_directory})
        Triggers=@([pscustomobject]@{DaysOfWeek=1;WeeksInterval=1;StartBoundary=([datetime]::Today.AddHours(22)).ToString('s')})
        Principal=[pscustomobject]@{UserId=$ArchiveStubUser;LogonType='Interactive';RunLevel='Limited'}
        Settings=[pscustomobject]@{Hidden=$true;MultipleInstances='IgnoreNew';StartWhenAvailable=$true}
    }
    __MUTATION__
    return $ArchiveTask
}
function Register-ScheduledTask { throw 'unexpected registration' }
& '__SCRIPT__' -Register
"""
        if forbid_discovery:
            mutation = "throw 'unexpected task discovery'"
        command = stub.replace('__PLAN__', plan_path).replace('__USER__', user_id).replace('__MUTATION__', mutation).replace('__SCRIPT__', script)
        return self.powershell(None, command=command)

    def test_same_windows_sid_accepts_task_and_plan_account_aliases(self):
        self.assertEqual(self.installer().returncode, 0)
        plan_path = self.state_root / 'weekly-task-plan.json'
        original = read_json(plan_path)
        account_aliases = (original['user'], original['user'].rsplit('\\', 1)[-1], original['user_sid'])
        for alias in account_aliases:
            with self.subTest(existing_user=alias):
                result = self.existing_task_stub(alias)
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                observed = json.loads(result.stdout)
                self.assertEqual(observed['status'], 'already_present')
                self.assertFalse(observed['changed'])
            with self.subTest(reviewed_user=alias):
                plan = dict(original, user=alias)
                write_json(plan_path, plan)
                result = self.existing_task_stub(original['user'])
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                self.assertEqual(json.loads(result.stdout)['status'], 'already_present')
                write_json(plan_path, original)
        # Existing reviewed plans are verified by account translation without
        # silently rewriting their old JSON or requiring newly added metadata.
        legacy = dict(original)
        del legacy['user_sid']
        write_json(plan_path, legacy)
        frozen = digest(plan_path)
        result = self.existing_task_stub(account_aliases[1])
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(digest(plan_path), frozen)

    def test_different_or_unresolvable_existing_user_sid_is_never_adopted(self):
        self.assertEqual(self.installer().returncode, 0)
        for alias in ('S-1-5-18', 'archive-user-that-does-not-exist-4fc898d2', ''):
            with self.subTest(existing_user=alias):
                result = self.existing_task_stub(alias)
                self.assertNotEqual(result.returncode, 0)
                self.assertIn('will not be overwritten', result.stderr)
                self.assertNotIn('unexpected registration', result.stderr)

    def test_reviewed_user_sid_must_match_name_and_actual_current_identity(self):
        self.assertEqual(self.installer().returncode, 0)
        plan_path = self.state_root / 'weekly-task-plan.json'
        original = read_json(plan_path)
        cases = (
            (dict(original, user='archive-user-that-does-not-exist-4fc898d2'), 'cannot be verified'),
            (dict(original, user_sid=original['user']), 'valid literal Windows SID'),
            (dict(original, user_sid=''), 'valid literal Windows SID'),
            (dict(original, user_sid='S-1-99999999999999999999999'), 'valid literal Windows SID'),
            (dict(original, user_sid='S-1-5-18'), 'reviewed user name and SID differ'),
            (dict(original, user='S-1-5-18', user_sid='S-1-5-18'), 'registration user SID differs'),
            ({key: value for key, value in dict(original, user='S-1-5-18').items() if key != 'user_sid'}, 'registration user SID differs'),
        )
        for plan, expected in cases:
            with self.subTest(user=plan['user'], sid=plan.get('user_sid')):
                write_json(plan_path, plan)
                result = self.existing_task_stub(original['user'], forbid_discovery=True)
                self.assertNotEqual(result.returncode, 0)
                self.assertIn(expected, result.stderr)
                self.assertNotIn('unexpected task discovery', result.stderr)
                self.assertNotIn('unexpected registration', result.stderr)

    def test_same_sid_still_requires_exact_task_paths_and_policy(self):
        self.assertEqual(self.installer().returncode, 0)
        plan = read_json(self.state_root / 'weekly-task-plan.json')
        alias = plan['user'].rsplit('\\', 1)[-1]
        for mutation in ("$ArchiveTask.Actions[0].Execute+='-unknown'", "$ArchiveTask.Settings.Hidden=$false",
                         "$ArchiveTask.Principal.LogonType='Password'"):
            with self.subTest(mutation=mutation):
                result = self.existing_task_stub(alias, mutation)
                self.assertNotEqual(result.returncode, 0)
                self.assertIn('will not be overwritten', result.stderr)
                self.assertNotIn('unexpected registration', result.stderr)


if __name__ == '__main__':
    unittest.main()
