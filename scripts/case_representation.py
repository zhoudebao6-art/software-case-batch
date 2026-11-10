"""Source-selected presentation, checked inside existing build/figure/review gates.

Bindings and declarations are not semantic approval or proof of native execution.
The original independent review must inspect the bound runtime and source evidence.
"""

POLICY = 'source-form-v1'
PLAN_POLICY = 'product-realization-v2'
PLAN_POLICIES = {'product-realization-v1', PLAN_POLICY}
FORMS = {
    'desktop_web': ('product_ui', 10),
    'mobile_web': ('product_ui', 1),
    'mini_program': ('native_client', 1),
    'desktop_app': ('native_client', 1),
    'mobile_app': ('native_client', 1),
    'game_web': ('product_ui', 1),
    'game_native': ('native_client', 1),
    'game_mini_program': ('native_client', 1),
    'embedded_headless': ('validation_console', 1),
    'service_headless': ('validation_console', 1),
    'technical_process': ('validation_console', 1),
}
NATIVE = {'mini_program': {'wechat-devtools','alipay-devtools'},
          'desktop_app': {'windows','linux','macos'},
          'mobile_app': {'android','ios'},
          'game_native': {'windows','linux','macos','android','ios'},
          'game_mini_program': {'wechat-devtools','alipay-devtools'}}

# These are evidence levels, not promises that a platform adapter is installed.
LEVELS = {
    'browser': {'browser_execution'},
    'windows': {'desktop_execution'}, 'linux': {'desktop_execution'}, 'macos': {'desktop_execution'},
    'android': {'emulator_execution','device_execution'}, 'ios': {'simulator_execution','device_execution'},
    'wechat-devtools': {'host_devtools_execution','host_device_execution'},
    'alipay-devtools': {'host_devtools_execution','host_device_execution'},
    'host-test': {'host_core_execution'}, 'device': {'device_execution'},
    'service': {'service_execution'}, 'calculation': {'calculation_execution'},
}

def validate_product_plan(rep, runtime, run):
    """Reuse the existing representation/report; never add a planning stage."""
    if 'product_plan_policy' not in run:return None  # Frozen source-form-v1 runs stay unchanged.
    policy=run['product_plan_policy']
    if not isinstance(policy,str) or policy not in PLAN_POLICIES:raise ValueError('Unknown product realization policy')
    plan=rep.get('product_plan')
    if not isinstance(runtime,dict) or not text(runtime.get('runtime')):
        raise ValueError('Product plan requires its actual runtime evidence')
    if not isinstance(plan,dict) or not all(text(plan.get(k)) for k in
            ('subject','core_chain','target_runtime','validation_level','media_route')):
        raise ValueError('Choose the actual product, input-processing-output chain, runtime and media before construction')
    if plan['target_runtime']!=runtime['runtime']:
        raise ValueError('Planned product runtime differs from actual execution; do not silently substitute a website')
    if (plan['validation_level'] not in LEVELS.get(runtime['runtime'],set()) or
            runtime.get('validation_level')!=plan['validation_level']):
        raise ValueError('Planned and actual validation levels must agree; host/simulator is not physical-device proof')
    allowed_media=({'browser_capture'} if runtime['runtime']=='browser' else
                   {'native_capture'} if rep['form'] in NATIVE else
                   {'device_capture','test_harness_capture'} if runtime['runtime']=='device' else
                   {'test_harness_capture'})
    if plan['media_route'] not in allowed_media:
        raise ValueError('Media route must represent the actual product runtime or explicitly scoped test harness')
    if policy==PLAN_POLICY:
        validate_materials(plan,rep,runtime)
    return plan


