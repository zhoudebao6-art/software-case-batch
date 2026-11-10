"""Contract fixtures, not proof that any native application/device ran."""
import copy
import unittest
from test_ten_modules import TenModuleGateTests
from case_representation import POLICY, PLAN_POLICY, FORMS, validate_figure_intent
from evidence_index import _required_review_paths


class RepresentationTests(unittest.TestCase):
    setUp=TenModuleGateTests.setUp
    tearDown=TenModuleGateTests.tearDown
    file=TenModuleGateTests.file
    image=TenModuleGateTests.image
    assertion=TenModuleGateTests.assertion
    save=TenModuleGateTests.save
    validate=TenModuleGateTests.validate
    rich=TenModuleGateTests.rich
    ten=TenModuleGateTests.ten
    frozen_scope=TenModuleGateTests.frozen_scope

    def form(self,form='desktop_web',count=10):
        self.ten(count)
        self.run['web_module_policy']=POLICY
        self.web['representation']={'form':form,'presentation_role':FORMS[form][0],
            'reason':'TEST source technical task',
            'source_refs':[{'path':'mapping.json','locator':'TEST paragraph 2'}]}
        runtime={'mini_program':'wechat-devtools','mobile_app':'android','desktop_app':'windows',
                 'game_native':'windows','game_mini_program':'wechat-devtools',
                 'embedded_headless':'host-test','service_headless':'service',
                 'technical_process':'calculation'}.get(form,'browser')
        self.report['runtime_validation']={'runtime':runtime,'entrypoint':'app.py',
            'implementation_paths':['app.py'],'assertion_ids':['assertion-0'],'log':'execution.log',
            'boundary':'TEST host execution only, no physical device or measured experiment',
            'viewport':{'width':390,'height':844}}
        self.save()

    def test_desktop_minimum_preserved_other_forms_source_coverage(self):
        for form in FORMS:
            with self.subTest(form=form):
                self.form(form,10 if form=='desktop_web' else 2)
                value=self.validate()
                self.assertEqual(value['representation']['form'],form)
                self.assertEqual(value['minimum_business_modules'],10 if form=='desktop_web' else 1)
        self.form(count=9)
        with self.assertRaisesRegex(ValueError,'at least 10'):self.validate()

    def test_source_choice_is_mandatory_and_bound(self):
        for mutation in ('missing','unknown','badrole','no_reason','no_source','foreign_source','no_locator'):
            self.form()
            rep=self.web['representation']
            if mutation=='missing':self.web.pop('representation')
            if mutation=='unknown':rep['form']='generic'
            if mutation=='badrole':rep['presentation_role']='validation_console'
            if mutation=='no_reason':rep['reason']=''
            if mutation=='no_source':rep['source_refs']=[]
            if mutation=='foreign_source':rep['source_refs'][0]['path']='other.json'
            if mutation=='no_locator':rep['source_refs'][0]['locator']=''
            with self.subTest(mutation=mutation),self.assertRaises(ValueError):self.validate()

    def test_browser_cannot_certify_native_or_device(self):
        for form in ('mini_program','desktop_app','mobile_app','game_native','game_mini_program','embedded_headless'):
            self.form(form,2)
            self.report['runtime_validation']['runtime']='browser';self.save()
            with self.subTest(form=form),self.assertRaises(ValueError):self.validate()

    def plan(self, form='embedded_headless'):
        self.form(form,2)
        self.run['product_plan_policy']=PLAN_POLICY
        rt=self.report['runtime_validation']
        level={'host-test':'host_core_execution','windows':'desktop_execution','wechat-devtools':'host_devtools_execution','android':'emulator_execution','browser':'browser_execution'}[rt['runtime']]
        rt['validation_level']=level
        self.web['representation']['product_plan']={'subject':'TEST sampling controller','core_chain':'TEST sample -> filter -> control output',
            'target_runtime':rt['runtime'],'validation_level':level,
            'media_route':'test_harness_capture' if form=='embedded_headless' else 'browser_capture' if rt['runtime']=='browser' else 'native_capture',
            'technical_evidence':[{'technical_claim':'TEST filtering relation',
                'source_ref':{'path':'mapping.json','locator':'TEST paragraph 2'},
                'expected_result':'TEST output agrees with reference computation',
                'provenance':'computed','boundary':'TEST fixture only; no device measurements',
                'input_paths':['input.json'],'result_paths':['result.json'],'assertion_ids':['assertion-0']}]}
        self.file('input.json',b'{"sample": 1}')
        self.file('result.json',b'{"filtered": 1}')
        self.report['assertions'][0]['evidence_paths']+=['input.json','result.json']
        self.save()

    def test_materials_use_actual_bound_core_inputs_and_results(self):
        for mutation in ('missing','empty','claim','source','input','result','same','assertion','unlinked','changed'):
            self.plan();plan=self.web['representation']['product_plan'];row=plan['technical_evidence'][0]
            if mutation=='missing':plan.pop('technical_evidence')
            if mutation=='empty':plan['technical_evidence']=[]
            if mutation=='claim':row['technical_claim']=''
            if mutation=='source':row['source_ref']['path']='foreign.json'
            if mutation=='input':row['input_paths']=['absent.csv']
            if mutation=='result':row['result_paths']=[]
            if mutation=='same':row['result_paths']=row['input_paths'][:]
            if mutation=='assertion':row['assertion_ids']=['assertion-1']
            if mutation=='unlinked':self.report['assertions'][0]['evidence_paths'].remove('result.json')
            self.save()
            if mutation=='changed':(self.work/'result.json').write_text('{"filtered": 999}')
            with self.subTest(mutation=mutation),self.assertRaises(ValueError):self.validate()

    def test_frozen_v1_plan_does_not_require_new_materials(self):
        self.plan();self.run['product_plan_policy']='product-realization-v1'
        self.web['representation']['product_plan'].pop('technical_evidence');self.save()
        self.validate()

    def test_material_aliases_fail_during_build_not_later_review(self):
        for path in ('./input.json','folder/../input.json','folder\\input.json','/input.json','C:/input.json','folder//input.json'):
            self.plan();row=self.web['representation']['product_plan']['technical_evidence'][0]
            row['result_paths']=[path];self.report['assertions'][0]['evidence_paths'].append(path);self.save()
            with self.subTest(path=path),self.assertRaisesRegex(ValueError,'canonical relative'):
                self.validate()

    def test_one_real_trace_can_contain_both_input_and_output(self):
        self.plan();row=self.web['representation']['product_plan']['technical_evidence'][0]
        self.file('trace.json',b'{"input": 1, "output": 1}')
        row.update(input_paths=['trace.json'],result_paths=['trace.json'],input_locator='$.input',result_locator='$.output')
        self.report['assertions'][0]['evidence_paths'].append('trace.json');self.save();self.validate()
        row['result_locator']='$.input';self.save()
        with self.assertRaisesRegex(ValueError,'distinct actual'):self.validate()

    def test_frozen_materials_cannot_drop_bound_result(self):
        self.plan();scope=self.frozen_scope();run=dict(self.run,word_name='original.docx')
        scope['web']['evidence_hashes'].pop('result.json')
        with self.assertRaisesRegex(ValueError,'technical materials'):
            _required_review_paths(self.work,run,scope,[],{'original.docx':'1'*64},current=False)

    def test_product_plan_is_bound_to_actual_runtime_level_and_media(self):
        for form in ('embedded_headless','mobile_app','mini_program','game_native','game_mini_program','mobile_web'):
            self.plan(form);value=self.validate()
            self.assertEqual(value['representation']['product_plan'],self.web['representation']['product_plan'])
        for mutation in ('absent','subject','core_chain','runtime','level','media','unknown','null'):
            self.plan('mobile_app');plan=self.web['representation']['product_plan']
            if mutation=='absent':self.web['representation'].pop('product_plan')
            if mutation in ('subject','core_chain'):plan[mutation]=''
            if mutation=='runtime':plan['target_runtime']='browser'
            if mutation=='level':self.report['runtime_validation']['validation_level']='device_execution'
            if mutation=='media':plan['media_route']='browser_capture'
            if mutation=='unknown':self.run['product_plan_policy']='unknown'
            if mutation=='null':self.run['product_plan_policy']=None
            self.save()
            with self.subTest(mutation=mutation),self.assertRaises(ValueError):self.validate()

    def test_new_plan_frozen_scope_cannot_drop_plan_or_claim_device(self):
        self.plan();scope=self.frozen_scope();run=dict(self.run,word_name='original.docx')
        _required_review_paths(self.work,run,scope,[],{'original.docx':'1'*64},current=False)
        for mutation in ('remove','device'):
            bad=copy.deepcopy(scope);rep=bad['web']['representation']
            if mutation=='remove':rep.pop('product_plan')
            else:rep['runtime_validation']['validation_level']='device_execution'
            with self.subTest(mutation=mutation),self.assertRaises(ValueError):
                _required_review_paths(self.work,run,bad,[],{'original.docx':'1'*64},current=False)

    def test_runtime_requires_current_real_dependencies(self):
        for mutation in ('missing','no_entry','foreign_path','unbound_log','foreign_assertion','unlinked_log','stale_hash'):
            self.form('mobile_app',2)
            rt=self.report['runtime_validation']
            if mutation=='missing':self.report.pop('runtime_validation')
            if mutation=='no_entry':rt['entrypoint']='absent.py'
            if mutation=='foreign_path':rt['implementation_paths']=['absent.py']
            if mutation=='unbound_log':rt['log']='absent.log'
            if mutation=='foreign_assertion':rt['assertion_ids']=['absent']
            if mutation=='unlinked_log':self.report['assertions'][0]['evidence_paths']=['screen.png']
            self.save()
            if mutation=='stale_hash':self.spec['implementation_hashes']['app.py']='0'*64
            with self.subTest(mutation=mutation),self.assertRaises(ValueError):self.validate()

    def test_mobile_and_host_boundary_are_checked(self):
        for viewport in (None,{}, {'width':1920,'height':1080},{'width':True,'height':844}):
            self.form('mobile_web',2);self.report['runtime_validation']['viewport']=viewport;self.save()
            with self.subTest(viewport=viewport),self.assertRaises(ValueError):self.validate()
        self.form('embedded_headless',2);self.report['runtime_validation'].pop('boundary');self.save()
        with self.assertRaises(ValueError):self.validate()

    def test_portrait_native_png_only_allowed_for_source_selected_mobile_forms(self):
        from PIL import Image
        for form in ('mobile_web','mobile_app','mini_program','desktop_web'):
            self.form(form,10)
            Image.new('RGB',(1080,1920),'gray').save(self.work/'screen.png')
            self.web['delivery_screenshot'].update(native_width=1080,native_height=1920)
            self.save()
            if form=='desktop_web':
                with self.assertRaises(ValueError):self.validate()
            else:self.assertEqual(self.validate()['delivery_screenshot']['height'],1920)
        self.run['web_module_policy']='ten-modules-v1'
        with self.assertRaises(ValueError):self.validate()

    def test_native_game_portrait_follows_actual_platform(self):
        from PIL import Image
        for form,runtime,allowed in [('game_native','android',True),('game_native','ios',True),
                                     ('game_native','windows',False),('game_mini_program','wechat-devtools',True)]:
            self.form(form,2);self.report['runtime_validation']['runtime']=runtime
            Image.new('RGB',(1080,1920),'gray').save(self.work/'screen.png')
            self.web['delivery_screenshot'].update(native_width=1080,native_height=1920);self.save()
            with self.subTest(form=form,runtime=runtime):
                if allowed:self.assertEqual(self.validate()['delivery_screenshot']['height'],1920)
                else:
                    with self.assertRaises(ValueError):self.validate()

    def test_frozen_review_requires_same_representation_and_full_module_bindings(self):
        self.form('embedded_headless',2)
        scope=self.frozen_scope();run=dict(self.run,word_name='original.docx')
        _required_review_paths(self.work,run,scope,[],{'original.docx':'1'*64},current=False)
        for field in ('representation','module_entry_assertions','module_screenshots'):
            bad=copy.deepcopy(scope);bad['web'].pop(field)
            with self.subTest(field=field),self.assertRaises(ValueError):
                _required_review_paths(self.work,run,bad,[],{'original.docx':'1'*64},current=False)


