"""Bind case-specific Web tasks to existing execution evidence, without rerunning it.

This gate checks structure and current bytes. Only the existing independent
review can judge source coverage, business correctness or photographic provenance.
"""
import hashlib
import re
from urllib.parse import urlsplit

from common import digest, inside, no_links, read_json, delivery_requirements

WEB_EXPERIENCE_POLICY = 'case-workflow-v1'
WEB_MODULE_POLICY = 'ten-modules-v1'


def web_module_policy(run):
    """An absent field keeps the old module contract; unknown versions fail closed."""
    if 'web_module_policy' not in run:
        return None
    if run['web_module_policy'] != WEB_MODULE_POLICY:
        raise ValueError('Unknown Web module policy')
    return WEB_MODULE_POLICY


def _text(value):
    return isinstance(value, str) and bool(value.strip())


def _texts(value, label):
    if (not isinstance(value, list) or not value or not all(_text(v) for v in value)
            or len(set(value)) != len(value)):
        raise ValueError('Web requires nonempty distinct ' + label)
    return value


def _records(value, label):
    if not isinstance(value, list) or not value or not all(isinstance(v, dict) for v in value):
        raise ValueError('Web requires nonempty ' + label)
    records = {}
    for item in value:
        key = item.get('id')
        if not _text(key) or key in records:
            raise ValueError('Web requires distinct ' + label + ' IDs')
        records[key] = item
    return records


def _image_identity(path):
    """Decode, not authenticate. Pixel identity also catches renamed/reencoded copies."""
    try:
        from PIL import Image
    except ImportError as exc:
        raise ValueError('Pillow is required to decode Web image evidence') from exc
    try:
        with Image.open(path) as image:
            image.verify()
        with Image.open(path) as image:
            image.load()
            pixels = image.convert('RGB')
            return hashlib.sha256(str(pixels.size).encode() + pixels.tobytes()).hexdigest()
    except (OSError, ValueError, Image.DecompressionBombError) as exc:
        raise ValueError('Web image evidence is not a decodable image: ' + str(path)) from exc


def _assertion(record, bound, label):
    if (record.get('passed') is not True or
            not all(_text(record.get(key)) for key in ('action', 'expected', 'actual'))):
        raise ValueError('Web actual passing assertion details required: ' + label)
    for path in _texts(record.get('evidence_paths'), 'assertion evidence paths'):
        bound(path)


def native_delivery_png(path):
    """Check native-size PNG bytes; the existing visual review judges readability."""
    from PIL import Image
    _image_identity(path)
    with Image.open(path) as image:
        if image.format != 'PNG' or image.width < 1920 or image.height < 1080:
            raise ValueError('Delivery screenshot must be an actual PNG at least 1920x1080')
        return {'width': image.width, 'height': image.height, 'sha256': digest(path)}


