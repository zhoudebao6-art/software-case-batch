import csv
import copy
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
from common import digest,write_json,read_json
from proflow import check_data_quality,workflow_status
import data_preflight


class DataWorkflowTests(unittest.TestCase):
    def test_current_export_and_review_are_bound_before_acceptance(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);work=root/'work';out=root/'out';metadata=work/'.product-v2';metadata.mkdir(parents=True)
            data=out/'模拟系统/数据';data.mkdir(parents=True);path=data/'记录.csv'
            path.write_text('对象编号,时间,数值\nOBJ_001,2026-01-01T00:00:00,1\nOBJ_001,2026-01-02T00:00:00,2\n',encoding='utf-8-sig')
            write_json(metadata/'run.json',{'output':str(out),'data_policy_version':'neutral-expanded-v1'})
            write_json(metadata/'data-cleaning.json',{'files':[{'name':path.name,'sha256':digest(path)}]})
            plan={'export_schema':{path.name:{'columns':{'对象编号':{'kind':'id','pattern':r'OBJ_\d{3}'},'时间':{'kind':'timestamp'},'数值':{'kind':'number'}},'primary_key':['对象编号','时间'],'effective_key':['对象编号','时间','数值'],'time_column':'时间','object_columns':['对象编号']}},
                  'name_review':{path.name:{'sha256':digest(path),'filename_checked':True,'columns_checked':True,'text_checked':True,'evidence':'真实逐项检查编号及固定业务字段，无专名'}},
                  'expansion_plan':{'main_tables':{path.name:{'target_effective_rows':2}},'generation_method':'按对象时序的确定性业务计算'}}
            write_json(metadata/'data-plan.json',plan)
            with self.assertRaisesRegex(ValueError,'check-data'):check_data_quality(work,out)
            result=check_data_quality(work,out,update=True)
            self.assertEqual(result,check_data_quality(work,out))
            path.write_text(path.read_text(encoding='utf-8-sig').replace('OBJ_001','城市名称'),encoding='utf-8-sig')
            with self.assertRaises(ValueError):check_data_quality(work,out)


class DataReuseTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name)
        self.work=self.root/'work';self.out=self.root/'out';self.metadata=self.work/'.product-v2';self.metadata.mkdir(parents=True)
        self.data=self.out/'模拟系统/数据';self.data.mkdir(parents=True);self.path=self.data/'记录.csv'
        self.path.write_text('对象编号,时间,数值\nOBJ_001,2026-01-01T00:00:00,1\nOBJ_001,2026-01-02T00:00:00,2\n',encoding='utf-8-sig')
        write_json(self.metadata/'run.json',{'data_policy_version':'neutral-expanded-v1','run_id':'data-fixture','workspace':str(self.work),'output':str(self.out)})
        write_json(self.metadata/'data-cleaning.json',{'status':'cleaned','files':[{'name':self.path.name,'sha256':digest(self.path)}]})
        self.plan={'export_schema':{self.path.name:{'columns':{'对象编号':{'kind':'id','pattern':r'OBJ_\d{3}'},'时间':{'kind':'timestamp'},'数值':{'kind':'number'}},
            'primary_key':['对象编号','时间'],'effective_key':['对象编号','时间','数值'],'time_column':'时间','object_columns':['对象编号']}},
            'name_review':{self.path.name:{'sha256':digest(self.path),'filename_checked':True,'columns_checked':True,'text_checked':True,'evidence':'实际专名检查夹具'}},
            'expansion_plan':{'main_tables':{self.path.name:{'target_effective_rows':2}},'generation_method':'确定性业务计算'}}
        self.plan_path=self.metadata/'data-plan.json';write_json(self.plan_path,self.plan)
    def tearDown(self):self.temp.cleanup()
    def check(self,update=False):return check_data_quality(self.work,self.out,update)
    def status(self):
        return workflow_status(self.work,self.out,read_json(self.metadata/'run.json'))['steps']['data']
    def test_completed_data_reuses_without_audit_or_receipt_rewrite(self):
        with patch('data_preflight.audit_csv_exports',wraps=data_preflight.audit_csv_exports) as calls:
            original=self.check(True);before=digest(self.metadata/'data-cleaning.json')
            self.assertEqual(original,self.check());self.assertEqual(original,self.check(True))
            self.assertEqual(calls.call_count,1);self.assertEqual(digest(self.metadata/'data-cleaning.json'),before)
        self.assertTrue(self.status()['data_completed'])
    def test_completed_data_ignores_later_code_plan_tool_and_runtime_changes(self):
        original=self.check(True);before=digest(self.metadata/'data-cleaning.json')
        (self.work/'app.py').write_text('later algorithm and parameters',encoding='utf8')
        self.plan_path.write_text('{changed, now invalid plan}',encoding='utf8')
        with patch('data_preflight.audit_csv_exports',side_effect=AssertionError('Completed data must not audit')),                patch.object(data_preflight,'__file__','missing changed checker.py'),patch('proflow.sys.version','changed interpreter fixture'):
            self.assertEqual(self.check(),original);self.assertEqual(self.status()['state'],'completed')
        self.assertEqual(digest(self.metadata/'data-cleaning.json'),before)
    def test_completed_data_ignores_later_raw_input_change_or_missing_input(self):
        raw=self.work/'original.csv';raw.write_text('original raw source',encoding='utf8')
        receipt=read_json(self.metadata/'data-cleaning.json');receipt['files'][0].update(input=str(raw),input_sha256=digest(raw))
        write_json(self.metadata/'data-cleaning.json',receipt);self.check(True)
        raw.write_text('later raw input',encoding='utf8');self.assertEqual(self.status()['state'],'completed')
        raw.unlink();self.assertEqual(self.status()['state'],'completed');self.assertIsNotNone(self.check())
    def test_csv_own_bytes_change_even_with_same_size_and_mtime_is_not_reused(self):
        self.check(True);stamp=self.path.stat();self.path.write_bytes(self.path.read_bytes().replace(b',1',b',x',1))
        os.utime(self.path,ns=(stamp.st_atime_ns,stamp.st_mtime_ns));self.assertEqual(self.path.stat().st_size,stamp.st_size)
        with patch('data_preflight.audit_csv_exports',wraps=data_preflight.audit_csv_exports) as calls:
            with self.assertRaises(ValueError):self.check()
            self.assertEqual(calls.call_count,1)
        self.assertEqual(self.status()['state'],'stale')
    def test_missing_or_first_quality_requires_complete_actual_audit(self):
        self.assertEqual(self.status()['state'],'cleaned');self.assertEqual(self.status()['next_action'],'check-data')
        with patch('data_preflight.audit_csv_exports',wraps=data_preflight.audit_csv_exports) as calls:
            with self.assertRaisesRegex(ValueError,'Run check-data'):self.check()
            self.assertEqual(calls.call_count,1)
        self.check(True);self.assertEqual(self.status()['state'],'completed')
    def test_invalid_or_failed_original_quality_is_not_reused(self):
        self.check(True);original=read_json(self.metadata/'data-cleaning.json')
        mutations=[lambda x:x.pop('quality'),lambda x:x.update(quality=[]),lambda x:x['quality'].update(audit=[]),
            lambda x:x['quality']['audit'].update(data_status='fail'),lambda x:x['quality']['expansion'].update(expansion_status='fail'),
            lambda x:x['quality']['audit']['files'][self.path.name].update(sha256='0'*64)]
        for mutation in mutations:
            with self.subTest(mutation=mutation):
                changed=copy.deepcopy(original);mutation(changed);write_json(self.metadata/'data-cleaning.json',changed)
                with patch('data_preflight.audit_csv_exports',wraps=data_preflight.audit_csv_exports) as calls:
                    self.check(True);self.assertEqual(calls.call_count,1)
    def test_old_real_pass_shape_reuses_without_upgrade_or_new_plan(self):
        quality=self.check(True);self.assertEqual(set(quality),{'policy','plan_sha256','audit','expansion'})
        before=digest(self.metadata/'data-cleaning.json');self.plan_path.unlink()
        with patch('data_preflight.audit_csv_exports',side_effect=AssertionError('Old completed pass is reusable')):
            self.assertEqual(self.check(),quality)
        self.assertEqual(digest(self.metadata/'data-cleaning.json'),before)
    def test_known_specific_data_error_requires_targeted_work(self):
        self.check(True);write_json(self.metadata/'build-checks.json',{'data_material_error':'Known wrong object mapping in exported records'})
        with self.assertRaisesRegex(ValueError,'Known material data error'):self.check()
        self.assertEqual(self.status()['state'],'unknown')
        run=read_json(self.metadata/'run.json');run.pop('data_policy_version');write_json(self.metadata/'run.json',run)
        with self.assertRaisesRegex(ValueError,'Known material data error'):self.check()
        self.assertEqual(self.status()['state'],'unknown')
    def test_first_audit_keeps_names_and_sufficient_scale_checks(self):
        self.plan['expansion_plan']['main_tables'][self.path.name]['target_effective_rows']=100;write_json(self.plan_path,self.plan)
        with self.assertRaisesRegex(ValueError,'Construction data checks incomplete'):self.check(True)
        self.plan['expansion_plan']['main_tables'][self.path.name]['target_effective_rows']=2
        self.plan['known_names']=['OBJ_001'];write_json(self.plan_path,self.plan)
        with self.assertRaisesRegex(ValueError,'Construction data checks incomplete'):self.check(True)
    def test_finalized_update_stays_frozen_and_members_cannot_change(self):
        self.check(True);write_json(self.metadata/'final-receipt.json',{'status':'complete'})
        with self.assertRaisesRegex(ValueError,'Finalized evidence is frozen'):self.check(True)
        extra=self.data/'new.csv';extra.write_bytes(self.path.read_bytes())
        with self.assertRaises(ValueError):self.check()
        extra.unlink();self.path.unlink()
        with self.assertRaises(ValueError):self.check()


if __name__=='__main__':unittest.main()
