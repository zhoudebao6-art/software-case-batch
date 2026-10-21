"""Behavioral fixtures only: no real case, domain approval or screen readability claim."""
import copy
import csv
import json
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'scripts'))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import delivery_paths, digest, file_map, read_json, write_json
from data_preflight import audit_csv_exports, validate_delivery_datasets
from media_evidence import validate_recording_duration, validate_recording_quality
import proflow
from test_delivery_layout import DeliveryFixture
from test_media_evidence import flow_proof
import test_web_contract as web_fixtures


class RichWebTests(unittest.TestCase):
    setUp = web_fixtures.WebContractTests.setUp
    tearDown = web_fixtures.WebContractTests.tearDown
    file = web_fixtures.WebContractTests.file
    image = web_fixtures.WebContractTests.image
    assertion = web_fixtures.WebContractTests.assertion
    save = web_fixtures.WebContractTests.save
    validate = web_fixtures.WebContractTests.validate
    def rich(self, count=6):
        from PIL import Image
        self.run['delivery_requirements_version'] = 'rich-delivery-v1'
        Image.new('RGB', (1920,1080), 'gray').save(self.work/'screen.png')
        self.web['delivery_screenshot'] = {'path':'screen.png','page_id':'workbench',
            'native_width':1920,'native_height':1080,'resized':False}
        self.web['modules'] = []
        self.report['assertions'] = []
        self.web['workflows'][0]['assertion_ids'] = []
        self.web['workflows'][0]['actions'] = []
        for index in range(count):
            action, assertion = f'operation-{index}', f'assertion-{index}'
            self.web['workflows'][0]['assertion_ids'].append(assertion)
            self.web['workflows'][0]['actions'].append(action)
            self.report['assertions'].append({'id':assertion,'workflow_id':'task',
                'page_ids':['workbench'],**self.assertion(action)})
            self.web['modules'].append({'id':f'module-{index}', 'purpose':f'TEST business purpose {index}',
                'ui_locator':f'#section-{index}','page_ids':['workbench'],
                'workflow_ids':['task'],'assertion_ids':[assertion]})
        self.save()

    def test_six_modules_and_more_are_real_action_bound_sections_on_one_page(self):
        for count in (6, 15):
            self.rich(count)
            self.assertEqual(len(self.validate()['module_ids']), count)

    def test_five_modules_reused_actions_and_duplicate_purposes_reject(self):
        self.rich(5)
        with self.assertRaisesRegex(ValueError,'at least 6'): self.validate()
        for mutation in ('action','purpose','location'):
            self.rich()
            if mutation=='action':self.web['modules'][1]['assertion_ids']=['assertion-0']
            if mutation=='purpose':self.web['modules'][1]['purpose']=self.web['modules'][0]['purpose']
            if mutation=='location':self.web['modules'][1]['ui_locator']=self.web['modules'][0]['ui_locator']
            with self.subTest(mutation=mutation), self.assertRaises(ValueError):self.validate()

    def test_one_png_exports_exact_bytes_and_existing_gate_rejects_changed_delivery(self):
        self.rich()
        output=self.work.parent/(self.work.name+'-output')
        # Output lives in the fixture temporary directory but disjoint from work.
        # No production run is registered or published by this test.
        self.run.update(output=str(output),workspace=str(self.work),title='测试业务',
                        delivery_layout_version='research-materials-v3')
        write_json(self.work/'.product-v2/run.json', self.run)
        write_json(self.work/'.product-v2/build-checks.json', self.spec)
        try:
            paths=delivery_paths(self.run)
            result=proflow.export_screenshot(self.work,output,self.run)
            self.assertEqual(digest(paths['screenshot']),digest(self.work/'screen.png'))
            self.assertEqual((result['width'],result['height']),(1920,1080))
            self.assertEqual(list(paths['system'].iterdir()),[paths['screenshot']])
            before=paths['screenshot'].read_bytes()
            paths['screenshot'].write_bytes(b'changed')
            with self.assertRaisesRegex(ValueError,'differs'):self.validate()
            proflow.export_screenshot(self.work,output,self.run)
            self.assertEqual(paths['screenshot'].read_bytes(),before)
            write_json(self.work/'.product-v2/simplified-final-receipt.json',{'fixture_only':True})
            with self.assertRaisesRegex(ValueError,'frozen'):proflow.export_screenshot(self.work,output,self.run)
            self.assertEqual(paths['screenshot'].read_bytes(),before)
        finally:
            import shutil
            if output.exists():shutil.rmtree(output)

    def test_small_lossy_resized_and_false_native_dimensions_reject(self):
        from PIL import Image
        for mutation in ('small','jpeg','resized','dimensions'):
            self.rich()
            if mutation=='small':Image.new('RGB',(800,600)).save(self.work/'screen.png')
            if mutation=='jpeg':Image.new('RGB',(1920,1080)).save(self.work/'screen.png',format='JPEG')
            if mutation=='resized':self.web['delivery_screenshot']['resized']=True
            if mutation=='dimensions':self.web['delivery_screenshot']['native_width']=800
            self.save()
            with self.subTest(mutation=mutation), self.assertRaises(ValueError):self.validate()