def validate_web_experience(workspace, run, spec, *, check_delivery=True):
    """Validate the frozen opt-in policy using the existing browser dependency map.

    Missing policy preserves historical runs. No extra browser
    run, model call, human approval, or semantic certification is introduced.
    """
    rich = delivery_requirements(run)
    module_policy = web_module_policy(run)
    if module_policy and not rich:
        raise ValueError('Ten-module Web validation requires its complete rich-delivery contract')
    if rich and run.get('web_experience_policy') != WEB_EXPERIENCE_POLICY:
        raise ValueError('Rich delivery requires its frozen Web experience policy')
    if 'web_experience_policy' not in run:
        return {'required': False, 'status': 'historical-contract'}
    if run['web_experience_policy'] != WEB_EXPERIENCE_POLICY:
        raise ValueError('Unknown Web experience policy')
    workspace = no_links(workspace)
    if (not isinstance(spec, dict) or spec.get('run_id') != run.get('run_id') or
            not _text(run.get('run_id')) or not _text(run.get('source_docx_sha256')) or
            spec.get('source_docx_sha256') != run['source_docx_sha256']):
        raise ValueError('Web evidence belongs to a different run or source')
    if digest(no_links(run['source_docx'])) != run['source_docx_sha256']:
        raise ValueError('Web original Word source changed')
    checks = spec.get('checks', {})
    browser = checks.get('browser', {}) if isinstance(checks, dict) else {}
    dependencies = browser.get('input_files') if isinstance(browser, dict) else None
    if not isinstance(dependencies, dict) or not dependencies:
        raise ValueError('Web requires existing browser input_files binding')
    canonical = {}
    for relative, sha in dependencies.items():
        if not _text(relative) or not isinstance(sha, str) or not re.fullmatch('[0-9a-f]{64}', sha):
            raise ValueError('Invalid Web browser dependency')
        key = relative.replace('\\', '/')
        if key.casefold() in canonical:
            raise ValueError('Duplicate Web browser dependency')
        canonical[key.casefold()] = (key, sha)
    evidence = {}

    def bound(relative):
        if not _text(relative):
            raise ValueError('Web evidence path required')
        path = inside(workspace, relative)
        key = path.relative_to(workspace).as_posix()
        record = canonical.get(key.casefold())
        if record is None or record[0] != key or digest(path) != record[1]:
            raise ValueError('Web evidence missing from browser inputs or changed: ' + key)
        if not path.stat().st_size:
            raise ValueError('Empty Web evidence: ' + key)
        evidence[key] = record[1]
        return path

    web = spec.get('web_experience')
    if not isinstance(web, dict):
        raise ValueError('Case-specific web_experience required')
    system_types = _texts(web.get('system_types'), 'system_types')
    if not all(re.fullmatch('[a-z][a-z0-9_-]*', kind) for kind in system_types):
        raise ValueError('Web system_types must use lowercase identifiers; vision uses vision')
    mappings = _texts(web.get('source_mapping'), 'source mapping paths')
    for path in mappings:
        bound(path)
    pages = _records(web.get('pages'), 'page')
    workflows = _records(web.get('workflows'), 'workflow')
    report_path = bound(web.get('report'))
    report = read_json(report_path)
    if (not isinstance(report, dict) or report.get('run_id') != run['run_id'] or
            report.get('source_docx_sha256') != run['source_docx_sha256']):
        raise ValueError('Web browser report belongs to a different run or source')
    assertions = _records(report.get('assertions'), 'assertion')
    used_assertions = set()
    routes = set()
    for page_id, page in pages.items():
        route = page.get('route')
        if (not _text(route) or not route.startswith('/') or route.startswith('//') or
                urlsplit(route).scheme or urlsplit(route).netloc or route in routes or
                not _text(page.get('purpose'))):
            raise ValueError('Web requires distinct real routes and page purposes')
        routes.add(route)
        associated = _texts(page.get('workflow_ids'), 'page workflow IDs')
        if not set(associated).issubset(workflows):
            raise ValueError('Unknown Web workflow referenced by page')
        _image_identity(bound(page.get('screenshot')))
    implementation = spec.get('implementation_hashes', {})
    for workflow_id, workflow in workflows.items():
        if (not _text(workflow.get('purpose')) or not _text(workflow.get('expected_result')) or
                workflow.get('implemented') is not True):
            raise ValueError('Web requires implemented core workflow and expected result')
        page_ids = _texts(workflow.get('page_ids'), 'workflow page IDs')
        if not set(page_ids).issubset(pages):
            raise ValueError('Unknown Web page referenced by workflow')
        for page_id, page in pages.items():
            if (page_id in page_ids) != (workflow_id in page['workflow_ids']):
                raise ValueError('Web page/workflow coverage is incomplete or inconsistent')
        refs = workflow.get('source_refs')
        if not isinstance(refs, list) or not refs:
            raise ValueError('Web workflow source paragraph references required')
        for ref in refs:
            if (not isinstance(ref, dict) or ref.get('path') not in mappings or
                    not _text(ref.get('locator'))):
                raise ValueError('Web source paragraph locator must reference a bound mapping')
        for relative in _texts(workflow.get('implementation_paths'), 'workflow implementation paths'):
            path = bound(relative)
            if not isinstance(implementation, dict) or implementation.get(relative) != digest(path):
                raise ValueError('Web workflow implementation is absent from current source snapshot')
        actions = _texts(workflow.get('actions'), 'workflow actions')
        assertion_ids = _texts(workflow.get('assertion_ids'), 'workflow assertion IDs')
        tested_actions, tested_pages = set(), set()
        for assertion_id in assertion_ids:
            if assertion_id not in assertions or assertion_id in used_assertions:
                raise ValueError('Unknown or reused Web workflow assertion')
            used_assertions.add(assertion_id)
            assertion = assertions[assertion_id]
            _assertion(assertion, bound, assertion_id)
            actual_pages = _texts(assertion.get('page_ids'), 'assertion page IDs')
            if (assertion.get('workflow_id') != workflow_id or
                    not set(actual_pages).issubset(page_ids) or assertion['action'] not in actions):
                raise ValueError('Web assertion is not bound to its actual workflow action/pages')
            tested_actions.add(assertion['action'])
            tested_pages.update(actual_pages)
        if tested_actions != set(actions) or tested_pages != set(page_ids):
            raise ValueError('Web workflow has untested actions or page coverage')
    if used_assertions != set(assertions):
        raise ValueError('Web browser report has unmapped workflow assertions')
    modules = {}
    delivery_screen = None
    if rich:
        modules = _records(web.get('modules'), 'business module')
        minimum_modules = 10 if module_policy else 6
        if len(modules) < minimum_modules:
            raise ValueError('Web requires at least '+str(minimum_modules)+' independent business modules; no upper limit')
        purposes, locations, module_assertions = set(), set(), set()
        for module_id, module in modules.items():
            purpose, locator = module.get('purpose'), module.get('ui_locator')
            if not _text(purpose) or not _text(locator):
                raise ValueError('Web module needs actual business purpose and page/section locator')
            normalized_purpose = ' '.join(purpose.casefold().split())
            page_ids = _texts(module.get('page_ids'), 'module page IDs')
            workflow_ids = _texts(module.get('workflow_ids'), 'module workflow IDs')
            assertion_ids = _texts(module.get('assertion_ids'), 'module action assertion IDs')
            location = (tuple(sorted(page_ids)), locator.strip())
            if (normalized_purpose in purposes or location in locations or
                    not set(page_ids) <= set(pages) or not set(workflow_ids) <= set(workflows)):
                raise ValueError('Duplicate or missing Web module purpose/location/page/workflow')
            tested_pages, tested_workflows = set(), set()
            for assertion_id in assertion_ids:
                if assertion_id not in assertions or assertion_id in module_assertions:
                    raise ValueError('Web modules require distinct actual action assertions')
                assertion = assertions[assertion_id]
                if (assertion['workflow_id'] not in workflow_ids or
                        not set(assertion['page_ids']) <= set(page_ids)):
                    raise ValueError('Web module assertion is not attached to its actual workflow/pages')
                tested_pages.update(assertion['page_ids']); tested_workflows.add(assertion['workflow_id'])
                module_assertions.add(assertion_id)
            if tested_pages != set(page_ids) or tested_workflows != set(workflow_ids):
                raise ValueError('Web module has empty or untested page/workflow attachment')
            if module_policy:
                entry_id = module.get('entry_assertion_id')
                entry = assertions.get(entry_id) if isinstance(entry_id, str) else None
                if (entry_id not in assertion_ids or not isinstance(entry, dict)
                        or entry.get('entry_visible') is not True
                        or entry.get('ui_locator') != locator):
                    raise ValueError('Each ten-policy module requires its own actual visible entry/action assertion and matching locator')
                screenshot=module.get('screenshot')
                if not _text(screenshot) or screenshot not in entry['evidence_paths']:
                    raise ValueError('Each ten-policy module needs its actual interface screenshot in the entry/action evidence')
                _image_identity(bound(screenshot))
            purposes.add(normalized_purpose); locations.add(location)
        screen = web.get('delivery_screenshot', {})
        page_id = screen.get('page_id') if isinstance(screen, dict) else None
        if (page_id not in pages or screen.get('path') != pages[page_id]['screenshot']
                or screen.get('resized') is not False):
            raise ValueError('Choose one actual native core business page screenshot; resized copies are forbidden')
        delivery_screen = native_delivery_png(bound(screen['path']))
        if (type(screen.get('native_width')) is not int or type(screen.get('native_height')) is not int
                or screen['native_width'] != delivery_screen['width'] or screen['native_height'] != delivery_screen['height']):
            raise ValueError('Delivery screenshot dimensions must match the actual native browser capture')
        delivery_screen.update(path=screen['path'], page_id=page_id)
        if check_delivery and 'output' in run:
            from common import delivery_paths
            target = delivery_paths(run).get('screenshot')
            if target and target.exists() and digest(target) != delivery_screen['sha256']:
                raise ValueError('Delivered screenshot differs from bound actual browser PNG')
    if 'vision' in system_types:
        _validate_vision(report.get('vision'), bound, implementation, run, workflows)
    return {'required': True, 'status': 'ready', 'policy': WEB_EXPERIENCE_POLICY,
            'run_id': run['run_id'], 'source_docx_sha256': run['source_docx_sha256'],
            'system_types': system_types, 'page_ids': list(pages), 'workflow_ids': list(workflows),
            **({'module_ids': list(modules), 'delivery_requirements_version': rich} if rich else {}),
            **({'web_module_policy': module_policy, 'minimum_business_modules': 10,
                'module_entry_assertions': {key: module['entry_assertion_id'] for key,module in modules.items()},
                'module_screenshots': {key: module['screenshot'] for key,module in modules.items()}}
               if module_policy else {}),
            **({'delivery_screenshot': delivery_screen} if delivery_screen else {}),
            'evidence_paths': sorted(evidence), 'evidence_hashes': evidence,
            'limitation': 'Structure and current bytes only; existing independent review must compare original paragraphs, source code, actual screenshots and execution logs. Image decoding does not authenticate real-world content, licensing, task completeness or inference correctness.'}


