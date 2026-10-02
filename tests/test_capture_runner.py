"""Declarative capture boundary tests; real browser integration is a separate fixture."""
import copy
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from io import BytesIO
import test_caseflow
from capture_runner import CaptureError, CaptureEnvironmentError, validate_plan, service_ready, digest


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

    def test_health_redirect_is_rejected(self):
        from capture_runner import LocalHealthOnly
        with self.assertRaises(CaptureEnvironmentError):
            LocalHealthOnly().redirect_request(None, None, 302, 'redirect', {}, 'https://foreign.invalid/health')
        class Redirected(BytesIO):
            def geturl(self):
                return 'http://127.0.0.1:19000/health'
        data={'case_id':'case','workspace':str(self.case),'version':'v1'}
        with patch('capture_runner.urlopen',return_value=Redirected(json.dumps(data).encode())),self.assertRaises(CaptureEnvironmentError):
            service_ready(self.case,'case',self.plan)

    def test_foreign_service_and_declared_pid_conflict_are_environment_problems(self):
        identity={'pid':1234,'port':12345,'created_at':'old','command_line_sha256':'a'*64}
        for data in ({'case_id':'foreign','workspace':str(self.case),'version':'v1'},
                     {'case_id':'case','workspace':str(self.case),'version':'v1','pid':5678}):
            self.plan['service_identity']=identity
            with self.subTest(data=data), patch('capture_runner.urlopen',return_value=BytesIO(json.dumps(data).encode())), \
                 patch('capture_runner._listener_identity') as probe, self.assertRaises(CaptureEnvironmentError):
                service_ready(self.case,'case',self.plan)
            probe.assert_not_called()

    def test_declared_service_identity_checks_live_listener_tuple(self):
        identity={'pid':1234,'port':12345,'created_at':'20261001120000.000000+000','command_line_sha256':'a'*64}
        self.plan['service_identity']=identity; self.save()
        data={'case_id':'case','workspace':str(self.case),'version':'v1',**{k:identity[k] for k in ('pid','port','created_at')}}
        with patch('capture_runner.urlopen',return_value=BytesIO(json.dumps(data).encode())), \
             patch('capture_runner._listener_identity',return_value=identity) as probe:
            self.assertEqual(service_ready(self.case,'case',self.plan),data)
        probe.assert_called_once_with(12345)

    def test_declared_pid_reuse_is_an_environment_problem(self):
        from capture_runner import CaptureEnvironmentError
        identity={'pid':1234,'port':12345,'created_at':'old','command_line_sha256':'a'*64}
        self.plan['service_identity']=identity
        data={'case_id':'case','workspace':str(self.case),'version':'v1'}
        with patch('capture_runner.urlopen', return_value=BytesIO(json.dumps(data).encode())), \
             patch('capture_runner._listener_identity', return_value={**identity, 'created_at':'new'}), \
             self.assertRaises(CaptureEnvironmentError):
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
