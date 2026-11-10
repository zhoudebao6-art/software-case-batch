"""Parent-built short evidence IDs; checks coverage, never invents viewed IDs."""
import argparse
from copy import deepcopy
import json
from pathlib import Path
import re
from common import digest,inside,no_links,product_location,read_json,write_json

REVIEW_COVERAGE_POLICY = 'required-evidence-v1'


def review_coverage_policy(run):
    """Absent policies retain frozen contracts; explicit unknown versions fail."""
    policy = run.get('review_coverage_policy')
    from system_diagrams import POLICY as DIAGRAM_POLICY
    if run.get('system_diagram_policy') == DIAGRAM_POLICY and policy != REVIEW_COVERAGE_POLICY:
        raise ValueError('System diagram v2 requires the existing first-review coverage policy')
    if policy is not None and policy != REVIEW_COVERAGE_POLICY:
        raise ValueError('Unknown review coverage policy')
    return policy


def _relative(workspace, value):
    if not isinstance(value, str) or not value:
        raise ValueError('Actual review evidence path required')
    path = no_links(value) if Path(value).is_absolute() else inside(workspace, value, must_exist=False)
    if workspace not in path.parents:
        raise ValueError('Review evidence must stay inside this workspace')
    return path.relative_to(workspace).as_posix()


def _coverage_records(workspace, records, current, hash_file=None):
    if not isinstance(records, list) or not records:
        raise ValueError('Nonempty frozen review index required')
    by_path, ids, names = {}, set(), set()
    for row in records:
        if (not isinstance(row, dict) or not isinstance(row.get('id'), str) or not row['id']
                or row['id'] in ids or not isinstance(row.get('sha256'), str)
                or not re.fullmatch('[0-9a-f]{64}', row['sha256'])):
            raise ValueError('Unique review evidence IDs and actual SHA256 values required')
        rel = _relative(workspace, row.get('path'))
        if rel.casefold() in names:
            raise ValueError('Duplicate review evidence path')
        names.add(rel.casefold())
        if rel.casefold() == '.product-v2/model-dispatch.json':
            raise ValueError('Mutable model-dispatch.json is authenticated separately, not frozen reading evidence')
        if current and (hash_file or digest)(inside(workspace, rel)) != row['sha256']:
            raise ValueError('Review snapshot changed: ' + row['id'])
        by_path[rel] = row; ids.add(row['id'])
    return by_path


