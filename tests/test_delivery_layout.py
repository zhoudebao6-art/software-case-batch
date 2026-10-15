"""Frozen delivery layouts and their public workflow boundaries; fixture data only."""
import copy
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch
import zipfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
sys.path.insert(0, str(ROOT / 'tests'))
import archive_products as archive
import proflow
import test_archive_products as archive_fixtures
from common import delivery_paths, digest, file_map, read_json, state, write_json
from contracts import delivery_layout
from media_evidence import frozen_video


# These are user-visible contract expectations, independent of the resolver.
LAYOUTS = {
    'legacy-v1': ('模拟系统', '项目源码.zip', '演示视频.mp4'),
    'system-materials-v2': ('系统材料', '源代码.zip', '操作视频.mp4'),
}
NEW = 'system-materials-v2'
HISTORICAL = None  # Existing run.json without a delivery_layout_version field.


class DeliveryFixture(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix='delivery-layout-')
        self.root = Path(self.tmp.name)
        self.source = self.root / '原始正文与公式参考.docx'
        with zipfile.ZipFile(self.source, 'w') as package:
            package.writestr('word/document.xml', '<document>正文公式参考</document>')

    def tearDown(self):
        self.tmp.cleanup()

    def workspace(self, name):
        work = self.root / name
        work.mkdir()
        return work

    def expected(self, output, version=HISTORICAL):
        system, source, video = LAYOUTS[version or 'legacy-v1']
        return {'word': output / self.source.name, 'system': output / system,
                'source_zip': output / system / source,
                'video': output / system / video, 'data_dir': output / system / '数据'}

    def run_record(self, work, output, version=HISTORICAL):
        result = {'schema_version': 2, 'workspace': str(work), 'output': str(output),
                  'word_name': self.source.name, 'source_docx': str(self.source),
                  'source_docx_sha256': digest(self.source), 'title': '设备业务管理',
                  'status': 'prepared', 'fixture_only': True}
        if version is not None:
            result['delivery_layout_version'] = version
        result.update({key: str(value) for key, value in self.expected(output, version).items()
                       if key != 'system'})
        return result

    def fill_delivery(self, output, version=HISTORICAL):
        paths = self.expected(output, version)
        paths['data_dir'].mkdir(parents=True)
        shutil.copyfile(self.source, paths['word'])
        with zipfile.ZipFile(paths['source_zip'], 'w') as package:
            package.writestr('app.py', 'print("运行")\n')
        paths['video'].write_bytes(b'fixture-video-not-real-media')
        (paths['data_dir'] / '明细.csv').write_text('编号,值\n001,2\n', encoding='utf-8-sig')
        return paths

    def finalized_parent(self, name, version):
        work = self.workspace(name)
        output = self.root / (name + '-delivery')
        self.fill_delivery(output, version)
        run = self.run_record(work, output, version)
        run['status'] = 'finalized'
        write_json(work / '.product-v2/run.json', run)
        receipt = work / '.product-v2/final-receipt.json'
        # This test-only historical receipt does not assert a real independent pass.
        write_json(receipt, {'status': 'complete', 'fixture_only': True,
                             'files': file_map(output), 'source_docx_sha256': digest(self.source)})
        return work, output, run, receipt


