"""Synthetic gate fixtures only: no case, browser run, license or inference proof.

Even accepted image fixtures are deliberately generated test pixels. This proves
the gate's documented limitation: a decoder cannot authenticate provenance.
"""
import copy
import json
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from common import digest
from web_contract import WEB_EXPERIENCE_POLICY, validate_web_experience


class WebContractTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='TEST_ONLY_web_contract_')
        self.work = Path(self.temp.name)
        self.file('original.docx', b'TEST ONLY source hash fixture, not a Word case')
        self.run = {'run_id': 'TEST_ONLY_gate_fixture', 'source_docx': str(self.work / 'original.docx'),
                    'source_docx_sha256': digest(self.work / 'original.docx'),
                    'web_experience_policy': WEB_EXPERIENCE_POLICY}
        self.spec = {'run_id': self.run['run_id'], 'source_docx_sha256': self.run['source_docx_sha256'],
                     'implementation_hashes': {}, 'checks': {'browser': {'input_files': {}}}}
        self.file('app.py', b'# TEST ONLY implementation fixture\n')
        self.file('mapping.json', b'{"TEST_ONLY": "source paragraph locator fixture"}')
        self.file('execution.log', b'TEST ONLY assertion log; not a real browser execution\n')
        self.image('screen.png', 'gray')
        self.web = {'system_types': ['calculation'], 'source_mapping': ['mapping.json'],
                    'pages': [{'id': 'workbench', 'route': '/tasks', 'purpose': 'TEST ONLY task workspace',
                               'workflow_ids': ['task'], 'screenshot': 'screen.png'}],
                    'workflows': [{'id': 'task', 'purpose': 'TEST ONLY process task', 'implemented': True,
                                   'source_refs': [{'path': 'mapping.json', 'locator': 'TEST_ONLY paragraph 2'}],
                                   'page_ids': ['workbench'], 'actions': ['calculate'],
                                   'expected_result': 'TEST ONLY saved result',
                                   'implementation_paths': ['app.py'], 'assertion_ids': ['calculation']}],
                    'report': 'browser-report.json'}
        self.spec['web_experience'] = self.web
        self.report = {'run_id': self.run['run_id'], 'source_docx_sha256': self.run['source_docx_sha256'],
                       'assertions': [{'id': 'calculation', 'workflow_id': 'task', 'page_ids': ['workbench'],
                                       **self.assertion('calculate')}]}
        self.save()

    def tearDown(self):
        self.temp.cleanup()

    def file(self, name, value):
        target = self.work / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(value)
        return target

    def image(self, name, color):
        from PIL import Image
        Image.new('RGB', (8, 7), color).save(self.work / name)

    def assertion(self, action):
        return {'action': action, 'expected': 'TEST ONLY expected value', 'actual': 'TEST ONLY actual value',
                'passed': True, 'evidence_paths': ['execution.log']}

    def save(self):
        self.file('browser-report.json', json.dumps(self.report).encode())
        files = {p.relative_to(self.work).as_posix(): digest(p) for p in self.work.rglob('*') if p.is_file()}
        self.spec['checks']['browser']['input_files'] = files
        self.spec['implementation_hashes'] = {'app.py': files['app.py']}

    def validate(self):
        return validate_web_experience(self.work, self.run, self.spec)

    def add_second_page(self):
        self.web['pages'].append({'id': 'result', 'route': '/results', 'purpose': 'TEST ONLY results',
                                  'workflow_ids': ['task'], 'screenshot': 'screen.png'})
        self.web['workflows'][0]['page_ids'].append('result')
        self.report['assertions'][0]['page_ids'].append('result')
        self.save()

    def vision(self):
        self.web['system_types'].append('vision')
        self.file('TEST_ONLY_provenance.json', b'{"note":"GENERATED UNIT TEST PIXELS. NOT REAL IMAGE, LICENSE OR INFERENCE PROOF."}')
        samples = []
        for index, color in enumerate(('red', 'blue')):
            name = f'TEST_ONLY_pixels_{index}.png'
            self.image(name, color)
            sha = digest(self.work / name)
            request = f'TEST_ONLY_request_{index}'
            output_name = f'TEST_ONLY_output_{index}.json'
            receipt = {'run_id': self.run['run_id'], 'source_docx_sha256': self.run['source_docx_sha256'],
                       'input_sha256': sha, 'request_id': request,
                       'result': {'TEST_ONLY': 'fabricated gate fixture; no inference occurred'}}
            self.file(output_name, json.dumps(receipt).encode())
            samples.append({'id': f'TEST_ONLY_sample_{index}', 'input_path': name, 'input_sha256': sha,
                            'input_kind': 'real_image',
                            'provenance': {'origin': 'user_authorized', 'source': 'TEST ONLY generated pixels; no provenance claim',
                                           'license': 'TEST ONLY schema value; not actual image license evidence',
                                           'record': 'TEST_ONLY_provenance.json'},
                            'backend': {'entry_path': 'app.py', 'entrypoint': 'TEST_ONLY_handler', 'request_id': request},
                            'output': {'path': output_name, 'sha256': digest(self.work / output_name),
                                       'input_sha256': sha, 'request_id': request, 'summary': 'TEST ONLY fabricated schema result'},
                            'assertions': [self.assertion('TEST ONLY compare result')]})
        self.report['vision'] = {'task_type': 'classification', 'workflow_id': 'task', 'samples': samples,
                                 'edge_cases': [{'kind': 'no_target', **self.assertion('TEST ONLY no target')}]}
        self.save()

    def test_historical_run_has_no_new_requirements(self):
        self.run.pop('web_experience_policy')
        self.assertEqual(validate_web_experience(self.work, self.run, {}),
                         {'required': False, 'status': 'historical-contract'})

    def test_unknown_policy_and_missing_web_rejected(self):
        self.run['web_experience_policy'] = 'future'
        with self.assertRaisesRegex(ValueError, 'Unknown'): self.validate()
        self.run['web_experience_policy'] = WEB_EXPERIENCE_POLICY
        self.spec.pop('web_experience')
        with self.assertRaisesRegex(ValueError, 'web_experience'): self.validate()

    def test_one_page_real_task_contract_has_no_fixed_page_quota(self):
        result = self.validate()
        self.assertEqual(result['page_ids'], ['workbench'])
        self.assertIn('browser-report.json', result['evidence_paths'])
        self.assertIn('mapping.json', result['evidence_paths'])
        self.assertIn('screen.png', result['evidence_paths'])
        self.assertIn('execution.log', result['evidence_paths'])
        self.assertIn('does not authenticate', result['limitation'])

    def test_multiple_pages_follow_actual_workflow(self):
        self.add_second_page()
        self.assertEqual(len(self.validate()['page_ids']), 2)

    def test_empty_core_workflow_and_unimplemented_rejected(self):
        original = copy.deepcopy(self.web['workflows'])
        for value in ([], [dict(original[0], implemented=False)], [dict(original[0], actions=[])]):
            with self.subTest(value=value):
                self.web['workflows'] = value
                with self.assertRaises(ValueError): self.validate()

    def test_duplicate_ids_routes_and_unknown_references_rejected(self):
        for key, value in [('id', 'workbench'), ('route', '/tasks'), ('workflow_ids', ['unknown'])]:
            self.add_second_page()
            self.web['pages'][1][key] = value
            with self.subTest(key=key), self.assertRaises(ValueError): self.validate()
            self.web['pages'].pop()
            self.web['workflows'][0]['page_ids'].pop()
            self.report['assertions'][0]['page_ids'].pop()
            self.save()
        self.web['workflows'][0]['page_ids'] = ['unknown']
        with self.assertRaisesRegex(ValueError, 'Unknown Web page'): self.validate()

    def test_page_coverage_must_be_bidirectional_and_actually_tested(self):
        self.add_second_page()
        self.web['pages'][1]['workflow_ids'] = ['unknown']
        with self.assertRaises(ValueError): self.validate()
        self.web['pages'][1]['workflow_ids'] = ['task']
        self.report['assertions'][0]['page_ids'] = ['workbench']; self.save()
        with self.assertRaisesRegex(ValueError, 'untested'): self.validate()

    def test_unmapped_action_missing_assertion_and_boolean_only_rejected(self):
        original = copy.deepcopy(self.report)
        for mutate in (lambda: self.web['workflows'][0]['actions'].append('save'),
                       lambda: self.web['workflows'][0].update(assertion_ids=['unknown']),
                       lambda: self.report['assertions'][0].update(actual=''),
                       lambda: self.report['assertions'][0].update(passed=False)):
            web = copy.deepcopy(self.web); self.report = copy.deepcopy(original)
            mutate(); self.save()
            with self.assertRaises(ValueError): self.validate()
            self.web.clear(); self.web.update(web)

    def test_report_source_and_original_bytes_bound(self):
        self.report['source_docx_sha256'] = 'wrong'; self.save()
        with self.assertRaisesRegex(ValueError, 'different run or source'): self.validate()
        self.report['source_docx_sha256'] = self.run['source_docx_sha256']; self.save()
        self.file('original.docx', b'changed')
        with self.assertRaisesRegex(ValueError, 'source changed'): self.validate()

    def test_missing_changed_empty_and_escaping_evidence_rejected(self):
        for name in ('mapping.json', 'screen.png', 'browser-report.json', 'execution.log'):
            before = (self.work / name).read_bytes()
            self.file(name, before + b'changed')
            with self.subTest(name=name), self.assertRaises(ValueError): self.validate()
            self.file(name, before)
        self.file('execution.log', b''); self.save()
        with self.assertRaisesRegex(ValueError, 'Empty'): self.validate()
        self.file('execution.log', b'TEST ONLY log'); self.save()
        self.web['pages'][0]['screenshot'] = '../outside.png'
        with self.assertRaisesRegex(ValueError, 'Unsafe'): self.validate()

    def test_unbound_mapping_screenshot_report_and_implementation_rejected(self):
        for name in ('mapping.json', 'screen.png', 'browser-report.json', 'execution.log', 'app.py'):
            sha = self.spec['checks']['browser']['input_files'].pop(name)
            with self.subTest(name=name), self.assertRaises(ValueError): self.validate()
            self.spec['checks']['browser']['input_files'][name] = sha
        self.spec['implementation_hashes'] = {}
        with self.assertRaisesRegex(ValueError, 'implementation'): self.validate()

    def test_bad_screenshot_is_decoded_not_extension_checked(self):
        self.file('screen.png', b'TEST ONLY not an image'); self.save()
        with self.assertRaisesRegex(ValueError, 'decodable'): self.validate()

    def test_vision_contract_accepts_classification_without_bbox_mask_confidence(self):
        self.vision()
        self.assertIn('vision', self.validate()['system_types'])

    def test_vision_no_target_empty_result_requires_explicit_status(self):
        self.vision()
        sample = self.report['vision']['samples'][0]
        path = sample['output']['path']
        receipt = json.loads((self.work / path).read_text())
        receipt.update(status='no_target', result=[])
        self.file(path, json.dumps(receipt).encode())
        sample['output']['sha256'] = digest(self.work / path); self.save()
        self.assertTrue(self.validate()['required'])
        receipt.pop('status')
        self.file(path, json.dumps(receipt).encode())
        sample['output']['sha256'] = digest(self.work / path); self.save()
        with self.assertRaisesRegex(ValueError, 'actual output'): self.validate()

    def test_nonvision_does_not_need_images_or_vision_report(self):
        self.assertNotIn('vision', self.report)
        self.assertTrue(self.validate()['required'])

    def test_vision_missing_report_license_or_actual_entry_rejected(self):
        self.web['system_types'].append('vision')
        with self.assertRaisesRegex(ValueError, 'Vision'): self.validate()
        self.web['system_types'].pop(); self.vision()
        vision = copy.deepcopy(self.report['vision'])
        for key, value in [('provenance', {}), ('backend', {}), ('input_kind', 'imagegen')]:
            self.report['vision'] = copy.deepcopy(vision)
            self.report['vision']['samples'][0][key] = value; self.save()
            with self.subTest(key=key), self.assertRaises(ValueError): self.validate()

    def test_vision_must_bind_existing_task_and_distinct_requests(self):
        self.vision(); original = copy.deepcopy(self.report['vision'])
        self.report['vision']['workflow_id'] = 'unknown'; self.save()
        with self.assertRaisesRegex(ValueError, 'Vision'): self.validate()
        self.report['vision'] = original
        first, second = self.report['vision']['samples']
        second['backend']['request_id'] = first['backend']['request_id']; self.save()
        with self.assertRaisesRegex(ValueError, 'distinct actual'): self.validate()

    def test_vision_distinct_decoded_content_required_not_renamed_copy(self):
        self.vision()
        first, second = self.report['vision']['samples']
        second['input_path'] = first['input_path']; second['input_sha256'] = first['input_sha256']
        second['output']['input_sha256'] = first['input_sha256']
        receipt = json.loads((self.work / second['output']['path']).read_text())
        receipt['input_sha256'] = first['input_sha256']
        self.file(second['output']['path'], json.dumps(receipt).encode())
        second['output']['sha256'] = digest(self.work / second['output']['path']); self.save()
        with self.assertRaisesRegex(ValueError, 'different decoded content'): self.validate()

    def test_vision_result_identity_and_failure_state_checks_required(self):
        self.vision(); original = copy.deepcopy(self.report['vision'])
        self.report['vision']['samples'][0]['output']['request_id'] = 'mismatch'; self.save()
        with self.assertRaisesRegex(ValueError, 'identity'): self.validate()
        self.report['vision'] = copy.deepcopy(original)
        sample = self.report['vision']['samples'][0]
        receipt = json.loads((self.work / sample['output']['path']).read_text())
        receipt['input_sha256'] = 'wrong'
        self.file(sample['output']['path'], json.dumps(receipt).encode())
        sample['output']['sha256'] = digest(self.work / sample['output']['path']); self.save()
        with self.assertRaisesRegex(ValueError, 'identity'): self.validate()
        self.report['vision'] = copy.deepcopy(original)
        # Restore the deliberately fabricated output fixture before testing edge state.
        receipt['input_sha256'] = sample['input_sha256']
        self.file(sample['output']['path'], json.dumps(receipt).encode()); self.save()
        self.report['vision']['edge_cases'] = []; self.save()
        with self.assertRaisesRegex(ValueError, 'failure or no-target'): self.validate()


if __name__ == '__main__':
    unittest.main()