def _required_review_paths(workspace, run, scope, checks, artifacts, current=True, inherited=None, hashes=None):
    """Declared dependencies only; no directory scan, render or viewed claim."""
    from web_contract import web_module_policy
    module_policy = web_module_policy(run)
    if not isinstance(scope, dict):
        raise ValueError('Declare complete Word pages and source mappings in review_scope')
    required, technical = set(), set()
    package_revision = run.get('revision_scope') == 'package' and bool(run.get('revision_of'))
    document_revision = bool(run.get('revision_of')) and run.get('revision_scope', 'document') == 'document'

    def add(value, human=True):
        rel = _relative(workspace, value)
        (required if human else technical).add(rel)
        return rel

    if not package_revision:
        word = scope.get('word', {})
        pages = word.get('pages') if isinstance(word, dict) else None
        if (not isinstance(pages, list) or not pages or type(word.get('page_count')) is not int
                or word['page_count'] != len(pages) or not isinstance(word.get('sha256'), str)
                or not re.fullmatch('[0-9a-f]{64}', word['sha256'])
                or word['sha256'] != artifacts.get(run.get('word_name'))):
            raise ValueError('Word review scope must bind the current Word hash and complete ordered page count')
        page_paths = []
        for number, page in enumerate(pages, 1):
            if not isinstance(page, dict) or type(page.get('page')) is not int or page['page'] != number:
                raise ValueError('Word review pages must be numbered consecutively from 1 in reading order')
            page_paths.append(add(page.get('path')))
        if len({p.casefold() for p in page_paths}) != len(page_paths):
            raise ValueError('Word review pages must be distinct actual files')
        mappings = scope.get('source_mappings')
        if not isinstance(mappings, list) or not mappings or not all(isinstance(p, str) for p in mappings):
            raise ValueError('Declare actual source mapping evidence in review_scope.source_mappings')
        for path in mappings: add(path)
    elif not isinstance(inherited, list) or not inherited:
        raise ValueError('Package review must preserve its existing inherited_evidence_chain')

    for item in checks or []:
        if not isinstance(item, dict): raise ValueError('Actual execution check objects required')
        add(item.get('log'))
    if not current:
        if run.get('web_experience_policy') and not package_revision and not document_revision:
            from web_contract import WEB_EXPERIENCE_POLICY
            web = scope.get('web', {})
            if (run['web_experience_policy'] != WEB_EXPERIENCE_POLICY or
                    not isinstance(web, dict) or web.get('policy') != WEB_EXPERIENCE_POLICY or
                    not isinstance(web.get('evidence_hashes'), dict) or not web['evidence_hashes'] or
                    not web.get('page_ids') or not web.get('workflow_ids')):
                raise ValueError('Frozen review must preserve complete Web workflow evidence')
            if module_policy:
                modules,entries,screens=web.get('module_ids'),web.get('module_entry_assertions'),web.get('module_screenshots')
                from case_representation import POLICY as SOURCE_FORM_POLICY, minimum_modules
                minimum=minimum_modules(web.get('representation')) if module_policy==SOURCE_FORM_POLICY else 10
                if module_policy==SOURCE_FORM_POLICY:
                    from case_representation import validate_product_plan, PLAN_POLICY
                    rep=web['representation']
                    plan=validate_product_plan(rep,rep.get('runtime_validation'),run)
                    if run.get('product_plan_policy')==PLAN_POLICY:
                        for row in plan['technical_evidence']:
                            if not set(row['input_paths']+row['result_paths']+[row['source_ref']['path']])<=set(web['evidence_hashes']):
                                raise ValueError('Frozen technical materials must preserve their input/result/source hashes')
                if (web.get('web_module_policy')!=module_policy or web.get('minimum_business_modules')!=minimum
                        or not isinstance(modules,list) or len(modules)<minimum or len(set(modules))!=len(modules)
                        or not isinstance(entries,dict) or set(entries)!=set(modules)
                        or not all(isinstance(v,str) and v.strip() for v in entries.values())
                        or len(set(entries.values()))!=len(entries)
                        or not isinstance(screens,dict) or set(screens)!=set(modules)
                        or not all(isinstance(v,str) and v in web['evidence_hashes'] for v in screens.values())):
                    raise ValueError('Frozen review must preserve all ten-policy modules and their visible-entry assertion bindings')
            if run.get('web_outcome_policy'):
                from observed_outcomes import outcome_policy
                if web.get('web_outcome_policy') != outcome_policy(run) or set(web.get('core_outcomes', {})) != {'primary','changed_input','recovery'}:
                    raise ValueError('Frozen review must preserve its core outcome bindings')
            add('.product-v2/build-checks.json')
            for path in web['evidence_hashes']: add(path)
        if not package_revision and not document_revision:
            video = scope.get('video', {})
            if not isinstance(video, dict) or not isinstance(video.get('timeline'), dict):
                raise ValueError('Frozen first review must preserve its complete video reading scope')
            add(video['timeline'].get('path'))
            for group in ('contact_sheets', 'endpoints', 'interaction_frames'):
                rows = video.get(group)
                if not isinstance(rows, list) or not rows or not all(isinstance(row, dict) for row in rows):
                    raise ValueError('Frozen first review lacks required video scope: ' + group)
                if group == 'endpoints' and {row.get('type') for row in rows} != {'first', 'last'}:
                    raise ValueError('Frozen first review requires both video endpoints')
                for row in rows: add(row.get('path'))
        return required, technical

    def document(name, optional=False):
        path = inside(workspace, '.product-v2/' + name, must_exist=False)
        if optional and not path.exists(): return {}
        add(str(path)); value = read_json(path)
        if not isinstance(value, dict): raise ValueError('Review dependency must be a JSON object: ' + name)
        return value

    document('run.json')
    charts = document('chart-manifest.json')
    for figure in charts.get('figures', []) + charts.get('retained_results', []): add(figure.get('png'), not package_revision)
    # The dedicated revision gates already require byte-identical inherited
    # system artifacts. A Word-only revision does not create fresh software or
    # video-reading obligations in the new workspace.
    if document_revision:
        return required, technical - required
    package = document('source-package.json')
    members = package.get('files')
    if not isinstance(members, dict) or not members: raise ValueError('Current source package members required')
    from runtime_cache import evidence_path
    for path in members: add(evidence_path(workspace,run,package,path).relative_to(workspace).as_posix())
    if package_revision:
        return required, technical - required
    controlled = document('controlled-video.json')
    timeline_path = add(controlled.get('timeline'))
    timeline = read_json(inside(workspace, timeline_path))
    timeline_sha = hashes[timeline_path] if hashes is not None and timeline_path in hashes else digest(inside(workspace, timeline_path))
    if timeline_sha != controlled.get('sha256'):
        raise ValueError('Controlled review timeline changed')
    for group in ('frames', 'contact_sheets', 'interaction_frames'):
        rows = timeline.get(group)
        if not isinstance(rows, list) or not rows: raise ValueError('Complete declared review timeline required: ' + group)
        for row in rows:
            if not isinstance(row, dict): raise ValueError('Actual review timeline item required')
            human = not package_revision and (group != 'frames' or row.get('type') in {'first', 'last'})
            add(row.get('file'), human)
    # This is the existing timeline's small visual navigation, frozen inside
    # the same index. It is generated, never another reviewer-written ledger.
    def visual_row(row):
        return {'path': _relative(workspace, row['file']), 'sha256': row['sha256'],
                **({'type': row['type']} if row.get('type') in {'first', 'last'} else {})}
    scope['video'] = {'timeline': {'path': timeline_path, 'sha256': controlled['sha256']},
                      'contact_sheets': [visual_row(row) for row in timeline['contact_sheets']],
                      'endpoints': [visual_row(row) for row in timeline['frames'] if row.get('type') in {'first', 'last'}],
                      'interaction_frames': [visual_row(row) for row in timeline['interaction_frames']]}
    if {row.get('type') for row in scope['video']['endpoints']} != {'first', 'last'}:
        raise ValueError('Complete first and last video frame declarations required')
    for name in ('recording.json', 'data-cleaning.json', 'data-quality.json', 'data-provenance.json', 'cleanup.json', 'build-checks.json'):
        value = document(name, optional=True)
        if name == 'build-checks.json':
            if run.get('web_experience_policy'):
                from web_contract import validate_web_experience
                web = validate_web_experience(workspace, run, value)
                scope['web'] = {key: web[key] for key in
                                ('policy', 'system_types', 'page_ids', 'workflow_ids', 'evidence_hashes')}
                if module_policy:
                    scope['web'].update({key:web[key] for key in
                        ('module_ids','web_module_policy','minimum_business_modules',
                         'module_entry_assertions','module_screenshots')})
                if module_policy=='source-form-v1':scope['web']['representation']=web['representation']
                if run.get('web_outcome_policy'):
                    scope['web'].update({key:web[key] for key in ('web_outcome_policy','core_outcomes')})
                for path in web['evidence_paths']: add(path)
            for check in value.get('checks', {}).values():
                add(check.get('log'))
                for path in check.get('input_files', {}): add(path)
    return required, technical - required