class FrozenResolverTests(DeliveryFixture):
    def test_declared_layout_and_historical_missing_field_have_exact_paths(self):
        for version in (HISTORICAL, 'legacy-v1', NEW):
            with self.subTest(version=version):
                output = self.root / (version or 'unmarked')
                run = self.run_record(self.root / 'work', output, version)
                before = copy.deepcopy(run)
                actual = delivery_paths(run)
                self.assertEqual(actual['version'], version or 'legacy-v1')
                for key, expected in self.expected(output, version).items():
                    self.assertEqual(actual[key], expected)
                self.assertEqual(run, before)

    def test_read_location_override_resolves_current_tree_without_rewriting_original_aliases(self):
        for version in (HISTORICAL, NEW):
            with self.subTest(version=version):
                original = self.root / 'daily'
                target = self.root / 'weekly'
                run = self.run_record(self.root / 'work', original, version)
                frozen = copy.deepcopy(run)
                actual = delivery_paths(run, target)
                for key, expected in self.expected(target, version).items():
                    self.assertEqual(actual[key], expected)
                self.assertEqual(run, frozen)

    def test_unknown_declared_versions_fail_closed(self):
        for version in ('future-v3', '', None, 2, ['legacy-v1']):
            with self.subTest(version=version):
                run = {'output': str(self.root / 'out'), 'delivery_layout_version': version}
                with self.assertRaisesRegex(ValueError, 'Unknown frozen delivery layout'):
                    delivery_paths(run)

    def test_every_stored_path_alias_is_validated_even_during_relocation(self):
        for version in (HISTORICAL, NEW):
            output = self.root / 'original'
            for key in ('word', 'system', 'source_zip', 'video', 'data_dir'):
                for value in (str(self.root / 'wrong-alias'), 7):
                    with self.subTest(version=version, alias=key, value=value):
                        run = self.run_record(self.root / 'work', output, version)
                        run[key] = value
                        with self.assertRaisesRegex(ValueError, 'Frozen delivery path differs'):
                            delivery_paths(run, self.root / 'archive')


class ExactLayoutTests(DeliveryFixture):
    def test_complete_layout_accepts_each_frozen_contract(self):
        for version in (HISTORICAL, NEW):
            with self.subTest(version=version):
                output = self.root / (version or 'legacy')
                self.fill_delivery(output, version)
                self.assertEqual(delivery_layout(output, self.run_record(self.root / 'work', output, version)),
                                 output / self.source.name)

    def test_unexpected_files_and_empty_directories_are_rejected_at_both_levels(self):
        for version in (HISTORICAL, NEW):
            for level in ('root', 'system'):
                for directory in (False, True):
                    with self.subTest(version=version, level=level, directory=directory):
                        output = self.root / f'{version}-{level}-{directory}'
                        paths = self.fill_delivery(output, version)
                        extra = (output if level == 'root' else paths['system']) / 'extra'
                        extra.mkdir() if directory else extra.write_bytes(b'extra')
                        with self.assertRaisesRegex(ValueError, 'exactly'):
                            delivery_layout(output, self.run_record(self.root / 'work', output, version))

    def test_a_complete_foreign_layout_cannot_satisfy_the_frozen_run(self):
        for frozen, actual in ((HISTORICAL, NEW), (NEW, HISTORICAL)):
            with self.subTest(frozen=frozen):
                output = self.root / (frozen or 'legacy')
                self.fill_delivery(output, actual)
                with self.assertRaisesRegex(ValueError, 'exactly'):
                    delivery_layout(output, self.run_record(self.root / 'work', output, frozen))