def _validate_vision(vision, bound, implementation, run, workflows):
    if (not isinstance(vision, dict) or not _text(vision.get('task_type')) or
            vision.get('workflow_id') not in workflows):
        raise ValueError('Vision requires a source-specific task type and actual execution evidence')
    samples = _records(vision.get('samples'), 'vision sample')
    identities, requests = set(), set()
    for sample_id, sample in samples.items():
        image = bound(sample.get('input_path'))
        if sample.get('input_kind') != 'real_image' or sample.get('input_sha256') != digest(image):
            raise ValueError('Vision requires declared real image inputs with current hashes')
        identities.add(_image_identity(image))
        provenance = sample.get('provenance', {})
        if (not isinstance(provenance, dict) or provenance.get('origin') not in
                {'public_licensed', 'user_authorized', 'self_captured'} or
                not all(_text(provenance.get(key)) for key in ('source', 'license'))):
            raise ValueError('Vision image source and license declarations required')
        bound(provenance.get('record'))
        backend = sample.get('backend', {})
        if (not isinstance(backend, dict) or
                not all(_text(backend.get(key)) for key in ('entry_path', 'entrypoint', 'request_id'))):
            raise ValueError('Vision requires the actual backend processing entry and request identity')
        if backend['request_id'] in requests:
            raise ValueError('Vision requires distinct actual processing request identities')
        requests.add(backend['request_id'])
        entry = bound(backend['entry_path'])
        if implementation.get(backend['entry_path']) != digest(entry):
            raise ValueError('Vision backend entry is not in current implementation')
        output = sample.get('output', {})
        if (not isinstance(output, dict) or not _text(output.get('summary')) or
                output.get('input_sha256') != sample['input_sha256'] or
                output.get('request_id') != backend['request_id']):
            raise ValueError('Vision input/output identity and readable result required')
        actual_output = bound(output.get('path'))
        if output.get('sha256') != digest(actual_output):
            raise ValueError('Vision output changed')
        receipt = read_json(actual_output)
        no_target = (isinstance(receipt, dict) and receipt.get('status') == 'no_target'
                     and receipt.get('result') == [])
        if (not isinstance(receipt, dict) or receipt.get('input_sha256') != sample['input_sha256'] or
                receipt.get('request_id') != backend['request_id'] or
                receipt.get('run_id') != run['run_id'] or
                receipt.get('source_docx_sha256') != run['source_docx_sha256'] or
                (receipt.get('result') in (None, '', [], {}) and not no_target)):
            raise ValueError('Vision actual output must retain run/source/input/request identity and result')
        assertions = sample.get('assertions')
        if not isinstance(assertions, list) or not assertions or not all(isinstance(a, dict) for a in assertions):
            raise ValueError('Vision actual result comparison assertions required')
        for assertion in assertions:
            _assertion(assertion, bound, sample_id)
    if len(identities) < 2:
        raise ValueError('Vision requires at least two representative images with different decoded content')
    edges = vision.get('edge_cases')
    if not isinstance(edges, list) or not edges or not all(isinstance(e, dict) for e in edges):
        raise ValueError('Vision requires an actual failure or no-target check')
    for edge in edges:
        if edge.get('kind') not in {'failure', 'no_target'}:
            raise ValueError('Vision edge check must cover failure or no-target state')
        _assertion(edge, bound, 'vision edge case')