def review_coverage_snapshot(workspace, run, records, scope, checks=None, required_paths=None,
                             artifacts=None, inherited=None, _hash_file=None):
    """Freeze existing request facts; never add reviewed IDs or an approval."""
    if review_coverage_policy(run) is None: return {}
    workspace = no_links(workspace)
    from common import file_map
    artifacts = file_map(product_location(workspace, run)) if artifacts is None else artifacts
    indexed = _coverage_records(workspace, records, True, _hash_file)
    if scope is None and run.get('revision_scope') == 'package' and run.get('revision_of'):
        scope = {}  # No new visual declaration for inherited package revisions.
    scope = deepcopy(scope)
    required, technical = _required_review_paths(workspace, run, scope, checks, artifacts, inherited=inherited,
                                                hashes={path: row['sha256'] for path, row in indexed.items()})
    from system_diagrams import required_review_paths
    required |= required_review_paths(run, artifacts, indexed)
    declared = {_relative(workspace, p) for p in (required_paths or [])}
    declared.discard('.product-v2/model-dispatch.json')
    missing = (required | technical | declared) - set(indexed)
    if missing: raise ValueError('Review index omits declared required evidence: ' + ', '.join(sorted(missing)))
    required |= declared - technical
    return {'review_coverage_policy': REVIEW_COVERAGE_POLICY, 'run_id': run['run_id'],
            'source_docx_sha256': run.get('source_docx_sha256'), 'current_artifacts': artifacts,
            'review_scope': scope, 'required_evidence': sorted(indexed[p]['id'] for p in required),
            **({'inherited_evidence_chain': inherited} if inherited is not None else {})}


def _known_frozen_bindings(workspace, run, proof, spec, indexed, required):
    """Check signed known snapshots without opening any original mutable file."""
    package_revision = run.get('revision_scope') == 'package' and bool(run.get('revision_of'))
    document_revision = bool(run.get('revision_of')) and run.get('revision_scope', 'document') == 'document'
    from system_diagrams import required_review_paths
    required_review_paths(run, spec['current_artifacts'], indexed, required)
    def require_hash(sha, path=None, human=True):
        rows = ([indexed.get(_relative(workspace, path))] if path is not None else
                [row for row in indexed.values() if row['sha256'] == sha])
        if (not isinstance(sha, str) or not re.fullmatch('[0-9a-f]{64}', sha)
                or not any(row and row['sha256'] == sha and (not human or row['id'] in required) for row in rows)):
            raise ValueError('Frozen review omits known required source/chart/video evidence')
    if run.get('web_experience_policy') and not package_revision and not document_revision:
        scope = spec.get('review_scope', {})
        web = scope.get('web', {}) if isinstance(scope, dict) else {}
        if not isinstance(web, dict) or not isinstance(web.get('evidence_hashes'), dict) or not web['evidence_hashes']:
            raise ValueError('Frozen review requires bound Web evidence')
        for path, sha in web['evidence_hashes'].items(): require_hash(sha, path)
    charts = proof.get('chart_snapshot', {})
    if not isinstance(charts, dict) or not charts:
        raise ValueError('Frozen review must preserve its existing chart_snapshot')
    figures, retained = charts.get('figures'), charts.get('retained_results', {})
    if not isinstance(figures, dict) or not figures or not isinstance(retained, dict):
        raise ValueError('Frozen review chart snapshot requires its current figure hashes')
    require_hash(charts.get('manifest_sha256'), '.product-v2/chart-manifest.json')
    for sha in list(figures.values()) + list(retained.values()):
        require_hash(sha, human=not package_revision)
    if not document_revision:
        package = proof.get('source_package', {})
        if not isinstance(package, dict) or not isinstance(package.get('files'), dict) or not package['files']:
            raise ValueError('Frozen review must preserve the existing source_package member snapshot')
        for path, sha in package['files'].items(): require_hash(sha, path)
    if not package_revision and not document_revision:
        scope = spec.get('review_scope')
        if not isinstance(scope, dict): raise ValueError('Frozen review scope required')
        video = scope.get('video', {})
        if not isinstance(video, dict) or not isinstance(video.get('timeline'), dict):
            raise ValueError('Frozen first review video scope required')
        timeline = video.get('timeline', {})
        if timeline.get('sha256') != proof.get('video_timeline_sha256'):
            raise ValueError('Frozen first review video timeline differs from the signed proof')
        rows = [timeline]
        for group in ('contact_sheets', 'endpoints', 'interaction_frames'):
            group_rows = video.get(group)
            if not isinstance(group_rows, list) or not group_rows or not all(isinstance(row, dict) for row in group_rows):
                raise ValueError('Frozen first review complete video scope required')
            rows.extend(group_rows)
        for row in rows:
            require_hash(row.get('sha256'), row.get('path'))