class PrepareLayoutTests(DeliveryFixture):
    def test_new_full_prepare_freezes_new_layout_and_resolved_aliases(self):
        work = self.workspace('new-work')
        output = self.root / 'new-delivery'
        run = proflow.prepare(work, output, '设备业务管理', self.source)
        self.assertEqual(run['delivery_layout_version'], NEW)
        for key in ('word', 'source_zip', 'video', 'data_dir'):
            self.assertEqual(run[key], str(self.expected(output, NEW)[key]))
        prompt = (work / '.product-v2/深化命令词.txt').read_text(encoding='utf-8')
        for key in ('source_zip', 'video', 'data_dir'):
            self.assertIn(str(self.expected(output, NEW)[key]), prompt)
        self.assertNotIn('模拟系统', prompt)

    def test_existing_unmarked_prepare_is_idempotent_without_migration_or_prompt_rewrite(self):
        work = self.workspace('historical-work')
        output = self.root / 'historical-delivery'
        run = proflow.prepare(work, output, '设备业务管理', self.source)
        run.pop('delivery_layout_version')
        run.update({key: str(value) for key, value in self.expected(output).items() if key != 'system'})
        write_json(work / '.product-v2/run.json', run)
        prompt = work / '.product-v2/深化命令词.txt'
        prompt.write_text('frozen historical instructions\n', encoding='utf-8')
        self.fill_delivery(output)
        before = file_map(work), file_map(output)
        self.assertEqual(proflow.prepare(work, output, '设备业务管理', self.source), run)
        self.assertEqual((file_map(work), file_map(output)), before)
        self.assertNotIn('delivery_layout_version', read_json(work / '.product-v2/run.json'))

    def test_document_and_package_revisions_inherit_parent_layout_without_parent_writes(self):
        for version in (HISTORICAL, NEW):
            base, base_output, _, receipt = self.finalized_parent('parent-' + str(version), version)
            frozen = file_map(base), file_map(base_output), digest(receipt)
            for scope in ('document', 'package'):
                with self.subTest(version=version, scope=scope):
                    child = self.workspace(f'child-{version}-{scope}')
                    output = self.root / f'child-output-{version}-{scope}'
                    run = proflow.prepare(child, output, '设备业务管理', self.source,
                                          revision_of=base, revision_scope=scope)
                    self.assertEqual(run['delivery_layout_version'], version or 'legacy-v1')
                    expected = self.expected(output, version)
                    self.assertEqual(run['video'], str(expected['video']))
                    self.assertEqual(run['source_zip'], str(expected['source_zip']))
                    self.assertEqual(run['revision_of']['system_files'],
                                     file_map(self.expected(base_output, version)['system']))
            self.assertEqual((file_map(base), file_map(base_output), digest(receipt)), frozen)

    def test_adopt_draft_supports_both_layouts_and_only_package_scope_may_change_zip(self):
        for version in (HISTORICAL, NEW):
            base, base_output, _, _ = self.finalized_parent('adopt-parent-' + str(version), version)
            for scope in ('document', 'package'):
                with self.subTest(version=version, scope=scope):
                    child = self.workspace(f'adopt-child-{version}-{scope}')
                    output = self.root / f'adopt-output-{version}-{scope}'
                    shutil.copytree(base_output, output)
                    if scope == 'package':
                        with zipfile.ZipFile(self.expected(output, version)['source_zip'], 'w') as package:
                            package.writestr('app.py', 'print("更新")\n')
                    before = file_map(output)
                    with self.assertRaisesRegex(ValueError, 'already exists'):
                        proflow.prepare(child, output, '设备业务管理', self.source, revision_of=base,
                                        revision_scope=scope)
                    run = proflow.prepare(child, output, '设备业务管理', self.source, revision_of=base,
                                          revision_scope=scope, adopt_draft=True)
                    self.assertEqual(run['delivery_layout_version'], version or 'legacy-v1')
                    self.assertEqual(run['adopted_draft_files'], before)
                    self.assertEqual(file_map(output), before)

    def test_adopt_draft_rejects_changed_video_and_csv_in_either_scope(self):
        for version in (HISTORICAL, NEW):
            base, base_output, _, _ = self.finalized_parent('drift-parent-' + str(version), version)
            for scope in ('document', 'package'):
                for artifact in ('video', 'csv'):
                    with self.subTest(version=version, scope=scope, artifact=artifact):
                        name = f'drift-{version}-{scope}-{artifact}'
                        child = self.workspace(name)
                        output = self.root / (name + '-output')
                        shutil.copytree(base_output, output)
                        paths = self.expected(output, version)
                        changed = paths['video'] if artifact == 'video' else paths['data_dir'] / '明细.csv'
                        changed.write_bytes(b'changed')
                        before = file_map(output)
                        with self.assertRaisesRegex(ValueError, 'preserve the complete finalized system'):
                            proflow.prepare(child, output, '设备业务管理', self.source, revision_of=base,
                                            revision_scope=scope, adopt_draft=True)
                        self.assertFalse((child / '.product-v2').exists())
                        self.assertEqual(file_map(output), before)


