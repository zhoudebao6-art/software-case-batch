"""Targeted source/data/media gate counterexamples; no production cases or models."""
import copy
from pathlib import Path
import sys
import unittest
from unittest.mock import patch
import zipfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from common import digest, read_json, write_json
from data_preflight import check_expansion
from proflow import pack_source, prepare, scan_delivery, scan_text
import test_contracts
import test_data_preflight
import test_product_flow
import test_simplified_closure


class SourceDeliveryRuleTests(unittest.TestCase):
    def setUp(self):
        self.f = test_product_flow.FlowTests()
        self.f.setUp()
        self.addCleanup(self.f.tearDown)

    def sources(self, files):
        for name, text in files.items():
            path = self.f.work / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(text, encoding='utf-8')
        return self.f.manifest('source-rule-manifest', {'files': list(files)})

    def handmade_scan(self, files):
        run = read_json(self.f.work / '.product-v2/run.json')
        archive = Path(run['source_zip'])
        archive.parent.mkdir(parents=True, exist_ok=True)
        with zipfile.ZipFile(archive, 'w') as bundle:
            for name, text in files.items():
                bundle.writestr(name, text)
        return scan_delivery(self.f.out, run=run)

    def test_private_dotenv_variants_are_omitted_but_examples_remain(self):
        private = ['.env', '.env.local', 'nested/.ENV.PRODUCTION', '.env.test.local',
                   '.env.example.production']
        examples = ['.env.example', '.env.local.example', '.env.production.sample', '.env.template']
        files = {name: 'API_TOKEN=fixture-private-only\n' for name in private}
        files.update({name: 'API_TOKEN=\n' for name in examples})
        files.update({'app.py': 'print("设备运行")\n', '启动.ps1': 'python app.py\n'})
        manifest = self.sources(files)
        before = {name: digest(self.f.work / name) for name in files}
        receipt = pack_source(self.f.work, self.f.out, manifest)
        self.assertEqual(set(receipt['files']), {*examples, 'app.py', '启动.ps1'})
        self.assertEqual({item['path'] for item in receipt['excluded']}, set(private))
        self.assertEqual({name: digest(self.f.work / name) for name in files}, before)
        self.assertTrue(scan_delivery(self.f.out, run=read_json(self.f.work / '.product-v2/run.json'))['passed'])

    def test_private_dotenv_in_a_handmade_archive_is_blocked(self):
        result = self.handmade_scan({'.env.local': 'API_TOKEN=fixture-private-only\n', 'app.py': 'print(1)'})
        self.assertFalse(result['passed'])
        self.assertTrue(any(item.get('error') == 'credential-file' for item in result['hits']))

    def test_retained_dotenv_samples_and_templates_still_receive_content_checks(self):
        for name in ('.env.production.sample', '.env.template'):
            with self.subTest(name=name):
                manifest = self.sources({name: 'LABEL=模拟数据\n'})
                with self.assertRaisesRegex(ValueError, 'semantic fix before packing'):
                    pack_source(self.f.work, self.f.out, manifest)

    def test_powershell_module_and_manifest_strings_are_scanned_when_packing(self):
        for name in ('app/Business.psm1', 'app/Business.psd1'):
            with self.subTest(name=name):
                manifest = self.sources({name: '$label="模拟数据"\n'})
                with self.assertRaisesRegex(ValueError, 'semantic fix before packing'):
                    pack_source(self.f.work, self.f.out, manifest)

    def test_powershell_module_and_rst_contents_are_scanned_in_final_archive(self):
        result = self.handmade_scan({'app/Business.psm1': '$label="模拟数据"\n',
                                     'app/Business.psd1': '@{ Label="参考值" }\n',
                                     'notes.rst': 'Synthetic data for evaluation.\n'})
        self.assertFalse(result['passed'])
        hit_paths = {item['path'].split('!', 1)[-1] for item in result['hits']}
        self.assertEqual(hit_paths, {'app/Business.psm1', 'app/Business.psd1', 'notes.rst'})

    def test_clean_powershell_algorithms_and_configuration_are_retained(self):
        files = {'app/Business.psm1': 'function Get-Current { param($voltage,$resistance) $voltage / $resistance }\n',
                 'app/Business.psd1': '@{ RootModule="Business.psm1"; ModuleVersion="1.0.0" }\n'}
        receipt = pack_source(self.f.work, self.f.out, self.sources(files))
        self.assertEqual(set(receipt['files']), set(files))
        self.assertTrue(scan_delivery(self.f.out, run=read_json(self.f.work / '.product-v2/run.json'))['passed'])

    def test_chinese_installation_deployment_guides_are_omitted_at_any_depth(self):
        guides = ['安装说明.txt', 'docs/部署说明.txt', 'docs/安装指南.md', '部署指南.md',
                  '安装手册.rst', 'docs/部署手册.html', 'docs/系统部署指南/notes.txt']
        runtime = {'app/import_parser.py': 'def parse(value): return value\n',
                   '安装.ps1': 'python -m pip install -r requirements.txt\n',
                   '启动.ps1': 'python app.py\n', '停止.ps1': '$processId = 100\n',
                   'requirements.txt': 'flask\n'}
        files = {name: '执行 python app.py。\n' for name in guides}
        files.update(runtime)
        receipt = pack_source(self.f.work, self.f.out, self.sources(files))
        self.assertEqual(set(receipt['files']), set(runtime))
        self.assertEqual({item['path'] for item in receipt['excluded']}, set(guides))

    def test_chinese_deployment_guide_in_handmade_archive_is_blocked(self):
        result = self.handmade_scan({'docs/部署说明.txt': '执行 python app.py。\n', 'app.py': 'print(1)'})
        self.assertFalse(result['passed'])
        self.assertTrue(any(item.get('error') == 'delivery-guide-or-production-document' for item in result['hits']))