def validate_review_coverage(workspace, run, proof, review_record, current=True):
    """Authenticate a reviewer's coverage claim, never infer actual perception.

    Saved first reviews/status use current=False: their signed index remains
    frozen while the original source tree may legitimately have been repaired.
    """
    if review_coverage_policy(run) is None:
        return {'required': False, 'status': 'historical-contract'}
    workspace = no_links(workspace)
    reference = proof.get('review_index')
    if (not isinstance(reference, dict) or not isinstance(review_record, dict)
            or reference != review_record.get('review_index')):
        raise ValueError('Proof and actual review stage must bind the same frozen review_index')
    rel = _relative(workspace, reference.get('path')); index = inside(workspace, rel)
    if digest(index) != reference.get('sha256'): raise ValueError('Frozen review index changed')
    spec = read_json(index)
    if (not isinstance(spec, dict) or spec.get('review_coverage_policy') != REVIEW_COVERAGE_POLICY
            or spec.get('workspace') != str(workspace) or spec.get('run_id') != run.get('run_id')
            or spec.get('source_docx_sha256') != run.get('source_docx_sha256')
            or not isinstance(spec.get('review_id'), str) or not spec['review_id']
            or proof.get('review_id') != spec['review_id']
            or not isinstance(spec.get('current_artifacts'), dict) or not spec['current_artifacts']
            or spec['current_artifacts'] != proof.get('reviewed_files')):
        raise ValueError('Frozen review index must bind this run, review ID and reviewed artifact snapshot')
    # Structure is checked here. The current branch hashes the index exactly
    # once in review_coverage_snapshot; historical bindings never hash old files.
    indexed = _coverage_records(workspace, spec.get('evidence'), False)
    required = spec.get('required_evidence')
    ids = {row['id'] for row in indexed.values()}
    if (not isinstance(required, list) or not required or not all(isinstance(i, str) for i in required)
            or len(required) != len(set(required)) or not set(required).issubset(ids)):
        raise ValueError('Frozen nonempty required review evidence IDs required')
    reviewed = proof.get('reviewed_evidence')
    if (not isinstance(reviewed, list) or not all(isinstance(i, str) for i in reviewed)
            or len(reviewed) != len(set(reviewed)) or not set(reviewed).issubset(ids)
            or not set(required).issubset(reviewed)):
        raise ValueError('Reviewer must report actual complete required evidence coverage, without unknown IDs')
    _known_frozen_bindings(workspace, run, proof, spec, indexed, set(required))
    if current:
        from common import file_map
        if file_map(product_location(workspace, run)) != spec['current_artifacts']:
            raise ValueError('Review artifact snapshot changed')
        expected = review_coverage_snapshot(workspace, run, spec['evidence'], spec.get('review_scope'),
                                            proof.get('checks'), artifacts=spec['current_artifacts'],
                                            inherited=proof.get('inherited_evidence_chain'))
        if not set(expected['required_evidence']).issubset(required):
            raise ValueError('Frozen required evidence omits a current declared reading dependency')
        if expected['review_scope'] != spec.get('review_scope'):
            raise ValueError('Frozen review scope differs from its current complete video declaration')
        if run.get('revision_scope') == 'package' and run.get('revision_of'):
            chain = proof.get('inherited_evidence_chain')
            if chain != spec.get('inherited_evidence_chain'):
                raise ValueError('Package review index must bind its existing inheritance chain')
            _inherited_review_coverage(workspace, run, chain)
    else:
        mandatory, _ = _required_review_paths(workspace, run, spec.get('review_scope'), proof.get('checks'),
                                               spec['current_artifacts'], False, spec.get('inherited_evidence_chain'))
        if not mandatory.issubset(indexed) or not {indexed[p]['id'] for p in mandatory}.issubset(required):
            raise ValueError('Frozen required evidence omits its declared Word/source/log scope')
    return {'required': True, 'status': 'bound-reviewer-coverage', 'review_index': reference,
            'review_id': spec['review_id'], 'required_evidence': required,
            'note': 'Authenticated independent coverage claim only; IDs and hashes do not prove actual viewing.'}


def _inherited_review_coverage(workspace, run, chain):
    """Read the already frozen parent proof; never reopen its old source tree."""
    if (not isinstance(chain, list) or not chain or not isinstance(chain[0], dict)
            or chain[0].get('workspace') != run['revision_of'].get('workspace')):
        raise ValueError('Package review requires its explicit finalized parent chain')
    for entry in chain:
        if not isinstance(entry, dict): raise ValueError('Actual inherited review reference required')
        parent = no_links(entry.get('workspace', ''))
        receipt_path = inside(parent, '.product-v2/final-receipt.json')
        receipt = read_json(receipt_path)
        if digest(receipt_path) != entry.get('receipt_sha256'):
            raise ValueError('Inherited review receipt changed')
        proof_path = no_links(receipt['execution_evidence']) if Path(receipt['execution_evidence']).is_absolute() else inside(parent, receipt['execution_evidence'])
        if (parent not in proof_path.parents or digest(proof_path) != entry.get('proof_sha256')
                or receipt.get('evidence_sha256') != entry.get('proof_sha256')):
            raise ValueError('Inherited independent review proof changed')
        previous_run = read_json(inside(parent, '.product-v2/run.json'))
        if previous_run.get('revision_scope') == 'package': continue
        previous_proof = read_json(proof_path)
        previous_stage = read_json(inside(parent, '.product-v2/model-dispatch.json')).get('stages', {}).get('review', {})
        validate_review_coverage(parent, previous_run, previous_proof, previous_stage, current=False)
        return
    raise ValueError('Package revision lacks its original frozen visual review')

def create(workspace,manifest,destination):
    workspace=no_links(workspace);spec=read_json(manifest);files=spec.get('files',[])
    if not files or len(set(files))!=len(files):raise ValueError('Unique actual evidence list required')
    records=[{'id':'E'+str(i+1).zfill(3),'path':rel,'sha256':digest(inside(workspace,rel))} for i,rel in enumerate(files)]
    value={'schema_version':1,'review_id':__import__('uuid').uuid4().hex[:12],'workspace':str(workspace),'evidence':records}
    if 'review_scope' in spec:value['review_scope']=spec['review_scope']
    run_path=workspace/'.product-v2/run.json'
    if run_path.exists():
        run=read_json(run_path)
        if review_coverage_policy(run):
            value.update(review_coverage_snapshot(workspace,run,records,spec.get('review_scope'),
                                                 spec.get('checks'),inherited=spec.get('inherited_evidence_chain')))
    write_json(destination,value);return value

