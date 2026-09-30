"""Declarative capture boundary tests; real browser integration is a separate fixture."""
import copy
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from io import BytesIO
import test_caseflow
from capture_runner import CaptureError, validate_plan, service_ready, digest


class CapturePlanTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.case=Path(self.temp.name).resolve()
        (self.case/'evidence').mkdir();(self.case/'app.py').write_text('pass')
        self.plan={'schema_version':1,'case_id':'case','base_url':'http://127.0.0.1:12345','health_path':'/health','version':'v1',
            'application_files':{'app.py':digest(self.case/'app.py')},'modules':[{'name':'Tasks','route':'/tasks','heading':'Tasks','ready_selectors':['#ready']}]}
        self.save()
    def tearDown(self):self.temp.cleanup()
    def save(self):(self.case/'evidence/capture-plan.json').write_text(json.dumps(self.plan),encoding='utf-8')
    def test_valid_plan_and_health_identity(self):
        self.assertEqual(validate_plan(self.case,'case',[12345]),self.plan)
        data={'case_id':'case','workspace':str(self.case),'version':'v1'}
        with patch('capture_runner.urlopen',return_value=BytesIO(json.dumps(data).encode())):
            self.assertEqual(service_ready(self.case,'case',self.plan),data)
    def test_wrong_service_identity_and_malformed_health_rejected(self):
        for data in [b'{}',b'[]',b'bad',json.dumps({'case_id':'another','workspace':str(self.case),'version':'v1'}).encode()]:
            with self.subTest(data=data),patch('capture_runner.urlopen',return_value=BytesIO(data)),self.assertRaises(CaptureError):
                service_ready(self.case,'case',self.plan)
    def test_foreign_ports_credentials_and_path_escape_rejected(self):
        original=copy.deepcopy(self.plan)
        for values in [{'base_url':'http://127.0.0.1:23456'},{'base_url':'http://127.0.0.1:bad'},
                       {'base_url':'http://user@127.0.0.1:12345'},{'base_url':'http://example.org'},
                       {'application_files':{'../app.py':'x'}},{'case_id':'foreign'}]:
            self.plan={**original,**values};self.save()
            with self.subTest(values=values),self.assertRaises(CaptureError):validate_plan(self.case,'case',[12345])
    def test_modified_source_and_unbounded_modules_rejected(self):
        (self.case/'app.py').write_text('changed')
        with self.assertRaises(CaptureError):validate_plan(self.case,'case',[12345])
        self.plan['application_files']['app.py']=digest(self.case/'app.py')
        self.plan['modules']*=3;self.save()
        with self.assertRaises(CaptureError):validate_plan(self.case,'case',[12345])
