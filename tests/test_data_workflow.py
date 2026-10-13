import csv
from pathlib import Path
import sys
import tempfile
import unittest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
from common import digest,write_json,read_json
from proflow import check_data_quality


class DataWorkflowTests(unittest.TestCase):
    def test_current_export_and_review_are_bound_before_acceptance(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);work=root/'work';out=root/'out';metadata=work/'.product-v2';metadata.mkdir(parents=True)
            data=out/'模拟系统/数据';data.mkdir(parents=True);path=data/'记录.csv'
            path.write_text('对象编号,时间,数值\nOBJ_001,2026-01-01T00:00:00,1\nOBJ_001,2026-01-02T00:00:00,2\n',encoding='utf-8-sig')
            write_json(metadata/'run.json',{'data_policy_version':'neutral-expanded-v1'})
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


if __name__=='__main__':unittest.main()