class FigurePurposeTests(unittest.TestCase):
    def test_new_diagram_roles_and_actual_result_evidence(self):
        for role in ('system_structure','state_transition','circuit_connection'):
            f=self.figure();f['technical_purpose'].update(role=role,depiction='source_based_diagram')
            validate_figure_intent(f,strict=True)
            f['technical_purpose']['depiction']='computed_plot'
            with self.assertRaises(ValueError):validate_figure_intent(f,strict=True)
        f=self.figure();f['technical_purpose']['depiction']='source_based_diagram'
        validate_figure_intent(f)  # Previously frozen contracts remain unchanged.
        with self.assertRaises(ValueError):validate_figure_intent(f,strict=True)
        from contracts import chart_records
        rows=[copy.deepcopy(f),copy.deepcopy(f)]
        for i,row in enumerate(rows):row['figure_id']=i+1
        chart_records({'figures':rows},{'web_module_policy':POLICY})
        with self.assertRaises(ValueError):chart_records({'figures':rows},{'web_module_policy':POLICY,'product_plan_policy':PLAN_POLICY})
    def test_real_chart_records_gate_applies_new_policy_only(self):
        from contracts import chart_records
        rows=[{'figure_id':1},{'figure_id':2}]
        self.assertEqual(chart_records({'figures':rows},{}),rows)
        with self.assertRaises(ValueError):
            chart_records({'figures':rows},{'web_module_policy':POLICY})
        for row in rows:row.update(self.figure())
        self.assertEqual(chart_records({'figures':rows},{'web_module_policy':POLICY}),rows)
        with self.assertRaisesRegex(ValueError,'Two to six'):
            chart_records({'figures':rows[:1]},{'web_module_policy':POLICY})

    def figure(self):
        return {'technical_purpose':{'role':'control_response','depiction':'computed_plot',
            'source_locator':'TEST paragraph 6','technical_feature':'TEST feedback transient',
            'why_this_form':'TEST expose overshoot and settling time'}}

    def test_computed_curve_and_source_based_signal_diagram(self):
        f=self.figure();self.assertEqual(validate_figure_intent(f)['role'],'control_response')
        f['technical_purpose'].update(role='signal_sequence',depiction='source_based_diagram')
        validate_figure_intent(f)

    def test_ui_cannot_substitute_for_physical_or_algorithm_evidence(self):
        f=self.figure();f['technical_purpose']['depiction']='interface_state'
        with self.assertRaises(ValueError):validate_figure_intent(f)
        f['technical_purpose']['role']='interaction_state';validate_figure_intent(f)

    def test_missing_why_source_and_fake_micrograph_reject(self):
        for key in ('source_locator','technical_feature','why_this_form','role','depiction'):
            f=self.figure();f['technical_purpose'].pop(key)
            with self.subTest(key=key),self.assertRaises(ValueError):validate_figure_intent(f)
        f=self.figure();f['technical_purpose'].update(role='material_characterization',depiction='measured_image')
        with self.assertRaises(ValueError):validate_figure_intent(f)
        f['technical_purpose']['measurement_source']='TEST real-source reference shape only'
        validate_figure_intent(f)

    def test_malformed_types_fail_cleanly(self):
        for field in ('role','depiction'):
            f=self.figure();f['technical_purpose'][field]={}
            with self.assertRaises(ValueError):validate_figure_intent(f)