class TextEncodingRuleTests(unittest.TestCase):
    BOM_ENCODINGS = ((b'\xef\xbb\xbf', 'utf-8'),
                     (b'\xff\xfe', 'utf-16-le'), (b'\xfe\xff', 'utf-16-be'),
                     (b'\xff\xfe\x00\x00', 'utf-32-le'), (b'\x00\x00\xfe\xff', 'utf-32-be'))

    def test_valid_bom_sources_pack_and_scan_without_changing_bytes(self):
        f = test_product_flow.FlowTests()
        f.setUp()
        try:
            files = {}
            for bom, encoding in self.BOM_ENCODINGS:
                name = 'app/business-' + encoding + '.psm1'
                payload = bom + '$label = "运行状态"\n'.encode(encoding)
                path = f.work / name
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(payload)
                files[name] = payload
            receipt = pack_source(f.work, f.out, f.manifest('bom-source-manifest', {'files': list(files)}))
            self.assertEqual(set(receipt['files']), set(files))
            run = read_json(f.work / '.product-v2/run.json')
            with zipfile.ZipFile(run['source_zip']) as archive:
                for name, payload in files.items():
                    self.assertEqual(archive.read(name), payload)
                    self.assertEqual((f.work / name).read_bytes(), payload)
            self.assertTrue(scan_delivery(f.out, run=run)['passed'])
        finally:
            f.tearDown()

    def test_restricted_bom_source_text_is_reported_at_its_actual_line(self):
        for bom, encoding in self.BOM_ENCODINGS:
            with self.subTest(encoding=encoding):
                hits = scan_text('app/Business.psm1', bom + '# 设备运行\n$label = "模拟数据"\n'.encode(encoding))
                self.assertTrue(hits)
                self.assertTrue(any(item.get('line') == 2 and '模拟' in item.get('words', []) for item in hits))
                self.assertTrue(all(item['path'] == 'app/Business.psm1' for item in hits))

    def test_bomless_utf16_or_utf32_with_raw_nuls_is_unreadable(self):
        for encoding in ('utf-16-le', 'utf-16-be', 'utf-32-le', 'utf-32-be'):
            with self.subTest(encoding=encoding):
                payload = '$label = "模拟数据"\n'.encode(encoding)
                self.assertIn(b'\x00', payload)
                self.assertEqual(scan_text('app/Business.psm1', payload),
                                 [{'path': 'app/Business.psm1', 'error': 'Text encoding is unreadable'}])

    def test_utf8_and_gb18030_paths_remain_compatible(self):
        for encoding in ('utf-8', 'gb18030'):
            with self.subTest(encoding=encoding):
                self.assertEqual(scan_text('app/Business.psm1', '$label = "运行状态"\n'.encode(encoding)), [])
                hits = scan_text('app/Business.psm1', '$label = "模拟数据"\n'.encode(encoding))
                self.assertTrue(any('模拟' in item.get('words', []) for item in hits))

    def test_invalid_bom_payload_and_embedded_nuls_are_not_fallback_success(self):
        for payload in (b'\xff\xfe\x00', b'\xfe\xff\x00', b'\xff\xfe\x00\x00A\x00',
                        b'\xef\xbb\xbf\xff', b'$label = "ok"\x00',
                        b'\xff\xfe' + '$label = "ok"\x00'.encode('utf-16-le')):
            with self.subTest(payload=payload):
                self.assertEqual(scan_text('app/Business.psm1', payload),
                                 [{'path': 'app/Business.psm1', 'error': 'Text encoding is unreadable'}])