def validate_materials(plan,rep,runtime,bound=None,assertions=None):
    """Reuse core execution inputs/results; no separate dossier or review round."""
    rows=plan.get('technical_evidence')
    if not isinstance(rows,list) or not rows:
        raise ValueError('System materials must identify the source technique and its actual input/result evidence')
    for row in rows:
        if (not isinstance(row,dict) or not all(text(row.get(k)) for k in
                ('technical_claim','expected_result','boundary')) or
                row.get('provenance') not in ('computed','measured','source_example','illustrative')):
            raise ValueError('Technical evidence needs its claim, expected result, provenance and actual proof boundary')
        ref=row.get('source_ref')
        refs=rep.get('source_refs')
        if (not isinstance(refs,list) or not refs or not all(isinstance(r,dict) and text(r.get('path')) for r in refs)
                or not isinstance(ref,dict) or not text(ref.get('locator')) or not text(ref.get('path')) or
                ref['path'] not in [r['path'] for r in refs]):
            raise ValueError('Technical material must reference the existing source mapping and locator')
        for key in ('input_paths','result_paths','assertion_ids'):
            values=row.get(key)
            if (not isinstance(values,list) or not values or not all(text(v) for v in values)
                    or len(values)!=len(set(values))):
                raise ValueError('Technical material requires distinct actual '+key)
        for path in row['input_paths']+row['result_paths']+[ref['path']]:
            if ('\\' in path or ':' in path or any(part in ('','.','..') for part in path.split('/'))):
                raise ValueError('Technical material paths must be canonical relative POSIX paths')
        runtime_ids=runtime.get('assertion_ids')
        if (not isinstance(runtime_ids,list) or not all(text(i) for i in runtime_ids) or
                not set(row['assertion_ids'])<=set(runtime_ids)):
            raise ValueError('Technical material must use the actual core runtime assertions')
        if set(row['input_paths']) & set(row['result_paths']):
            if (not text(row.get('input_locator')) or not text(row.get('result_locator')) or
                    row['input_locator'].strip()==row['result_locator'].strip()):
                raise ValueError('Shared input/result traces need distinct actual field or column locators')
        if bound is not None:
            paths=set(row['input_paths']+row['result_paths'])
            for path in paths:bound(path)
            linked=set()
            for aid in row['assertion_ids']:
                linked.update(assertions[aid].get('evidence_paths',[]))
            if not paths<=linked:
                raise ValueError('Technical inputs/results must be consumed by the linked execution assertions')
    return rows

def text(value):
    return isinstance(value,str) and bool(value.strip())

def minimum_modules(representation):
    if not isinstance(representation,dict) or not isinstance(representation.get('form'),str) or representation['form'] not in FORMS:
        raise ValueError('Source-selected software form required; do not default every patent to a Web dashboard')
    role,count=FORMS[representation['form']]
    if representation.get('presentation_role') != role:
        raise ValueError('Product interface, native client and validation console must not be confused')
    return count