class RichDataTests(DeliveryFixture):
    def datasets(self, count, copied=False):
        work=self.workspace('csv-'+str(count)+'-'+str(copied))
        paths=[];schema={};reviews={}
        for index in range(count):
            name=f'记录{index}.csv';path=work/name
            with path.open('w',encoding='utf-8-sig',newline='') as stream:
                csv.writer(stream).writerows([['编号','值'],[f'R{index}',str(1 if copied else index+1)]])
            paths.append(path)
            schema[name]={'dataset_id':f'dataset-{index}','purpose':f'业务目标{index}',
                'columns':{'编号':{'kind':'id','pattern':'R[0-9]+'},'值':{'kind':'number'}},
                'primary_key':['编号'],'effective_key':['值']}
            reviews[name]={'sha256':digest(path),'filename_checked':True,'columns_checked':True,
                'text_checked':True,'evidence':'TEST ONLY inspected fixture CSV text'}
        return work,paths,schema,reviews

    def test_ten_and_more_audited_csvs_count_but_renamed_business_copies_do_not(self):
        for count in (10,17):
            _,paths,schema,reviews=self.datasets(count)
            audit=audit_csv_exports(paths,schema,name_review=reviews)
            self.assertEqual(audit['data_status'],'pass')
            self.assertEqual(validate_delivery_datasets(audit)['dataset_count'],count)
        _,paths,schema,reviews=self.datasets(10,True)
        with self.assertRaisesRegex(ValueError,'copied'):
            validate_delivery_datasets(audit_csv_exports(paths,schema,name_review=reviews))

    def test_public_clean_and_check_data_require_ten_and_preserve_qualified_exports(self):
        for count in (9,10):
            work,paths,schema,_=self.datasets(count)
            output=self.root/f'exports-{count}'
            run=proflow.prepare(work,output,'对象运行业务',self.source)
            manifest={'files':[{'path':p.name,'name':p.name,'reason':schema[p.name]['purpose'],
                'primary_key':['编号']} for p in paths]}
            write_json(work/'selection.json',manifest)
            proflow.clean_csv(work,output,work/'selection.json')
            exported=delivery_paths(run)['data_dir']
            reviews={p.name:{'sha256':digest(exported/p.name),'filename_checked':True,'columns_checked':True,
                'text_checked':True,'evidence':'TEST ONLY inspected current exported CSV'} for p in paths}
            plan={'export_schema':schema,'name_review':reviews,'expansion_plan':{
                'generation_method':'TEST ONLY deterministic domain fixture',
                'main_tables':{p.name:{'target_effective_rows':1} for p in paths}}}
            write_json(work/'.product-v2/data-plan.json',plan)
            if count==9:
                with self.assertRaisesRegex(ValueError,'at least 10'):proflow.check_data_quality(work,output,update=True)
            else:
                proflow.check_data_quality(work,output,update=True)
                frozen=file_map(exported)
                # Completed qualified data remains reusable even if the old plan changes.
                write_json(work/'.product-v2/data-plan.json',{'later':'unrelated change'})
                proflow.check_data_quality(work,output)
                self.assertEqual(file_map(exported),frozen)


class BoundedRecordingTests(unittest.TestCase):
    def test_rich_construction_cannot_early_return_as_historical(self):
        from contracts import construction_checks
        for policy in (None, 'unknown-policy'):
            run={'delivery_requirements_version':'rich-delivery-v1'}
            if policy is not None:run['construction_check_policy_version']=policy
            with self.subTest(policy=policy),self.assertRaisesRegex(ValueError,'frozen construction'):
                construction_checks(Path.cwd(),run)
        with self.assertRaisesRegex(ValueError,'Unknown frozen delivery requirements'):
            construction_checks(Path.cwd(),{'delivery_requirements_version':'future'})
        self.assertEqual(construction_checks(Path.cwd(),{})['status'],'historical-contract')

    def test_actual_duration_boundaries_and_unmodified_older_contract(self):
        for seconds in (60.001,84,300):
            proof=flow_proof(seconds);proof.update(recording_policy_version='flow-complete-v2',timeout_seconds=400)
            self.assertEqual(validate_recording_duration(proof)['duration'],seconds)
        for seconds in (60,300.001):
            proof=flow_proof(seconds);proof.update(recording_policy_version='flow-complete-v2',timeout_seconds=400)
            with self.assertRaises(ValueError):validate_recording_duration(proof)
        proof=flow_proof(420);proof['timeout_seconds']=500
        self.assertEqual(validate_recording_duration(proof)['duration'],420)

    def test_native_quality_requires_original_1080_and_single_crf18_encode(self):
        proof={'recording_policy_version':'flow-complete-v2','width':1920,'height':1080,
            'capture_quality':{'native_width':1920,'native_height':1080,'codec':'libx264','preset':'fast',
                'crf':18,'resized':False,'transcodes_from_raw':1}}
        validate_recording_quality(proof)
        for key,value in (('native_width',1280),('crf',20),('resized',True),('transcodes_from_raw',2)):
            changed=copy.deepcopy(proof);changed['capture_quality'][key]=value
            with self.subTest(key=key),self.assertRaises(ValueError):validate_recording_quality(changed)


if __name__=='__main__':unittest.main()