class PublicationLayoutTests(DeliveryFixture):
    def publish_fixture(self, name, version):
        work = self.workspace(name)
        candidate = self.root / (name + '-candidate')
        self.fill_delivery(candidate, version)
        run = self.run_record(work, candidate, version)
        write_json(work / '.product-v2/run.json', run)
        final = work / '.product-v2/final-receipt.json'
        write_json(final, {'status': 'complete', 'delivery_state': 'verified-candidate',
                           'fixture_only': True, 'files': file_map(candidate)})
        return work, candidate, final

    def test_publish_updates_aliases_preserves_layout_and_never_rewrites_acceptance(self):
        for version in (HISTORICAL, NEW):
            with self.subTest(version=version):
                work, candidate, final = self.publish_fixture('publish-' + str(version), version)
                destination = self.root / ('published-' + str(version))
                frozen_receipt = final.read_bytes()
                files = file_map(candidate)
                with patch.object(proflow, 'cleanup_ready'):
                    result = proflow.publish(work, destination)
                self.assertEqual(result['files'], files)
                self.assertFalse(candidate.exists())
                self.assertEqual(file_map(destination), files)
                _, actual, run = state(work)
                self.assertEqual(actual, destination)
                self.assertEqual(run.get('delivery_layout_version'), version)
                self.assertNotIn('system',run)
                for key in ('word', 'source_zip', 'video', 'data_dir'):
                    self.assertEqual(run[key], str(self.expected(destination, version)[key]))
                self.assertEqual(final.read_bytes(), frozen_receipt)
                frozen_run = (work / '.product-v2/run.json').read_bytes()
                with patch.object(proflow, 'cleanup_ready'):
                    self.assertEqual(proflow.publish(work, destination), result)
                self.assertEqual((work / '.product-v2/run.json').read_bytes(), frozen_run)
                self.assertEqual(final.read_bytes(), frozen_receipt)

    def test_publish_relocates_accepted_optional_system_alias_for_each_layout(self):
        for version in (HISTORICAL, 'legacy-v1', NEW):
            with self.subTest(version=version):
                work,candidate,final=self.publish_fixture('system-alias-'+str(version),version)
                run_path=work/'.product-v2/run.json';run=read_json(run_path)
                run['system']=str(self.expected(candidate,version)['system'])
                write_json(run_path,run)
                destination=self.root/('system-alias-published-'+str(version))
                frozen_receipt=final.read_bytes();files=file_map(candidate)
                with patch.object(proflow,'cleanup_ready'):
                    published=proflow.publish(work,destination)
                _,actual,updated=state(work)
                self.assertEqual(actual,destination)
                self.assertEqual(updated['system'],str(self.expected(destination,version)['system']))
                for key,path in self.expected(destination,version).items():
                    self.assertEqual(updated[key],str(path))
                self.assertEqual(file_map(destination),files)
                self.assertEqual(final.read_bytes(),frozen_receipt)
                self.assertEqual(read_json(work/'.product-v2/publish-intent.json')['run_snapshot'],run)
                frozen_run=run_path.read_bytes()
                with patch.object(proflow,'cleanup_ready'):
                    self.assertEqual(proflow.publish(work,destination),published)
                self.assertEqual(run_path.read_bytes(),frozen_run)

    def test_optional_system_alias_recovers_before_and_after_run_update(self):
        for version in (HISTORICAL, 'legacy-v1', NEW):
            for boundary in ('run.json','publish-receipt.json'):
                with self.subTest(version=version,boundary=boundary):
                    name='system-recovery-'+str(version)+'-'+boundary
                    work,candidate,final=self.publish_fixture(name,version)
                    run_path=work/'.product-v2/run.json';run=read_json(run_path)
                    run['system']=str(self.expected(candidate,version)['system'])
                    write_json(run_path,run)
                    destination=self.root/(name+'-published')
                    frozen_receipt=final.read_bytes();files=file_map(candidate)
                    real_write=proflow.write_json

                    def interrupted(path,value):
                        if Path(path).name==boundary:
                            raise OSError('fixture: optional-system publication interruption')
                        return real_write(path,value)

                    with patch.object(proflow,'cleanup_ready'),patch.object(proflow,'write_json',interrupted):
                        with self.assertRaisesRegex(OSError,'optional-system'):
                            proflow.publish(work,destination)
                    self.assertFalse(candidate.exists())
                    self.assertEqual(file_map(destination),files)
                    intermediate=read_json(run_path)
                    expected_root=destination if boundary=='publish-receipt.json' else candidate
                    self.assertEqual(intermediate['system'],str(self.expected(expected_root,version)['system']))
                    with patch.object(proflow,'cleanup_ready'):
                        self.assertEqual(proflow.publish(work,destination)['status'],'published')
                    _,actual,updated=state(work)
                    self.assertEqual(actual,destination)
                    self.assertEqual(updated['system'],str(self.expected(destination,version)['system']))
                    self.assertEqual(final.read_bytes(),frozen_receipt)

    def test_published_optional_alias_base_and_both_revision_scopes_stay_usable(self):
        for version in (HISTORICAL,NEW):
            with self.subTest(version=version):
                parent,candidate,final=self.publish_fixture('alias-base-'+str(version),version)
                parent_run_path=parent/'.product-v2/run.json';parent_run=read_json(parent_run_path)
                parent_run['system']=str(self.expected(candidate,version)['system'])
                write_json(parent_run_path,parent_run)
                parent_destination=self.root/('alias-base-published-'+str(version))
                with patch.object(proflow,'cleanup_ready'):
                    proflow.publish(parent,parent_destination)
                frozen_parent={path:path.read_bytes() for path in (parent_run_path,final,parent/'.product-v2/publish-receipt.json')}
                for scope in ('document','package'):
                    name='alias-child-'+str(version)+'-'+scope
                    child=self.workspace(name);output=self.root/(name+'-candidate')
                    run=proflow.prepare(child,output,'设备业务管理',self.source,revision_of=parent,revision_scope=scope)
                    inherited=copy.deepcopy(run['revision_of'])
                    self.assertEqual(run['delivery_layout_version'],version or 'legacy-v1')
                    self.fill_delivery(output,version)
                    run['system']=str(self.expected(output,version)['system'])
                    write_json(child/'.product-v2/run.json',run)
                    child_final=child/'.product-v2/final-receipt.json'
                    write_json(child_final,{'status':'complete','delivery_state':'verified-candidate','fixture_only':True,
                              'scope':scope+'-revision','files':file_map(output)})
                    frozen_child_receipt=child_final.read_bytes();destination=self.root/(name+'-published')
                    with patch.object(proflow,'cleanup_ready'):
                        proflow.publish(child,destination)
                    _,actual,published_run=state(child)
                    self.assertEqual(actual,destination)
                    self.assertEqual(published_run['system'],str(self.expected(destination,version)['system']))
                    self.assertEqual(published_run['revision_of'],inherited)
                    self.assertEqual(child_final.read_bytes(),frozen_child_receipt)
                self.assertEqual({path:path.read_bytes() for path in frozen_parent},frozen_parent)

    def test_publish_resumes_after_directory_rename_with_same_layout_and_frozen_receipt(self):
        for version in (HISTORICAL, NEW):
            with self.subTest(version=version):
                work, candidate, final = self.publish_fixture('recover-' + str(version), version)
                destination = self.root / ('recovered-' + str(version))
                frozen_receipt = final.read_bytes()
                real_write = proflow.write_json

                def fail_run_update(path, value):
                    if Path(path).name == 'run.json' and value.get('status') == 'published':
                        raise OSError('fixture: interrupted after atomic rename')
                    return real_write(path, value)

                with patch.object(proflow, 'cleanup_ready'), patch.object(proflow, 'write_json', fail_run_update):
                    with self.assertRaisesRegex(OSError, 'interrupted'):
                        proflow.publish(work, destination)
                self.assertFalse(candidate.exists())
                self.assertTrue(destination.exists())
                with patch.object(proflow, 'cleanup_ready'):
                    self.assertEqual(proflow.publish(work, destination)['status'], 'published')
                _, output, run = state(work)
                self.assertEqual(output, destination)
                self.assertEqual(run.get('delivery_layout_version'), version)
                self.assertEqual(run['video'], str(self.expected(destination, version)['video']))
                self.assertEqual(final.read_bytes(), frozen_receipt)

    def test_publish_refuses_layout_and_alias_rewrite_while_candidate_bytes_stay_old(self):
        for version, changed in ((HISTORICAL, NEW), (NEW, 'legacy-v1')):
            with self.subTest(version=version):
                work, candidate, final = self.publish_fixture('rewrite-' + str(version), version)
                run_path = work / '.product-v2/run.json'
                run = read_json(run_path)
                run['delivery_layout_version'] = changed
                run.update({key: str(value) for key, value in self.expected(candidate, changed).items()
                            if key != 'system'})
                write_json(run_path, run)
                frozen_receipt, frozen_bytes = final.read_bytes(), file_map(candidate)
                destination = self.root / ('rewritten-' + str(version))
                with patch.object(proflow, 'cleanup_ready'), self.assertRaisesRegex(ValueError, 'exactly'):
                    proflow.publish(work, destination)
                self.assertFalse(destination.exists())
                self.assertEqual(file_map(candidate), frozen_bytes)
                self.assertEqual(final.read_bytes(), frozen_receipt)
                self.assertEqual(read_json(run_path), run)

    def test_publish_refuses_run_layout_that_disagrees_with_explicit_acceptance_layout(self):
        for version, rejected in ((HISTORICAL, NEW), (NEW, 'legacy-v1')):
            with self.subTest(version=version):
                work, candidate, final = self.publish_fixture('binding-' + str(version), version)
                receipt = read_json(final)
                receipt['delivery_layout_version'] = rejected
                write_json(final, receipt)
                frozen = file_map(work), file_map(candidate)
                destination = self.root / ('binding-destination-' + str(version))
                with patch.object(proflow, 'cleanup_ready'), self.assertRaisesRegex(ValueError, 'frozen acceptance receipt'):
                    proflow.publish(work, destination)
                self.assertFalse(destination.exists())
                self.assertEqual((file_map(work), file_map(candidate)), frozen)