def validate_representation(web, report, run, mappings, bound, implementation, assertions, hasher=None):
    rep=web.get('representation');minimum=minimum_modules(rep)
    if not text(rep.get('reason')):
        raise ValueError('Explain the source-based runtime/form choice')
    refs=rep.get('source_refs')
    if not isinstance(refs,list) or not refs:
        raise ValueError('Software form must cite source paragraphs or bound explicit user requirements')
    for ref in refs:
        if not isinstance(ref,dict) or ref.get('path') not in mappings or not text(ref.get('locator')):
            raise ValueError('Software form source reference must use a bound mapping and locator')
        bound(ref['path'])
    form=rep['form']
    runtime=report.get('runtime_validation')
    if not isinstance(runtime,dict) or not text(runtime.get('runtime')) or not text(runtime.get('entrypoint')):
        raise ValueError('Describe actual runtime and entrypoint in the existing execution report')
    if form in NATIVE and runtime['runtime'] not in NATIVE[form]:
        raise ValueError('Browser mockup cannot certify a native App or mini-program runtime')
    if form in {'desktop_web','mobile_web','game_web'} and runtime['runtime']!='browser':
        raise ValueError('Web form requires actual browser runtime')
    if form in {'embedded_headless','service_headless','technical_process'}:
        if runtime['runtime'] not in {'device','host-test','service','calculation'} or not text(runtime.get('boundary')):
            raise ValueError('Headless/process validation must state the actual runtime and unverified hardware/experiment boundary')
    paths=runtime.get('implementation_paths');ids=runtime.get('assertion_ids')
    if not isinstance(implementation,dict):
        raise ValueError('Current implementation snapshot must be a file/hash map')
    if not isinstance(paths,list) or not paths or not all(text(p) for p in paths) or len(set(paths))!=len(paths):
        raise ValueError('Actual runtime implementation paths required')
    for path in paths:
        if not isinstance(path,str) or path not in implementation:
            raise ValueError('Runtime implementation is missing from the current source snapshot')
        p=bound(path)
        from common import digest
        if implementation[path] != (hasher or digest)(p):
            raise ValueError('Runtime implementation bytes differ from the current snapshot')
    if form in NATIVE and runtime['entrypoint'] not in paths:
        raise ValueError('Native runtime entrypoint must be an actual bound project file')
    if not isinstance(ids,list) or not ids or not all(isinstance(i,str) and i in assertions for i in ids):
        raise ValueError('Actual runtime assertions must belong to the existing report')
    # Logs are existing execution evidence, not a new report or self-issued pass.
    log=runtime.get('log');bound(log)
    if not all(isinstance(assertions[i].get('evidence_paths'),list) and
               log in assertions[i]['evidence_paths'] for i in ids):
        raise ValueError('Runtime assertions must bind their actual runtime log')
    if form=='mobile_web':
        view=runtime.get('viewport',{})
        if (not isinstance(view,dict) or type(view.get('width')) is not int or type(view.get('height')) is not int or
                not 240<=view['width']<=600 or view['height']<=view['width']):
            raise ValueError('Mobile Web requires an actual portrait mobile viewport check')
    plan=validate_product_plan(rep,runtime,run)
    if run.get('product_plan_policy')==PLAN_POLICY:
        validate_materials(plan,rep,runtime,bound,assertions)
    return {'form':form,'presentation_role':rep['presentation_role'],'reason':rep['reason'],
            'source_refs':refs,'runtime_validation':runtime,'minimum_modules':minimum,
            **({'product_plan':plan} if plan is not None else {})}

def validate_figure_intent(figure, strict=False):
    intent=figure.get('technical_purpose')
    roles={'quantitative_result','geometry_relation','control_response','algorithm_structure',
           'signal_sequence','image_processing','material_characterization','interaction_state',
           'system_structure','state_transition','circuit_connection'}
    if (not isinstance(intent,dict) or not text(intent.get('role')) or intent.get('role') not in roles or
            not all(text(intent.get(k)) for k in ('source_locator','technical_feature','why_this_form'))):
        raise ValueError('Figure must identify its source feature and technical purpose, not a generic chart template')
    if not text(intent.get('depiction')) or intent.get('depiction') not in {'computed_plot','source_based_diagram','measured_image','interface_state'}:
        raise ValueError('Declare the actual depiction, without confusing a product screenshot with patent technical evidence')
    if intent['depiction']=='interface_state' and intent['role']!='interaction_state':
        raise ValueError('Interface screenshots cannot substitute for algorithm, hardware or measured-effect evidence')
    if intent['depiction']=='measured_image' and not text(intent.get('measurement_source')):
        raise ValueError('Measured image needs real measurement provenance; rendered texture is not microscopy')
    if strict:
        if intent['role'] in {'system_structure','state_transition','circuit_connection','algorithm_structure'} and intent['depiction']!='source_based_diagram':
            raise ValueError('Technical structure/state/circuit drawings need source-based relationships, not UI or numeric decoration')
        if intent['role'] in {'quantitative_result','control_response','material_characterization'} and intent['depiction'] not in {'computed_plot','measured_image'}:
            raise ValueError('A structural drawing cannot stand in for calculated or measured result evidence')
    return intent