def check(index,ids,workspace=None):
    spec=read_json(index);evidence=spec['evidence'];known={r['id'] for r in evidence}
    if not evidence:raise ValueError('Nonempty actual evidence index required')
    if len(known)!=len(evidence) or len(ids)!=len(set(ids)):raise ValueError('Duplicate requested or reviewed ID')
    expected=known
    if review_coverage_policy(spec):
        required=spec.get('required_evidence')
        if (not isinstance(required,list) or not required or not all(isinstance(i,str) for i in required)
                or len(required)!=len(set(required)) or not set(required).issubset(known)):
            raise ValueError('Frozen required evidence IDs must be nonempty, unique and known')
        expected=set(required)
    if workspace:
        root=no_links(workspace)
        if str(root)!=spec['workspace']:raise ValueError('Evidence index workspace differs')
        for record in evidence:
            if digest(inside(root,record['path']))!=record['sha256']:raise ValueError('Review snapshot changed: '+record['id'])
    actual=set(ids);return {'complete':expected.issubset(actual) and not actual-known,'missing':sorted(expected-actual),'unknown':sorted(actual-known),
        'note':'IDs must come from actual review or legal unchanged prior review. This command never signs or adds IDs.'}

def index_summary(index, spec=None):
    """Short directory for model input; all evidence remains in the full index."""
    index=no_links(index);spec=read_json(index) if spec is None else spec
    kinds={}
    for row in spec['evidence']:
        extension=Path(row['path']).suffix.lower() or '(no extension)'
        kinds[extension]=kinds.get(extension,0)+1
    return {'kind':'neutral-evidence-directory','path':str(index),'sha256':digest(index),
            'evidence_items':len(spec['evidence']),'by_extension':dict(sorted(kinds.items())),
            'coverage_claim':False,
            'instruction':'Read the referenced complete index in bounded chunks as needed. Every required item still needs actual review or separately authenticated legal prior review. Counts and unchanged hashes never establish viewed coverage; first Word/video review remains complete.'}