class ScanLayoutTests(DeliveryFixture):
    def test_original_word_and_exact_legacy_container_are_narrow_exemptions(self):
        for version in (HISTORICAL, NEW):
            with self.subTest(version=version):
                output = self.root / (version or 'legacy')
                self.fill_delivery(output, version)
                run = self.run_record(self.root / 'work', output, version)
                self.assertTrue(proflow.scan_delivery(output, run['word_name'], run)['passed'])
                with self.assertRaisesRegex(ValueError, 'Word name differs'):
                    proflow.scan_delivery(output, '替换正文.docx', run)

    def test_a_second_word_with_similar_name_is_not_exempt(self):
        for version in (HISTORICAL, NEW):
            with self.subTest(version=version):
                output = self.root / (version or 'legacy')
                self.fill_delivery(output, version)
                second = output / ('副本-' + self.source.name)
                shutil.copyfile(self.source, second)
                run = self.run_record(self.root / 'work', output, version)
                result = proflow.scan_delivery(output, run=run)
                self.assertFalse(result['passed'])
                self.assertTrue(any(hit['path'] == second.name for hit in result['hits']))

    def test_container_exception_never_hides_code_csv_or_nested_restricted_names(self):
        for version in (HISTORICAL, NEW):
            with self.subTest(version=version):
                output = self.root / (version or 'legacy')
                paths = self.fill_delivery(output, version)
                with zipfile.ZipFile(paths['source_zip'], 'w') as package:
                    package.writestr('app.py', 'label = "模拟系统"\n')
                    package.writestr('模拟系统/worker.py', 'print(1)\n')
                (paths['data_dir'] / '明细.csv').write_text('编号,值\n001,模拟系统\n', encoding='utf-8-sig')
                nested = paths['system'] / '模拟系统' / 'main.py'
                nested.parent.mkdir()
                nested.write_text('print(1)\n', encoding='utf-8')
                result = proflow.scan_delivery(output, run=self.run_record(self.root / 'work', output, version))
                hits = {hit['path'] for hit in result['hits']}
                archive_name = paths['source_zip'].relative_to(output).as_posix()
                self.assertIn(archive_name + '!app.py', hits)
                self.assertIn(archive_name + '!模拟系统/worker.py', hits)
                self.assertIn((paths['data_dir'] / '明细.csv').relative_to(output).as_posix(), hits)
                self.assertIn(nested.relative_to(output).as_posix(), hits)

    def test_new_layout_does_not_grant_a_top_level_legacy_container_exception(self):
        output = self.root / 'new-output'
        self.fill_delivery(output, NEW)
        wrong = output / '模拟系统' / 'main.py'
        wrong.parent.mkdir()
        wrong.write_text('print(1)\n', encoding='utf-8')
        result = proflow.scan_delivery(output, run=self.run_record(self.root / 'work', output, NEW))
        self.assertTrue(any(hit['path'] == '模拟系统/main.py' for hit in result['hits']))

    def test_similar_container_and_restricted_csv_filenames_are_not_exempt(self):
        for version in (HISTORICAL, NEW):
            with self.subTest(version=version):
                output = self.root / (version or 'legacy')
                paths = self.fill_delivery(output, version)
                code = output / '模拟系统备份' / 'main.py'
                code.parent.mkdir()
                code.write_text('print(1)\n', encoding='utf-8')
                csv = paths['data_dir'] / '模拟系统.csv'
                csv.write_text('编号,值\n001,2\n', encoding='utf-8-sig')
                result = proflow.scan_delivery(output, run=self.run_record(self.root / 'work', output, version))
                hits = {hit['path'] for hit in result['hits']}
                self.assertIn('模拟系统备份/main.py', hits)
                self.assertIn(csv.relative_to(output).as_posix(), hits)


