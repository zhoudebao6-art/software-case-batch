"""Gate fixtures only: these do not attest a real product or browser session."""
import copy
import unittest
import test_web_contract as fixtures
from observed_outcomes import POLICY, outcome_policy
from common import read_json, write_json
import test_product_flow as flow
from proflow import prepare


class OutcomeTests(unittest.TestCase):
    setUp=fixtures.WebContractTests.setUp
    tearDown=fixtures.WebContractTests.tearDown
    file=fixtures.WebContractTests.file
    image=fixtures.WebContractTests.image
    assertion=fixtures.WebContractTests.assertion
    save=fixtures.WebContractTests.save
    validate=fixtures.WebContractTests.validate
    def outcomes(self):
        self.run['web_outcome_policy'] = POLICY
        first = self.report['assertions'][0]
        first.update(observed_input={'object':'A','input':2}, comparisons=[
            {'label':'UI object','expected':'A','actual':'A'},
            {'label':'calculation','expected':{'value':4,'version':1},'actual':{'value':4,'version':1}}])
        second=copy.deepcopy(first)
        second.update(id='second', action='calculate-second', observed_input={'object':'B','input':3},
                      comparisons=[{'label':'calculation','expected':{'object':'B','value':6},'actual':{'object':'B','value':6}}])
        recovery=copy.deepcopy(first)
        recovery.update(id='recover',action='correct-invalid',observed_input={'invalid':'bad','corrected':2},
                        recovery_observation={'trigger':'TEST invalid parameter','observed_error':'TEST input must be numeric','resumed_action':'TEST correct then calculate'})
        self.report['assertions'] += [second,recovery]
        self.report['core_outcomes']={'primary':'calculation','changed_input':'second','recovery':'recover'}
        wf=self.web['workflows'][0]
        wf['actions'] += ['calculate-second','correct-invalid']
        wf['assertion_ids'] += ['second','recover']
        self.save()

    def test_good_values_bind_to_existing_report(self):
        self.outcomes(); value=self.validate()
        self.assertEqual(value['web_outcome_policy'],POLICY)
        self.assertEqual(value['core_outcomes'],self.report['core_outcomes'])
        self.assertIn('browser-report.json',value['evidence_hashes'])

    def test_pass_flag_cannot_mask_wrong_actual_result(self):
        self.outcomes(); self.report['assertions'][1]['comparisons'][0]['actual']['value']=4;self.save()
        with self.assertRaisesRegex(ValueError,'differs from expected'):self.validate()

    def test_changed_label_is_not_changed_input(self):
        self.outcomes(); self.report['assertions'][1]['observed_input']=self.report['assertions'][0]['observed_input'];self.save()
        with self.assertRaisesRegex(ValueError,'did not change'):self.validate()

    def test_boolean_or_generic_success_is_not_business_result(self):
        for actual in (True,'success',{},[],None):
            self.outcomes() if 'core_outcomes' not in self.report else None
            self.report['assertions'][0]['comparisons']=[{'label':'status','expected':actual,'actual':actual}];self.save()
            with self.assertRaisesRegex(ValueError,'only success'):self.validate()

    def test_types_and_nonfinite_values_rejected(self):
        self.outcomes()
        for expected,actual in [(1,True),(float('nan'),float('nan')),(float('inf'),float('inf'))]:
            self.report['assertions'][0]['comparisons']=[{'label':'value','expected':expected,'actual':actual}];self.save()
            with self.assertRaises(ValueError):self.validate()

    def test_recovery_must_observe_failure(self):
        self.outcomes();self.report['assertions'][2].pop('recovery_observation');self.save()
        with self.assertRaisesRegex(ValueError,'actual failure'):self.validate()

    def test_role_reuse_or_missing_policy_report_rejected(self):
        self.outcomes();self.report['core_outcomes']['recovery']='second';self.save()
        with self.assertRaisesRegex(ValueError,'distinct'):self.validate()
        self.report.pop('core_outcomes');self.save()
        with self.assertRaisesRegex(ValueError,'must reference'):self.validate()

    def test_unchanged_output_can_be_domain_correct(self):
        self.outcomes();self.report['assertions'][1]['comparisons']=copy.deepcopy(self.report['assertions'][0]['comparisons']);self.save()
        self.assertEqual(self.validate()['status'],'ready')

    def test_old_contract_unchanged_unknown_policy_rejected(self):
        self.assertNotIn('web_outcome_policy',self.validate())
        self.run['web_outcome_policy']='unknown'
        with self.assertRaisesRegex(ValueError,'Unknown Web outcome'):self.validate()


class PreparedOutcomeTests(unittest.TestCase):
    setUp=flow.FlowTests.setUp
    tearDown=flow.FlowTests.tearDown

    def test_new_contract_and_handoff(self):
        run=read_json(self.work/'.product-v2/run.json')
        self.assertEqual(outcome_policy(run),POLICY)
        text=(self.work/'.product-v2/深化命令词.txt').read_text('utf-8')
        self.assertIn('references/product-quality.md',text.replace('\\','/'))
        self.assertIn('core_outcomes',text)

    def test_existing_run_bytes_and_legacy_contract_preserved(self):
        path=self.work/'.product-v2/run.json';run=read_json(path)
        run.pop('web_outcome_policy');write_json(path,run);before=path.read_bytes()
        prompt=self.work/'.product-v2/深化命令词.txt';prompt.write_bytes(b'frozen')
        prepare(self.work,self.out,'设备运行管理',self.source)
        self.assertEqual(path.read_bytes(),before);self.assertEqual(prompt.read_bytes(),b'frozen')


if __name__=='__main__':unittest.main()