class EffectiveBusinessKeyTests(unittest.TestCase):
    def setUp(self):
        self.f = test_data_preflight.DataPreflightTests()
        self.f.setUp()
        self.addCleanup(self.f.tearDown)

    def test_surrogate_key_cannot_make_copied_business_rows_look_expanded(self):
        f = self.f
        f.rows[1] = ['R2', *f.rows[0][1:]]
        f.path = f.write('记录.csv', list(f.columns), f.rows)
        f.schema['记录.csv']['effective_key'].insert(0, '记录编号')
        with self.assertRaisesRegex(ValueError, 'exclude surrogate primary keys'):
            f.audit(name_review=f.reviews())
        f.schema['记录.csv']['effective_key'].remove('记录编号')
        audit = f.audit(name_review=f.reviews())
        self.assertEqual(audit['data_status'], 'fail')
        self.assertEqual(audit['files']['记录.csv']['effective_rows'], 1)
        expanded = check_expansion({'files': {'记录.csv': {'effective_rows': 1}}}, audit,
                                  {'generation_method': 'isolated copied-row counterexample',
                                   'main_tables': {'记录.csv': {'target_effective_rows': 2}}})
        self.assertEqual(expanded['expansion_status'], 'fail')

    def test_actual_object_time_event_and_value_differences_still_count(self):
        f = self.f
        initial = copy.deepcopy(f.rows[0])
        f.rows = [initial]
        for field, value in ((1, 'O2'), (2, '2026-10-02T00:00:00'), (3, '异常'), (4, '4')):
            row = copy.deepcopy(initial)
            row[0] = 'R' + str(len(f.rows) + 1)
            row[field] = value
            f.rows.append(row)
        f.path = f.write('记录.csv', list(f.columns), f.rows)
        audit = f.audit(name_review=f.reviews())
        self.assertEqual(audit['data_status'], 'pass')
        self.assertEqual(audit['files']['记录.csv']['effective_rows'], 5)
        self.assertEqual(audit['files']['记录.csv']['independent_objects'], {'对象编号': 2})

    def test_natural_entity_time_key_remains_valid(self):
        f = self.f
        spec = f.schema['记录.csv']
        spec['primary_key_kind'] = 'natural'
        spec['primary_key'] = spec['effective_key'] = ['对象编号', '时间', '状态']
        audit = f.audit(name_review=f.reviews())
        self.assertEqual(audit['data_status'], 'pass')
        self.assertEqual(audit['files']['记录.csv']['effective_rows'], 2)

    def test_identifier_dimension_remains_valid_without_surrogate_growth(self):
        f = self.f
        f.path = f.write('记录.csv', ['对象编号'], [['O1'], ['O2']])
        f.schema = {'记录.csv': {'table_role': 'dimension', 'columns': {'对象编号': f.columns['对象编号']},
                               'primary_key': ['对象编号'], 'effective_key': ['对象编号']}}
        self.assertEqual(f.audit(name_review=f.reviews())['data_status'], 'pass')

    def test_natural_row_id_cannot_inflate_primary_or_effective_business_keys(self):
        f = self.f
        f.rows[1] = ['R2', *f.rows[0][1:]]
        f.path = f.write('记录.csv', list(f.columns), f.rows)
        before = f.path.read_bytes()
        original = copy.deepcopy(f.schema['记录.csv'])
        original.update(primary_key_kind='natural', primary_key=['对象编号', '时间'])
        for locations in (('primary_key',), ('effective_key',), ('primary_key', 'effective_key')):
            with self.subTest(locations=locations):
                spec = copy.deepcopy(original)
                for label in locations:
                    spec[label].insert(0, '记录编号')
                f.schema['记录.csv'] = spec
                with self.assertRaisesRegex(ValueError, 'ID fields must be declared entity object_columns'):
                    f.audit(name_review=f.reviews())
        f.schema['记录.csv'] = original
        audit = f.audit(name_review=f.reviews())
        self.assertEqual(audit['data_status'], 'fail')
        self.assertEqual(audit['files']['记录.csv']['effective_rows'], 1)
        expansion = check_expansion({'files': {'记录.csv': {'effective_rows': 1}}}, audit,
                                    {'generation_method': 'isolated natural-key row-ID counterexample',
                                     'main_tables': {'记录.csv': {'target_effective_rows': 2}}})
        self.assertEqual(expansion['expansion_status'], 'fail')
        self.assertEqual(f.path.read_bytes(), before)

    def test_nonprimary_sequence_id_cannot_inflate_surrogate_effective_key(self):
        f = self.f
        f.columns['流水编号'] = {'kind': 'id', 'pattern': r'S\d+'}
        f.rows[1] = ['R2', *f.rows[0][1:]]
        f.rows = [row + ['S' + str(index + 1)] for index, row in enumerate(f.rows)]
        f.path = f.write('记录.csv', list(f.columns), f.rows)
        f.schema['记录.csv']['effective_key'].append('流水编号')
        with self.assertRaisesRegex(ValueError, 'effective_key ID fields must be declared entity object_columns'):
            f.audit(name_review=f.reviews())

    def test_multiple_declared_entities_in_natural_time_key_remain_distinct(self):
        f = self.f
        f.columns['关联对象编号'] = {'kind': 'id', 'pattern': r'O\d+'}
        f.rows[1] = ['R2', *f.rows[0][1:]]
        f.rows = [row + ['O' + str(index + 2)] for index, row in enumerate(f.rows)]
        f.path = f.write('记录.csv', list(f.columns), f.rows)
        spec = f.schema['记录.csv']
        spec['primary_key_kind'] = 'natural'
        spec['object_columns'] = ['对象编号', '关联对象编号']
        spec['primary_key'] = spec['effective_key'] = ['对象编号', '关联对象编号', '时间', '状态']
        audit = f.audit(name_review=f.reviews())
        self.assertEqual(audit['data_status'], 'pass')
        self.assertEqual(audit['files']['记录.csv']['effective_rows'], 2)
        self.assertEqual(audit['files']['记录.csv']['independent_objects'], {'对象编号': 1, '关联对象编号': 2})

    def test_two_typed_natural_business_fields_remain_valid_without_entity_ids(self):
        f = self.f
        spec = f.schema['记录.csv']
        spec['primary_key_kind'] = 'natural'
        for fields in (['时间', '值'], ['状态', '值']):
            with self.subTest(fields=fields):
                spec['primary_key'] = spec['effective_key'] = fields
                audit = f.audit(name_review=f.reviews())
                self.assertEqual(audit['data_status'], 'pass')
                self.assertEqual(audit['files']['记录.csv']['effective_rows'], 2)