class WriteAndMediaLayoutTests(DeliveryFixture):
    def writer_fixture(self, name, version):
        work = self.workspace(name)
        output = self.root / (name + '-output')
        output.mkdir()
        run = self.run_record(work, output, version)
        write_json(work / '.product-v2/run.json', run)
        (work / 'app.py').write_text('print(1)\n', encoding='utf-8')
        (work / 'input.csv').write_text('编号,值\n001,2\n', encoding='utf-8-sig')
        package = work / 'source-manifest.json'
        data = work / 'data-manifest.json'
        write_json(package, {'files': ['app.py']})
        write_json(data, {'files': [{'path': 'input.csv', 'reason': '业务记录', 'primary_key': ['编号']}]})
        return work, output, run, package, data

    def test_pack_and_clean_refuse_wrong_output_before_creating_any_artifact(self):
        for version in (HISTORICAL, NEW):
            for name, operation in (('pack', proflow.pack_source), ('clean', proflow.clean_csv)):
                with self.subTest(version=version, operation=name):
                    work, output, _, package, data = self.writer_fixture(f'wrong-{version}-{name}', version)
                    wrong = self.root / f'arbitrary-{version}-{name}'
                    before = file_map(work), file_map(output)
                    with self.assertRaisesRegex(ValueError, 'output differs'):
                        operation(work, wrong, package if name == 'pack' else data)
                    self.assertFalse(wrong.exists())
                    self.assertEqual((file_map(work), file_map(output)), before)

    def test_pack_and_clean_refuse_unknown_layout_before_creating_any_artifact(self):
        for name, operation in (('pack', proflow.pack_source), ('clean', proflow.clean_csv)):
            with self.subTest(operation=name):
                work, output, run, package, data = self.writer_fixture('unknown-' + name, NEW)
                run['delivery_layout_version'] = 'future-v3'
                write_json(work / '.product-v2/run.json', run)
                before = file_map(work), file_map(output)
                with self.assertRaisesRegex(ValueError, 'Unknown frozen delivery layout'):
                    operation(work, output, package if name == 'pack' else data)
                self.assertEqual((file_map(work), file_map(output)), before)
                self.assertEqual(list(output.iterdir()), [])

    def test_media_uses_the_frozen_video_path_in_both_layouts(self):
        for version in (HISTORICAL, NEW):
            with self.subTest(version=version):
                work, output, _, _, _ = self.writer_fixture('media-' + str(version), version)
                expected = self.expected(output, version)['video']
                self.assertEqual(frozen_video(work, expected), expected)
                other = self.expected(output, NEW if version is HISTORICAL else HISTORICAL)['video']
                with self.assertRaisesRegex(ValueError, 'Video path differs'):
                    frozen_video(work, other)

    def test_node_recording_resolves_both_layouts_through_real_python_entry(self):
        node = os.environ.get('SCB_PRO_NODE') or shutil.which('node')
        if not node:
            self.skipTest('Node runtime is unavailable')
        script = ("const fs=require('node:fs');"
                  "const recorder=require(process.argv[1]);"
                  "const workspace=process.argv[2];"
                  "const run=JSON.parse(fs.readFileSync(workspace+'/.product-v2/run.json','utf8'));"
                  "process.stdout.write(JSON.stringify(recorder.frozenDeliveryPaths(workspace,run)));")
        env = dict(os.environ, SCB_PRO_PYTHON=sys.executable)
        for version in (HISTORICAL, NEW):
            with self.subTest(version=version):
                work, output, _, _, _ = self.writer_fixture('node-' + str(version), version)
                before = file_map(work), file_map(output)
                result = subprocess.run([node, '-e', script, str(ROOT / 'scripts/record.cjs'), str(work)],
                                        capture_output=True, text=True, encoding='utf-8', env=env, timeout=30)
                self.assertEqual(result.returncode, 0, result.stderr)
                actual = json.loads(result.stdout)
                self.assertEqual(actual['version'], version or 'legacy-v1')
                for key in ('source_zip', 'video', 'data_dir'):
                    self.assertEqual(Path(actual[key]), self.expected(output, version)[key])
                self.assertEqual(actual['run_sha256'], digest(work / '.product-v2/run.json'))
                self.assertEqual((file_map(work), file_map(output)), before)
                run = read_json(work / '.product-v2/run.json')
                run['delivery_layout_version'] = 'future-v3'
                write_json(work / '.product-v2/run.json', run)
                rejected = subprocess.run([node, '-e', script, str(ROOT / 'scripts/record.cjs'), str(work)],
                                          capture_output=True, text=True, encoding='utf-8', env=env, timeout=30)
                self.assertNotEqual(rejected.returncode, 0)
                self.assertIn('Unknown frozen delivery layout', rejected.stderr)
                self.assertEqual(list(output.iterdir()), [])