def review_input(workspace,index,destination,compact=False):
    """Current neutral bindings; no decision, viewed IDs or reviewer signature."""
    workspace=no_links(workspace)
    spec=read_json(index)
    from common import file_map
    run=read_json(inside(workspace,'.product-v2/run.json'))
    if run.get('workspace') and run['workspace']!=str(workspace):raise ValueError('Review run workspace identity differs')
    output=product_location(workspace,run)
    if not output.is_dir():raise ValueError('Current product output is missing; do not produce empty review facts')
    artifacts=file_map(output)
    if not artifacts:raise ValueError('Current product output is empty; do not request independent product review')
    coverage_policy=review_coverage_policy(run)
    if not coverage_policy:check(index,[],workspace)
    verified_hashes={}
    if coverage_policy:
        expected=review_coverage_snapshot(workspace,run,spec['evidence'],spec.get('review_scope'),
                                         artifacts=artifacts,inherited=spec.get('inherited_evidence_chain'))
        if (any(spec.get(key)!=expected.get(key) for key in ('review_coverage_policy','run_id','source_docx_sha256','current_artifacts','review_scope'))
                or not set(expected['required_evidence']).issubset(spec.get('required_evidence',[]))):
            raise ValueError('Review facts require the complete frozen current index scope')
        verified_hashes={_relative(workspace,row['path']):row['sha256'] for row in spec['evidence']}
    def current_hash(path):
        rel=_relative(workspace,str(path))
        return verified_hashes[rel] if rel in verified_hashes else digest(path)
    from contracts import chart_policy,chart_records
    policy=chart_policy(run)
    manifest=inside(workspace,'.product-v2/chart-manifest.json');charts=read_json(manifest)
    figures=chart_records(charts,run) if policy is not None else charts['figures']
    for figure in figures:
        if current_hash(inside(workspace,figure['png']))!=figure['sha256']:raise ValueError('Chart input changed')
    facts={'schema_version':1,'kind':'review-input-facts','workspace':str(workspace),
           'run_id':run['run_id'],'index':{'path':str(no_links(index)),'sha256':digest(index)},
           'current_artifacts':artifacts,
           'current_charts':{'manifest_sha256':digest(manifest),'figures':{str(f['figure_id']):f['sha256'] for f in charts['figures']}},
           'instruction':'Reviewer must inspect the required evidence and write independent conclusions, actual reviewed IDs and final proof hash. These bindings are not a review.'}
    if coverage_policy:
        facts.update(review_index=facts['index'],review_id=spec['review_id'],
                     required_evidence=spec['required_evidence'],review_scope=spec['review_scope'])
    from review_packet import current_admitted_metadata
    facts.update(current_admitted_metadata(workspace))
    if compact:facts['evidence_directory']=index_summary(index,spec)
    else:facts['evidence']=spec['evidence']
    facts['review_sequence']={'first':'Use the actual source mappings and algorithm/API/persistence evidence to check applicable acceptance/rejection boundaries and final-engine derived results in references/system-data.md before expensive visual coverage.',
        'on_blocking_defect':'Collect all reproducible material defects in this review. Continue independent checks and the complete first visual reading of stable Word/video even if code needs repair. Stop only checks made impossible or invalid by that actual dependency; disclose exactly what remains unread and why. Never invent coverage or add a whole-case review for minor fixes.',
        'issue_triage':'In this same first review distinguish core delivery blockers from nonblocking advice using the actual source and explicit requirements. Do not request optional enhancements. State concrete impact and affected artifacts in existing issues; keep harmless style/future-feature advice in internal notes. Optional added functionality may be disabled/removed only when source requirements, explicit functions and the frozen delivery contract remain satisfied; check actual entry points and backend actions rather than hiding a failing action. Core computation/source mismatches, startup/export failures, damaged/missing deliverables and required unread/failed checks remain blockers. Never relabel those as advice.',
        'after_first_review':'Preserve the first issue IDs, severity, unread scope and revise decision. Existing resolutions may record accepted_nonblocking with a source/scope reason for advice needing no change, removed for actual optional-function removal, or resolved for a fix. An unchanged advice-only closure reuses exact successful first checks and the existing owner/authorization, without a new repair agent. Removal/fixes use the original repairer and only real affected browser/API/backend and current package-startup checks, then close-simplified; do not add whole-case review, forms, or redo unchanged Word/data/video. Keep diagnoses/history internal and never call simplified closure an independent pass.',
        'for_pass':'Complete the full required source, document, chart, UI and video review; no visual scope or independent role is reduced. A video already actually reviewed and accepted may inherit its original viewed conclusion while its final media and technical evidence remain unchanged; later minor code, data or copy edits do not require another video review. A video never actually accepted still requires the complete first review.'}
    revision = run.get('revision_scope', 'document') if coverage_policy and run.get('revision_of') else None
    if revision == 'document':
        facts['review_sequence']['first']='Check current source mappings, changed Word context and every declared rendered Word page; preserve the dedicated revision gate\'s unchanged inherited system evidence.'
        facts['review_sequence']['for_pass']='Review the complete current Word/chart/context scope. Unchanged previously accepted software, data and video retain their authenticated original conclusions; this revision creates no new whole-system or video reading stage.'
    elif revision == 'package':
        facts['review_sequence']['first']='Check the current source archive, startup evidence and existing inherited_evidence_chain. Authenticate unchanged prior visual conclusions without inventing a new viewing claim.'
        facts['review_sequence']['for_pass']='Review the current package changes and startup facts. Inherit the unchanged Word/chart/data/video conclusions through the existing finalized chain; do not repeat their first visual review.'
    from source_delivery import main_code_only, retain_all_source
    if main_code_only(run):
        sequence=facts['review_sequence']
        sequence['after_first_review']=sequence['after_first_review'].replace('current package-startup checks','current package member/hash checks')
        sequence['issue_triage']=sequence['issue_triage'].replace('startup/export failures','working-system startup/export failures')
        if revision == 'package':
            sequence['first']='Check current complete main source members/hashes and existing inherited_evidence_chain; no package unpack/install/startup check. Authenticate unchanged prior visual conclusions without a new viewing claim.'
            sequence['for_pass']='Review current package changes and complete main code coverage. Inherit unchanged working-system execution and Word/chart/data/video conclusions through the finalized chain; do not repeat their first review.'
        elif revision is None:
            sequence['first']+=' Inspect actual packaged main algorithm/backend modules against the existing source mappings and working system: full functions/classes, data processing, validation, persistence and applicable query/export paths; excerpts, missing core logic or filler are not sufficient. Do not unpack/install/start this code package or impose a line-count quota.'
    if retain_all_source(run):
        facts['review_sequence']['first']+=' Compare the full declared project trees and loose files to exported members; only identified production/private/runtime exclusions are allowed. Preserve tests, assets, configs and existing scripts. No new review stage or startup test.'
    from source_delivery import retain_runtime_cache
    if retain_runtime_cache(run) and revision != 'document':
        facts['review_sequence']['first'] += ' Case-owned runtime results/caches are retained delivery data. Check source-package runtime_cache_files and SQLite snapshot hashes/time against actual members; credentials, private sessions and machine dependencies stay out. Mutable cache state is not code coverage: fixed calculation inputs remain dependency-bound.'
        if revision is None:
            facts['review_sequence']['first'] += ' Inspect the source-specific continuous state transitions, partial feedback and repeat/recovery behavior in existing execution assertions, not just a successful initial page.'
    if policy is not None:
        facts['current_charts']['chart_policy']=policy
        facts['chart_review_requirements']={'every_current_png':True,
            'quality_evidence':['meaning','data','legibility','layout','explanation'],
            'visual_evidence':['no_title_header_evidence','no_schematic_evidence'],
            'instruction':'Open every current PNG and Word context; verify no 示意 and no title/header. Explain source-relative value in meaning and before/red explanation/after context in explanation. Declared captions/labels are not pixel OCR.'}
        if revision == 'package':
            facts['chart_review_requirements'].update(every_current_png=False,
                instruction='Authenticate the unchanged chart hashes and their existing signed visual conclusions through inherited_evidence_chain; these pointers do not require fresh visual reading.')
    if run.get('explanation_context_policy') and revision != 'package':
        from contracts import chart_snapshot
        snapshot=chart_snapshot(workspace,output/run['word_name'],run)
        facts['current_charts'].update({
            key:snapshot[key] for key in ('explanation_context_policy','explanation_contexts')})
        facts['chart_review_requirements']['context_instruction']=(
            'These anchors only prove structural placement. Read the actual original example, '
            'preceding prose, inserted explanation and following prose. Confirm the same object, '
            'conditions, formula and results in each explanation judgment. Explanations collected '
            'in an unrelated tail section are a material document defect, not a cosmetic suggestion. '
            'Compare every added formula with the source: a complete copied source equation is also '
            'a material document defect even when placed correctly and colored red. Preserve all '
            'original equations and their existing repeats; symbol references and genuinely distinct '
            'grounded derivations are not full-formula copies. The native structure check is not '
            'algebraic equivalence or OCR; actually inspect text/image formulas and redundant prose.')
        if run.get('explanation_fact_policy'):
            facts['current_charts'].update({key:snapshot[key] for key in
                ('explanation_fact_policy','explanation_key_facts')})
            facts['chart_review_requirements']['key_fact_instruction']=(
                'Within this same first review, compare every actual chart with its key_facts '
                'and the located explanation blocks. Independently find omitted meaningful '
                'annotations, turning points, extrema, thresholds, start/end conditions and '
                'events; declarations and exact excerpt matches do not prove completeness. '
                'Also check symbols both ways: prose-to-figure and figure-to-prose, point versus '
                'vector versus matrix, basis directions, origins, projections, start/end coordinates, '
                'units, weights and panel/example identity. A matrix is not a point; its columns '
                'may be depicted as basis vectors. Do not mix numeric examples between panels. '
                'A symbol mentioned only in prose does not prove that the figure depicts its relation. '
                'Check the cited source/data locator, value, time reference, unit, object, '
                'conditions and cause/result together, including before/after prose. '
                'Continuous samples and automatic ticks need not be transcribed point by point. '
                'Explain this actual comparison in each existing chart_reviews.explanation '
                'judgment; a missing or inconsistent necessary explanation is a material '
                'document defect. No new review stage or semantic pass is created by the script.')
            if run.get('explanation_fact_policy') == 'key-facts-v2':
                facts['chart_review_requirements']['correspondence_instruction'] = (
                    'Use existing chart_reviews.explanation.checked_fact_ids for all actually checked '
                    'key facts and existing evidence for concrete observed correspondences or defects. '
                    'Inspect the current PNG and Word, not just the declared depiction. Independently '
                    'find missing labels/relations/definitions even when omitted from key_facts. '
                    'Do not add another review round or prefill checked IDs from the manifest.')
            facts['chart_review_requirements']['explanation_reading_order'] = [
                'Read each actual PNG first: axes/time reference/units, every meaningful series/region/legend/color scale, annotation and event. Cross-check declarations; an omitted declaration must not hide an omitted explanation.',
                'Read its own original embodiment before/explanation/after: same object, conditions, baseline, meaningful values/intervals, grounded cause or explicitly limited inference, conclusion and next-step use. Explain ordinary ticks/samples by range and trend, not point-by-point transcription.',
                'For relevant source formulas, inspect native inline symbols in the rendered Word: original subscripts/superscripts/accents/Greek letters, index meaning and units, and which plotted quantity/series/region they represent. Describe the observed change and applicable conditions; never copy the full equation or invent a formula for a formula-free figure.',
                'During the same reading, flag generic warning/production-use endings for targeted removal by the author, not manual user cleanup. The original author also cleans the final exported Word before packaging; bind the actual final bytes, preserve source text and check only affected content for wording fixes. End with the embodiment-specific conclusion. Keep original text and necessary technical conditions/uncertainty integrated accurately; never relabel computation as measurement. Do not delete the last sentence mechanically or start another review round.',
                'Record the actual graph-to-prose comparison and any missing item in the existing chart_reviews.explanation evidence. No separate checklist file, new review round, automatic semantic pass or repeat reading of unchanged accepted artifacts.'
            ]
    controlled=workspace/'.product-v2/controlled-video.json'
    use_controlled=controlled.exists() and revision is None
    if use_controlled:
        media=read_json(controlled);timeline=no_links(media['timeline'])
        if workspace not in timeline.parents or current_hash(timeline)!=media['sha256']:raise ValueError('Current controlled timeline changed')
        facts['current_video_timeline']={'path':str(timeline),'sha256':current_hash(timeline)}
    # Direct navigation only: do not duplicate hundreds of uniform frames or
    # mark a single evidence ID read. The complete index remains authoritative.
    indexed={str(inside(workspace,row['path'])):row for row in spec['evidence']}
    def reference(path,sha,**extra):
        path=no_links(path) if Path(path).is_absolute() else inside(workspace,path)
        if workspace not in path.parents:raise ValueError('Visual navigation must stay in this workspace')
        row=indexed.get(str(path))
        if (row['sha256'] if row else digest(path))!=sha:raise ValueError('Visual navigation input changed: '+str(path))
        result={'path':str(path),'sha256':sha,**extra}
        if row:result['evidence_id']=row['id']
        return result
    navigation={'coverage_claim':False,
        'instruction':'Open these actual files; a link or hash is not a viewed item. Read every Word page from the full index, all video contact sheets and required full-resolution endpoint/interaction frames; inspect other full-resolution frames where needed. Keep all original evidence and report actual reviewed IDs only.',
        'charts':[reference(f['png'],f['sha256'],figure_id=f['figure_id']) for f in figures]}
    if revision:
        navigation['instruction']='Inspect the current revision scope and authenticate the unchanged inherited system/visual conclusions through the existing finalized chain. Navigation pointers never establish a fresh viewed claim.'
    if use_controlled:
        report=read_json(timeline)
        navigation['video']={group:[reference(item['file'],item['sha256']) for item in report.get(group,[])]
                             for group in ('contact_sheets','interaction_frames')}
        navigation['video']['endpoints']=[reference(item['file'],item['sha256'],type=item['type'])
                                         for item in report.get('frames',[]) if item.get('type') in {'first','last'}]
    if run.get('web_experience_policy') and not revision:
        web = spec['review_scope']['web']
        facts['web_review_requirements'] = {
            'policy': web['policy'], 'page_ids': web['page_ids'], 'workflow_ids': web['workflow_ids'],
            'instruction': 'Read every business page screenshot and actual task assertion with its original-source mapping and implementation. Check complete case-specific tasks, navigation, input-to-backend-to-result/persistence/export and suitable system form. For vision, inspect real input images, licensing/provenance and actual backend results; reject decoration, prepainted labels or fixed outputs masquerading as recognition. A declared task list, page count, hashes and structural success do not establish semantic completeness. Compare the actual core page with the builder\'s stated primary object, operator task and simultaneous information needs. In the existing review findings identify the page/region and trace one concrete object -> simultaneous information -> action -> observable result from the builder scene, using the supplied pages.screenshot and workflow/assertion evidence. Verify that the main work area, adjacent information and interaction serve the source-specific task; screenshots establish spatial organization, not backend correctness, and assertions alone do not establish readable layout. Generic praise or a palette change is not evidence. Missing required relationships/actions or an obstructive layout is material; a familiar layout serving the same work is valid. Do not choose a template from title keywords, demand novel components, or impose new fields, screenshot counts, reports or evidence files. If same-batch screenshots are already supplied, compare task structure rather than counting different colors; do not fetch old cases or require comparison artifacts. Review visible copy in the supplied core/detail/empty/error-state evidence: persistent text should help identify an object, enter a value, interpret a result or recover an action. Remove purposeless welcome banners, capability marketing, repeated title explanations and algorithm-introduction walls during construction; use concrete action labels and contextual state messages. Put low-frequency definitions in accessible on-demand help, but keep decision-critical conditions, units, data nature, risks and blocking reasons visible beside the affected input/result. Do not impose a word quota, blacklist, new screenshot/evidence field or review round; do not reduce Word figure explanations. Extra prose alone is nonblocking unless it obstructs work or misleads. Judge information depth from real objects, task queues, domain views, exceptions, history and comparison where source-supported, not whitespace filled by decorative cards or repeated copies of one result. Trace selection and filtering through related views and meaningful backend changes; examine secondary modules as well as the home page. Inspect primary/changed-input/recovery observations in the existing browser report when the run freezes observed-outcomes-v1: typed equality is only an evidence consistency check, not proof of execution or semantic correctness. Check screenshot density, hierarchy, type scale and legibility at normal zoom; use the supplied interaction/video evidence to inspect real motion, interruption and reduced-motion behavior. Rich animation must connect actual state changes, never fake progress or live data. Inspect the source along a real UI action -> API validation -> domain computation -> transaction/query -> rendered result, including a source-specific invariant and failure recovery. Readable responsibility separation, bounded data access, disposal and stable identities matter; line counts, framework choice and file counts are not quality scores. Keep this in the same first review and classify only material defects as blocking. Ten modules need not be ten identical pages. Do not fail a useful sidebar, table or card merely for its component type. Report material usability/content defects together; cosmetic preferences remain nonblocking, with only affected checks after a fix. Include all material findings in the existing independent review, no extra design review stage.'}
        if run.get('web_outcome_policy'):
            facts['web_review_requirements'].update({key:web[key] for key in ('web_outcome_policy','core_outcomes')})
        if run.get('web_module_policy'):
            from web_contract import web_module_policy
            facts['web_review_requirements'].update(
                web_module_policy=web_module_policy(run),
                minimum_business_modules=web['minimum_business_modules'],
                module_ids=web['module_ids'],
                module_entry_assertions=web['module_entry_assertions'],
                module_screenshots=web['module_screenshots'],
                module_instruction='In the same first review inspect all declared modules against their source-selected minimum and complete source requirements, with no upper limit: each has an actual visible entry, independent business purpose and real tested action. Reject empty pages, statistical cards and renamed/repeated pages/actions used as modules. Read all module screenshots and assertions even when the continuous core-workflow video does not visit every module; preserve the original video duration and quality contract, without a new review stage.')
        if run.get('web_module_policy')=='source-form-v1':
            facts['web_review_requirements']['representation']=web['representation']
            facts['web_review_requirements']['form_instruction']='Compare the source-selected software form and original paragraphs with actual runtime logs, implementation and screenshots. A validation console is not a native product UI. A browser phone frame is not a native App/mini-program. Read all technical figures for their actual feature, depiction and source, not appearance similarity. Do this in the same first review; structural validation alone does not certify authenticity or technical relevance.'
        navigation['web'] = [reference(path, sha) for path, sha in web['evidence_hashes'].items()
                             if Path(path).suffix.lower() in {'.png', '.jpg', '.jpeg', '.webp', '.bmp', '.tif', '.tiff'}]
    facts['visual_navigation']=navigation
    destination=no_links(destination)
    if workspace not in destination.parents or destination.exists():raise ValueError('Use a new internal facts path; do not overwrite any review')
    write_json(destination,facts);return {'facts':str(destination),'sha256':digest(destination),'evidence_items':len(spec['evidence'])}

if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('action',choices=['create','check','review-input']);p.add_argument('--workspace');p.add_argument('--manifest');p.add_argument('--index',required=True);p.add_argument('--output');p.add_argument('--compact',action='store_true');p.add_argument('--ids',nargs='*',default=[]);a=p.parse_args()
    try:
        result=create(a.workspace,a.manifest,a.index) if a.action=='create' else (review_input(a.workspace,a.index,a.output,a.compact) if a.action=='review-input' else check(a.index,a.ids,a.workspace))
        print(json.dumps(result,ensure_ascii=False,indent=2));raise SystemExit(0 if result.get('complete',True) else 2)
    except (OSError,ValueError,KeyError) as e:print('ERROR: '+str(e));raise SystemExit(2)