class SimplifiedVideoChangeTests(unittest.TestCase):
    def setUp(self):
        self.f = test_simplified_closure.SimplifiedClosureTests()
        self.f.setUp()
        self.addCleanup(self.f.doCleanups)

    def test_known_major_operation_change_blocks_unchanged_video(self):
        f = self.f
        path = f.f.work / '.product-v2/build-checks.json'
        write_json(path, {'video_material_change': 'The primary navigation and submission workflow was replaced.'})
        with self.assertRaisesRegex(ValueError, 'major system/operation change'):
            f.close()
        self.assertTrue(f.f.out.is_dir())
        self.assertFalse(f.destination.exists())

    def test_qualified_unchanged_video_reuses_without_full_frame_validation(self):
        with patch('media_evidence.validate', side_effect=AssertionError('Unchanged qualified frames must stay reused')):
            self.assertEqual(self.f.close()['status'], 'delivered')


class PrepareFrozenPolicyTests(unittest.TestCase):
    def test_new_case_freezes_source_parts_and_review_coverage_policies(self):
        f = test_product_flow.FlowTests()
        f.setUp()
        try:
            run = read_json(f.work / '.product-v2/run.json')
            self.assertEqual(run['source_integrity_policy'], 'source-parts-v1')
            self.assertEqual(run['review_coverage_policy'], 'required-evidence-v1')
        finally:
            f.tearDown()

    def test_document_revision_upgrades_and_package_revision_preserves_base_policy(self):
        f = test_contracts.ContractTests()
        f.setUp()
        try:
            base, _, _ = f.revision_fixture()
            path = base / '.product-v2/run.json'
            old = read_json(path)
            versions = {'source_integrity_policy': 'source-parts-v1',
                        'review_coverage_policy': 'required-evidence-v1'}
            for index, policy in enumerate(('missing', None, 'source-parts-v1')):
                previous = dict(old)
                for key, version in versions.items():
                    if policy == 'missing':
                        previous.pop(key, None)
                    else:
                        previous[key] = None if policy is None else version
                write_json(path, previous)
                for scope in ('document', 'package'):
                    work = f.root / f'parts-{index}-{scope}'
                    work.mkdir()
                    result = prepare(work, f.root / f'parts-output-{index}-{scope}', '设备运行控制',
                                     f.source, base, revision_scope=scope)
                    for key, version in versions.items():
                        expected = version if scope == 'document' else previous.get(key)
                        self.assertEqual(result.get(key), expected)
                        if scope == 'package':
                            self.assertEqual(key in result, policy != 'missing')
                    before = digest(work / '.product-v2/run.json')
                    prepare(work, f.root / f'parts-output-{index}-{scope}', '设备运行控制',
                            f.source, base, revision_scope=scope)
                    self.assertEqual(digest(work / '.product-v2/run.json'), before)
        finally:
            f.tearDown()


if __name__ == '__main__':
    unittest.main()
