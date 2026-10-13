import copy
import csv
import hashlib
import os
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from data_preflight import audit_csv_exports, check_expansion, stable_entity_id


class DataPreflightTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(dir=os.environ['TEMP'])
        self.root = Path(self.temp.name)
        self.columns = {'记录编号': {'kind': 'id', 'pattern': r'R\d+'},
                        '对象编号': {'kind': 'id', 'pattern': r'O\d+'},
                        '时间': {'kind': 'timestamp'}, '状态': {'kind': 'enum', 'values': ['正常', '异常', '恢复']},
                        '值': {'kind': 'number'}, '备注': {'kind': 'text'}}
        self.schema = {'记录.csv': {'columns': self.columns, 'primary_key': ['记录编号'],
                                  'effective_key': ['对象编号', '时间', '状态', '值'],
                                  'object_columns': ['对象编号'], 'time_column': '时间', 'event_column': '状态'}}
        self.rows = [['R1', 'O1', '2026-10-01T00:00:00', '正常', '3', '已处理'],
                     ['R2', 'O1', '2026-10-02T00:00:00', '恢复', '4', '待核对']]
        self.path = self.write('记录.csv', list(self.columns), self.rows)

    def tearDown(self):
        self.temp.cleanup()

    def write(self, name, columns, rows):
        path = self.root/name
        with path.open('w', encoding='utf-8-sig', newline='') as stream:
            writer = csv.writer(stream)
            writer.writerow(columns)
            writer.writerows(rows)
        return path

    def reviews(self, paths=None):
        return {path.name: {'sha256': hashlib.sha256(path.read_bytes()).hexdigest(),
                            'filename_checked': True, 'columns_checked': True,
                            'text_checked': True, 'evidence': '建设者实际检查当前CSV文件名、列名与所有自由文本'}
                for path in paths or [self.path]}

    def audit(self, **kwargs):
        return audit_csv_exports([self.path], self.schema, **kwargs)

    def test_actual_scale_and_hash_bound_review(self):
        result = self.audit()
        self.assertEqual(result['data_status'], 'review_required')
        self.assertEqual(result['name_review_required'], ['记录.csv'])
        result = self.audit(name_review=self.reviews())
        self.assertEqual(result['data_status'], 'pass')
        metrics = result['files']['记录.csv']
        self.assertEqual(metrics['effective_rows'], 2)
        self.assertEqual(metrics['independent_objects'], {'对象编号': 1})
        self.assertEqual(metrics['time_end'], '2026-10-02T00:00:00')
        self.assertEqual(metrics['events'], {'正常': 1, '恢复': 1})
        self.assertFalse(result['general_name_recognition'])

    def test_known_names_in_nested_text_are_reported_without_editing(self):
        self.rows[0][-1] = '{"说明":"\\u5f20\\u4e09在星河公司处理杭州记录"}'
        self.path = self.write('记录.csv', list(self.columns), self.rows)
        before = self.path.read_bytes()
        result = self.audit(known_names=['张三', '星河公司', '杭州'], name_review=self.reviews())
        self.assertEqual(result['data_status'], 'fail')
        self.assertEqual({hit['matched'] for hit in result['findings'] if hit['kind'] == 'known-name'},
                         {'张三', '星河公司', '杭州'})
        self.assertEqual(self.path.read_bytes(), before)

    def test_filename_header_and_prohibited_name_schema_checked(self):
        path = self.write('杭州记录.csv', ['记录编号', '公司名称'], [['R1', '星河公司']])
        schema = {path.name: {'columns': {'记录编号': {'kind': 'id', 'pattern': 'R[0-9]+'},
                                        '公司名称': {'kind': 'company_name'}},
                             'primary_key': ['记录编号'], 'effective_key': ['公司名称']}}
        result = audit_csv_exports([path], schema, known_names=['杭州', '星河公司'], name_review=self.reviews([path]))
        self.assertEqual(result['data_status'], 'fail')
        self.assertTrue(any(hit.get('location') == 'filename' for hit in result['findings']))
        self.assertTrue(any(hit['kind'] == 'name-column' for hit in result['findings']))

    def test_generic_business_terms_and_units_survive(self):
        self.rows[0][-1] = '操作员；公司类型；地区编号；kWh'
        self.path = self.write('记录.csv', list(self.columns), self.rows)
        before = self.path.read_bytes()
        result = self.audit(name_review=self.reviews())
        self.assertEqual(result['data_status'], 'pass')
        self.assertEqual(self.path.read_bytes(), before)

    def test_only_changing_surrogate_ids_does_not_expand_effective_scale(self):
        self.rows.append(['R3', *self.rows[0][1:]])
        self.path = self.write('记录.csv', list(self.columns), self.rows)
        result = self.audit(name_review=self.reviews())
        self.assertEqual(result['files']['记录.csv']['rows'], 3)
        self.assertEqual(result['files']['记录.csv']['effective_rows'], 2)
        self.assertEqual(result['data_status'], 'fail')
        self.assertIn('duplicate-business-content', {hit['kind'] for hit in result['findings']})

    def test_natural_entity_time_event_composite_can_be_effective_key(self):
        spec = self.schema['记录.csv']
        spec['primary_key_kind'] = 'natural'
        spec['primary_key'] = spec['effective_key'] = ['对象编号', '时间', '状态']
        result = self.audit(name_review=self.reviews())
        self.assertEqual(result['data_status'], 'pass')
        self.assertEqual(result['files']['记录.csv']['effective_rows'], 2)
        self.rows.append(['R3', *self.rows[0][1:]])
        self.path = self.write('记录.csv', list(self.columns), self.rows)
        result = self.audit(name_review=self.reviews())
        self.assertEqual(result['data_status'], 'fail')
        kinds = {hit['kind'] for hit in result['findings']}
        self.assertIn('invalid-primary-key', kinds)
        self.assertIn('duplicate-business-content', kinds)

    def test_pure_row_id_detail_rejected_even_if_declared_natural(self):
        spec = self.schema['记录.csv']
        spec['primary_key'] = spec['effective_key'] = ['记录编号']
        for kind in ('surrogate', 'natural'):
            with self.subTest(primary_key_kind=kind):
                spec['primary_key_kind'] = kind
                with self.assertRaises(ValueError):
                    self.audit(name_review=self.reviews())
        # Two ID columns alone do not provide business-time/event content either.
        spec['primary_key'] = spec['effective_key'] = ['记录编号', '对象编号']
        with self.assertRaises(ValueError):
            self.audit(name_review=self.reviews())

    def test_natural_key_needs_real_typed_semantics_not_free_text(self):
        spec = self.schema['记录.csv']
        spec['primary_key_kind'] = 'natural'
        spec['primary_key'] = spec['effective_key'] = ['记录编号', '备注']
        with self.assertRaises(ValueError):
            self.audit(name_review=self.reviews())
        spec['primary_key'] = spec['effective_key'] = ['时间', '值']
        self.assertEqual(self.audit(name_review=self.reviews())['data_status'], 'pass')

    def test_natural_composite_primary_cannot_use_only_row_id_as_effective_key(self):
        spec = self.schema['记录.csv']
        spec['primary_key_kind'] = 'natural'
        spec['primary_key'] = ['对象编号', '时间', '状态']
        spec['effective_key'] = ['记录编号']
        with self.assertRaises(ValueError):
            self.audit(name_review=self.reviews())

    def test_entity_plus_one_business_field_needs_matching_semantic_declaration(self):
        original = copy.deepcopy(self.schema['记录.csv'])
        for field, declaration in (('时间', 'time_column'), ('状态', 'event_column')):
            with self.subTest(field=field):
                spec = copy.deepcopy(original)
                spec['primary_key_kind'] = 'natural'
                spec['primary_key'] = spec['effective_key'] = ['对象编号', field]
                self.schema['记录.csv'] = spec
                self.assertEqual(self.audit(name_review=self.reviews())['data_status'], 'pass')
                del spec[declaration]
                with self.assertRaises(ValueError):
                    self.audit(name_review=self.reviews())

    def test_declared_time_column_cannot_be_mislabeled_to_escape_natural_key_checks(self):
        spec = self.schema['记录.csv']
        spec['primary_key_kind'] = 'natural'
        spec['primary_key'] = spec['effective_key'] = ['对象编号', '时间', '状态']
        spec['columns']['时间'] = {'kind': 'enum', 'values': [row[2] for row in self.rows]}
        with self.assertRaises(ValueError):
            self.audit(name_review=self.reviews())

    def test_stable_id_consistent_across_tables_and_keys(self):
        self.assertEqual(stable_entity_id('OBJ', '原对象A'), stable_entity_id('OBJ', '原对象A'))
        self.assertNotEqual(stable_entity_id('OBJ', '原对象A'), stable_entity_id('OBJ', '原对象B'))
        self.assertNotEqual(stable_entity_id('OBJ', '原对象A'), stable_entity_id('OP', '原对象A'))
        self.assertNotIn('原对象', stable_entity_id('OBJ', '原对象A'))
        with self.assertRaises(ValueError):
            stable_entity_id('真实公司', '原对象A')

    def test_identifier_only_dimension_is_valid_without_growth_requirement(self):
        path = self.write('对象.csv', ['对象编号'], [['O1'], ['O2']])
        schema = {'对象.csv': {'table_role': 'dimension',
                               'columns': {'对象编号': {'kind': 'id', 'pattern': r'O\d+'}},
                               'primary_key': ['对象编号'], 'effective_key': ['对象编号']}}
        result = audit_csv_exports([path], schema, name_review=self.reviews([path]))
        self.assertEqual(result['data_status'], 'pass')

    def test_same_csv_repeated_under_another_filename_is_not_more_data(self):
        duplicate = self.root/'重复.csv'
        duplicate.write_bytes(self.path.read_bytes())
        schema = {**self.schema, '重复.csv': copy.deepcopy(self.schema['记录.csv'])}
        paths = [self.path, duplicate]
        result = audit_csv_exports(paths, schema, name_review=self.reviews(paths))
        self.assertEqual(result['data_status'], 'fail')
        self.assertIn('duplicate-export', {hit['kind'] for hit in result['findings']})

    def test_foreign_key_and_actual_csv_set(self):
        parent = self.write('对象.csv', ['对象编号', '类别'], [['O1', '设备']])
        schema = copy.deepcopy(self.schema)
        schema['记录.csv']['foreign_keys'] = [{'columns': ['对象编号'], 'target_file': '对象.csv',
                                             'target_columns': ['对象编号']}]
        schema['对象.csv'] = {'columns': {'对象编号': {'kind': 'id', 'pattern': r'O\d+'},
                                         '类别': {'kind': 'enum', 'values': ['设备']}},
                             'primary_key': ['对象编号'], 'effective_key': ['对象编号', '类别']}
        paths = [self.path, parent]
        self.assertEqual(audit_csv_exports(paths, schema, name_review=self.reviews(paths))['data_status'], 'pass')
        self.rows[0][1] = 'O2'
        self.write('记录.csv', list(self.columns), self.rows)
        result = audit_csv_exports(paths, schema, name_review=self.reviews(paths))
        self.assertEqual(result['data_status'], 'fail')
        self.assertIn('missing-foreign-key', {hit['kind'] for hit in result['findings']})
        with self.assertRaises(ValueError):
            audit_csv_exports([self.path], schema)

    def test_stale_review_cannot_approve_current_csv(self):
        reviews = self.reviews()
        self.rows[0][-1] = '需要复核'
        self.write('记录.csv', list(self.columns), self.rows)
        self.assertEqual(self.audit(name_review=reviews)['data_status'], 'review_required')

    def test_contextual_x2_only_for_selected_main_tables(self):
        current = self.audit(name_review=self.reviews())
        baseline = {'files': {'记录.csv': {'effective_rows': 1}}}
        plan = {'main_tables': {'记录.csv': {}}, 'generation_method': '固定种子按业务事件脚本扩展时间与恢复工况'}
        result = check_expansion(baseline, current, plan)
        self.assertEqual(result['expansion_status'], 'pass')
        self.assertEqual(result['tables']['记录.csv']['planning_starting_target'], 2)
        self.assertFalse(result['domain_validity_automatically_verified'])
        baseline['files']['记录.csv']['effective_rows'] = 2
        self.assertEqual(check_expansion(baseline, current, plan)['expansion_status'], 'fail')
        plan['main_tables']['记录.csv'] = {'target_effective_rows': 2}
        with self.assertRaises(ValueError):
            check_expansion(baseline, current, plan)
        plan['main_tables']['记录.csv']['adjustment_reason'] = '当前业务对象仅一台，扩大时间窗口；维表无需翻倍'
        self.assertEqual(check_expansion(baseline, current, plan)['expansion_status'], 'pass')

    def test_new_case_explicit_target_and_real_event_coverage(self):
        current = self.audit(name_review=self.reviews())
        plan = {'main_tables': {'记录.csv': {'target_effective_rows': 2, 'required_events': ['异常']}},
                'generation_method': '确定性领域脚本'}
        result = check_expansion(None, current, plan)
        self.assertEqual(result['expansion_status'], 'fail')
        self.assertIsNone(result['tables']['记录.csv']['baseline_effective_rows'])
        del plan['main_tables']['记录.csv']['target_effective_rows']
        with self.assertRaises(ValueError):
            check_expansion(None, current, plan)

    def test_invalid_numeric_and_findings_limit_cannot_hide_failure(self):
        self.rows[0][4] = 'NaN'
        self.rows[1][4] = 'bad'
        self.write('记录.csv', list(self.columns), self.rows)
        result = self.audit(name_review=self.reviews(), max_findings=1)
        self.assertEqual(result['data_status'], 'fail')
        self.assertGreater(result['truncated_findings'], 0)


if __name__ == '__main__':
    unittest.main()