class NewLayoutArchiveTests(unittest.TestCase):
    # Reuse setup only; inheriting ArchiveTests would rerun all its frozen tests.
    setUp = archive_fixtures.ArchiveTests.setUp
    tearDown = archive_fixtures.ArchiveTests.tearDown

    def test_archive_and_state_locate_new_layout_without_rewriting_frozen_paths_or_receipts(self):
        system = self.source / '模拟系统'
        system.rename(self.source / '系统材料')
        system = self.source / '系统材料'
        (system / '项目源码.zip').rename(system / '源代码.zip')
        (system / '演示视频.mp4').rename(system / '操作视频.mp4')
        self.files = file_map(self.source)
        proof = read_json(self.proof)
        proof.update({'fixture_only': True, 'reviewed_files': self.files})
        write_json(self.proof, proof)
        final = read_json(self.final)
        final.update({'files': self.files, 'evidence_sha256': digest(self.proof)})
        write_json(self.final, final)
        published = read_json(self.publish)
        published.update({'files': self.files, 'source_receipt_sha256': digest(self.final)})
        write_json(self.publish, published)
        run_path = self.work / '.product-v2/run.json'
        run = read_json(run_path)
        run.update({'schema_version': 2, 'delivery_layout_version': NEW, 'word_name': '原名.docx',
                    'word': str(self.source / '原名.docx'), 'source_zip': str(system / '源代码.zip'),
                    'video': str(system / '操作视频.mp4'), 'data_dir': str(system / '数据')})
        write_json(run_path, run)
        frozen = {path: path.read_bytes() for path in (run_path, self.final, self.publish)}
        result = archive.apply(*self.args)
        self.assertEqual(result['retained'], [])
        self.assertEqual(len(result['archived']), 1)
        self.assertFalse(self.source.exists())
        self.assertEqual(file_map(self.destination), self.files)
        with patch.dict(os.environ, {'SCB_PRO_ARCHIVE_STATE_ROOT': str(self.state_root)}):
            workspace, output, archived_run = state(self.work)
            self.assertEqual(workspace, self.work)
            self.assertEqual(output, self.destination)
            self.assertEqual(archived_run, run)
            paths = delivery_paths(archived_run, output)
            self.assertEqual(paths['source_zip'], self.destination / '系统材料/源代码.zip')
            self.assertEqual(paths['video'], self.destination / '系统材料/操作视频.mp4')
        self.assertEqual({path: path.read_bytes() for path in frozen}, frozen)


if __name__ == '__main__':
    unittest.main()
