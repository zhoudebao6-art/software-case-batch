"""Optional read-only reviewer preparation; never runs tests, views evidence or signs pass.

check prints structured errors without writing. draft writes only a new explicit
private directory. Existing evidence indexes retain their IDs; automatic discovery
is limited to current receipts and declared dependencies, never a workspace scan.
"""
import argparse
import hashlib
import json
from pathlib import Path
import re
import zipfile

from common import digest, inside, no_links, product_location, read_json
from evidence_index import check, review_input

EXECUTION_KINDS = ('algorithm', 'api', 'persistence', 'browser', 'build', 'package_startup')
STAGES = ('build-start', 'build-complete', 'data-ready', 'pre-review')


def stage_check(workspace, stage, execution=None, index=None, manifest=None, plan=None):
    """Check materials when they become due, without creating missing evidence.

    Pre-review deliberately does not require an independent review dispatch:
    admission and the real review call happen after this preparation step.
    Final review authentication remains contracts.model_review's responsibility.
    """
    workspace = no_links(workspace)
    if stage not in STAGES:
        raise ValueError('Unknown material handoff stage')
    errors = []

    def issue(location, message, action):
        errors.append({'code': 'stage-material', 'location': str(location),
                       'message': str(message)[:1000], 'action': action})

    def document(name, action):
        try:
            value = read_json(inside(workspace, '.product-v2/' + name))
            if not isinstance(value, dict):
                raise ValueError('Expected a JSON object')
            return value
        except (ValueError, OSError, TypeError) as exc:
            issue(name, exc, action); return {}

    run = document('run.json', 'Use proflow.py prepare on the original case workspace; do not prepare the extracted package tree.')
    if run.get('workspace') != str(workspace) or not run.get('run_id'):
        issue('run.json', 'Current original workspace and run_id required', 'Read the current prepared run.json; preserve historical runs.')
    if stage in {'build-start', 'build-complete', 'pre-review'}:
        action = ('Record the actual spawn_agent session_log, call_id and returned task_name in model-dispatch.json; '
                  'never invent a dispatch or fill in the future review call.')
        spec = document('model-dispatch.json', action)
        stages = spec.get('stages', {})
        if (spec.get('schema_version') != 1 or not isinstance(stages, dict) or 'build' not in stages
                or any(not isinstance(k, str) or (k not in {'build', 'review'}
                       and not re.fullmatch(r'repair-[1-9][0-9]*', k)) for k in stages)):
            issue('model-dispatch.json.stages', 'Actual build and retained contiguous repair dispatch records required', action)
            stages = {}
        repairs = sorted((k for k in stages if k.startswith('repair-')), key=lambda k: int(k.split('-')[1]))
        if repairs != ['repair-' + str(i) for i in range(1, len(repairs) + 1)]:
            issue('model-dispatch.json.stages', 'Repair sequence must be contiguous and retained', action)
        seen_calls, seen_agents = set(), set()
        for name in (['build'] + repairs if stages else []):
            try:
                from contracts import _dispatch_events
                entry = stages[name]
                if not isinstance(entry, dict) or not isinstance(entry.get('call_id'), str) or not entry['call_id']:
                    raise ValueError('Actual distinct stage call_id required')
                call_id = entry['call_id']
                if call_id in seen_calls:
                    raise ValueError('Distinct stage call IDs required')
                seen_calls.add(call_id)
                # Reuse the same authentic session root / call-output matcher as finalization.
                call, result, _ = _dispatch_events(entry.get('session_log', ''), call_id)
                payload = call['payload']; arguments = json.loads(payload['arguments'])
                effort = 'high' if name == 'build' else 'ultra'
                if (payload.get('name', '').split('.')[-1] != 'spawn_agent'
                        or arguments.get('fork_turns') != 'none' or arguments.get('model') != 'gpt-6.1-sol'
                        or arguments.get('reasoning_effort') != effort):
                    raise ValueError('Actual ' + name + ' must use gpt-6.1-sol/' + effort + ' with fork_turns=none')
                result = result['payload'].get('output')
                if isinstance(result, str):
                    result = json.loads(result)
                if (not isinstance(result, dict) or not isinstance(result.get('task_name'), str)
                        or not result['task_name'] or entry.get('agent_id') != result['task_name']
                        or result['task_name'] in seen_agents
                        or any(result.get(k) for k in ('error', 'isError', 'is_error'))):
                    raise ValueError('Distinct actual successful returned task_name must match agent_id')
                seen_agents.add(result['task_name'])
                if stage != 'build-start' and (not isinstance(entry.get('artifact_hashes'), dict)
                        or not entry['artifact_hashes'] or not isinstance(entry.get('chart_snapshot'), dict)
                        or not entry['chart_snapshot']):
                    raise ValueError('Retain each actual completed build/repair artifact_hashes and chart_snapshot')
            except (ValueError, OSError, KeyError, TypeError, AttributeError) as exc:
                issue('model-dispatch.json.stages.' + name, exc, action)
        if stage != 'build-start' and run:
            try:
                from contracts import construction_checks
                construction_checks(workspace, run, plan)
            except (ValueError, OSError, KeyError, TypeError, AttributeError) as exc:
                issue('build-checks.json', exc, 'Use the existing proflow.py check-build to identify stale dependencies; rerun only failed or changed checks.')
    if stage in {'data-ready', 'pre-review'}:
        action = ('Save the actual internal data-provenance.json with nature, sources and validation from this case; '
                  'retain truthful sourcing attempts and limitations. Reuse already qualified clean CSVs.')
        provenance = document('data-provenance.json', action)
        missing = [k for k in ('nature', 'sources', 'validation') if not provenance.get(k)]
        if missing:
            issue('data-provenance.json', 'Required internal provenance fields missing: ' + ', '.join(missing), action)
        if provenance.get('run_id') not in (None, run.get('run_id')):
            issue('data-provenance.json.run_id', 'Declared provenance belongs to a different run', action)
    report = {'schema_version': 1, 'kind': 'stage-material-preflight', 'stage': stage,
              'workspace': str(workspace), 'run_id': run.get('run_id'), 'errors': errors,
              'status': 'blocked' if errors else 'inputs_ready',
              'scope': 'Read-only due-stage metadata and authentic build/repair call checks; no future review dispatch required. '
                       'No business commands, media decode, independent approval or fabricated evidence.'}
    if stage == 'pre-review':
        if not execution:
            issue('execution', 'Six execution facts and final ZIP binding are due before review',
                  'Supply --execution <existing six-check JSON>; package_probe.py can record actual final ZIP startup facts.')
        else:
            packet = inspect(workspace, execution, index, manifest)
            report['review_inputs'] = packet
            errors.extend(packet['errors'])
        report['status'] = 'blocked' if errors else 'inputs_ready'
    return report


def execution_checks(value, kinds=EXECUTION_KINDS):
    """Keep the final-proof list contract; construction-check objects differ."""
    if (not isinstance(value, list) or len(value) != len(kinds)
            or not all(isinstance(item, dict) for item in value)
            or not all(isinstance(item.get('kind'), str) for item in value)
            or {item['kind'] for item in value} != set(kinds)):
        raise ValueError('Six distinct execution checks required: checks must be a list of '
                         'objects with exact kinds ' + ', '.join(kinds))
    return value


def inspect(workspace, execution, index=None, manifest=None):
    workspace = no_links(workspace)
    errors, paths = [], set()

    def issue(code, location, message):
        errors.append({'code': code, 'location': str(location), 'message': str(message)[:1000]})

    if index and manifest:
        issue('schema', 'scope', 'Choose an existing complete index OR a supplementary manifest; do not silently omit manifest files')

    def actual(value, expected=None):
        try:
            if not isinstance(value, (str, Path)) or not str(value):
                raise ValueError('Expected an actual file path')
            path = no_links(value) if Path(value).is_absolute() else inside(workspace, value, must_exist=False)
            if workspace not in path.parents:
                raise ValueError('Evidence must be inside the current workspace')
            if not path.is_file():
                issue('missing', value, 'Missing regular evidence file'); return None
            paths.add(path.relative_to(workspace).as_posix())
            if expected is not None and digest(path) != expected:
                issue('stale', value, 'Declared SHA256 differs from current evidence')
            return path
        except (ValueError, OSError, TypeError) as exc:
            issue('schema', value, exc); return None

    def document(value, required=True, expected=None):
        if not required and not (workspace / value).exists():
            return {}
        path = actual(value, expected)
        if path is None:
            return {}
        try:
            result = read_json(path)
            if not isinstance(result, dict):
                raise ValueError('Expected a JSON object')
            return result
        except (ValueError, OSError) as exc:
            issue('schema', value, exc); return {}

    run = document('.product-v2/run.json')
    if run.get('workspace') != str(workspace) or not run.get('run_id'):
        issue('schema', '.product-v2/run.json', 'Current workspace and run_id required')
    proof = document(execution)
    checks = []
    try:
        checks = execution_checks(proof.get('checks'))
    except ValueError as exc:
        issue('schema', 'checks', exc)
    for item in checks:
        kind = item['kind']
        if type(item.get('exit_code')) is not int or item['exit_code'] != 0:
            issue('failed', 'checks.' + kind, 'Actual successful integer exit_code required')
        if not isinstance(item.get('command'), str) or not item['command'].strip():
            issue('schema', 'checks.' + kind + '.command', 'Nonempty actual command required')
        if not isinstance(item.get('sha256'), str) or len(item['sha256']) != 64:
            issue('schema', 'checks.' + kind + '.sha256', 'Actual log SHA256 required')
        log = actual(item.get('log'), item.get('sha256', ''))
        if log and log.stat().st_size == 0:
            issue('missing', item['log'], 'Execution log is empty')

    charts = document('.product-v2/chart-manifest.json')
    try:
        from contracts import chart_policy, chart_records
        if chart_policy(run) is not None:
            chart_records(charts, run)
    except (ValueError, KeyError, TypeError, AttributeError) as exc:
        issue('schema', 'chart-manifest', exc)
    figures = charts.get('figures', [])
    if not isinstance(figures, list) or not figures:
        issue('schema', 'chart-manifest.figures', 'Current nonempty chart records required')
    else:
        for item in figures:
            if not isinstance(item, dict):
                issue('schema', 'chart-manifest.figures', 'Chart must be an object'); continue
            actual(item.get('png'), item.get('sha256', ''))
    package = document('.product-v2/source-package.json')
    members = package.get('files', {})
    if not isinstance(members, dict) or not members:
        issue('schema', 'source-package.files', 'Explicit current source hash map required')
    else:
        for rel, sha in members.items():
            actual(rel, sha)
    controlled = document('.product-v2/controlled-video.json')
    if controlled:
        timeline = document(controlled.get('timeline'), expected=controlled.get('sha256', ''))
        for group in ('frames', 'contact_sheets', 'interaction_frames'):
            items = timeline.get(group, [])
            if not isinstance(items, list) or not items:
                issue('schema', 'timeline.' + group, 'Actual declared timeline items required'); continue
            for item in items:
                if not isinstance(item, dict):
                    issue('schema', 'timeline.' + group, 'Timeline item must be an object'); continue
                actual(item.get('file'), item.get('sha256', ''))
    for name in ('recording.json', 'data-cleaning.json', 'data-quality.json',
                 'data-provenance.json', 'cleanup.json', 'model-dispatch.json', 'build-checks.json'):
        doc = document('.product-v2/' + name, required=False)
        if name == 'build-checks.json' and isinstance(doc.get('checks'), dict):
            for item in doc['checks'].values():
                if not isinstance(item, dict):
                    issue('schema', 'build-checks.checks', 'Construction check must be an object'); continue
                actual(item.get('log'), item.get('sha256', ''))
                inputs = item.get('input_files', {})
                if isinstance(inputs, dict):
                    for rel, sha in inputs.items():
                        actual(rel, sha)

    if manifest:
        extra = document(manifest).get('files')
        if not isinstance(extra, list) or not all(isinstance(rel, str) for rel in extra):
            issue('schema', 'manifest.files', 'Explicit evidence file list required')
        else:
            for rel in extra:
                actual(rel)
    output = None
    try:
        output = product_location(workspace, run)
        if output == workspace or workspace in output.parents or output in workspace.parents:
            raise ValueError('Product and workspace must be disjoint')
        if not output.is_dir() or not any(p.is_file() for p in output.rglob('*')):
            issue('missing', output, 'Current product output is missing or empty')
        from common import delivery_paths
        archive = delivery_paths(run, output)['source_zip']
        if not archive.is_file():
            issue('missing', archive, 'Current final source ZIP required')
        elif digest(archive) != proof.get('source_zip_sha256') or digest(archive) != package.get('sha256'):
            issue('stale', 'source_zip_sha256', 'Execution and package receipt must bind the final ZIP')
        if proof.get('video_timeline_sha256') != controlled.get('sha256'):
            issue('stale', 'video_timeline_sha256', 'Execution facts must bind the current controlled timeline')
    except (ValueError, OSError, KeyError, TypeError) as exc:
        issue('schema', 'run.output', exc)

    records = []
    if index:
        try:
            check(index, [], workspace)
            records = read_json(index)['evidence']
        except (ValueError, OSError, KeyError, TypeError, AttributeError) as exc:
            issue('stale', 'index', exc)
    elif not errors:
        records = [{'id': 'E' + str(i + 1).zfill(3), 'path': rel, 'sha256': digest(inside(workspace, rel))}
                   for i, rel in enumerate(sorted(paths))]
    return {'schema_version': 1, 'kind': 'review-input-preflight',
            'status': 'blocked' if errors else 'inputs_ready', 'errors': errors,
            'workspace': str(workspace), 'run_id': run.get('run_id'), 'evidence': records,
            'execution_checks': checks, 'source_zip_sha256': proof.get('source_zip_sha256'),
            'video_timeline_sha256': controlled.get('sha256'),
            'scope': 'Declared current evidence only; discovery is not proof of complete review scope. '
                     'Supply an existing complete index or explicit manifest for rendered Word pages and source mappings. '
                     'No commands executed, visuals viewed, review approved or receipt modified.'}


def draft(workspace, execution, destination, index=None, manifest=None, root=None, batch_id=None, token=None, compact=False):
    workspace = no_links(workspace); destination = no_links(destination)
    private = workspace / '.product-v2/review-inputs'
    if private not in destination.parents or destination.exists():
        raise ValueError('Use an explicit wholly new private .product-v2/review-inputs/<name> directory; never overwrite evidence or a review')
    report = inspect(workspace, execution, index, manifest)
    if report['errors']:
        return report  # No partial artifacts on failed preflight.
    metadata = {}
    if any(value is not None for value in (root, batch_id, token)):
        if not all((root, batch_id, token)): raise ValueError('Admitted draft requires --root, --batch-id and --token together')
        metadata = admitted_metadata(workspace, root, batch_id, token)
    else:
        metadata = current_admitted_metadata(workspace)
    # Keep real original member facts in the existing signed review, so a later
    # container-only repack need not repeat successful business execution.
    from common import delivery_paths
    from contracts import zip_member_hashes
    run = read_json(inside(workspace, '.product-v2/run.json'))
    archive = delivery_paths(run, no_links(run['output']))['source_zip']
    try:
        members = zip_member_hashes(archive)
        package = read_json(inside(workspace, '.product-v2/source-package.json'))
        if digest(archive) != report['source_zip_sha256'] or package.get('files') != members:
            raise ValueError('Current ZIP members differ from the actual source package receipt')
    except (ValueError, OSError, zipfile.BadZipFile) as exc:
        report['status'] = 'blocked'
        report['errors'].append({'code': 'source-package', 'location': 'source_package', 'message': str(exc)})
        return report
    destination.mkdir(parents=True, exist_ok=False)
    records = report['evidence']
    snapshot = {'schema_version': 1, 'workspace': str(workspace), 'evidence': records,
                'review_id': hashlib.sha256(json.dumps(records, sort_keys=True).encode()).hexdigest()[:12]}

    def save(name, value):
        # Exclusive creation: earlier reviews and index files are never replaced.
        with (destination / name).open('x', encoding='utf-8', newline='\n') as stream:
            json.dump(value, stream, ensure_ascii=False, indent=2); stream.write('\n')
    save('index.json', snapshot)
    facts_path = destination / 'facts.json'
    review_input(workspace, destination / 'index.json', facts_path, compact)
    save('preflight.json', report)
    save('review-draft.json', {**metadata, 'kind': 'non-authoritative-review-draft', 'run_id': report['run_id'],
         'checks': report['execution_checks'], 'source_zip_sha256': report['source_zip_sha256'],
         'source_package': {'sha256': report['source_zip_sha256'], 'files': members},
         'video_timeline_sha256': report['video_timeline_sha256'],
         'reviewed_files': read_json(facts_path)['current_artifacts'],
         'reviewed_evidence': [], 'chart_reviews': [], 'visual_notes': [], 'limitations': [],
         'instruction': 'Copied execution facts are unreviewed. Reviewer must actually inspect evidence, '
                        'write independent findings, actual coverage and identity, then attest the final proof hash. '
                        'This draft has no decision or signature and cannot finalize.'})
    return {'status': 'draft_created', 'directory': str(destination), 'evidence_items': len(records),
            'facts_path': str(facts_path), 'facts_sha256': digest(facts_path),
            'scope': report['scope']}


def admitted_metadata(workspace, root, batch_id, token):
    """Copy machine-owned routing facts, never reviewer conclusions or identity."""
    from batch_control import batch, load_review_admission, load_review_dispatch_permit
    workspace = no_links(workspace); _, manifest = batch(root, batch_id)
    tickets = [q for q in read_json(no_links(root) / 'queue.json')
               if q.get('token') == token and q.get('batch_id') == batch_id]
    if len(tickets) != 1 or tickets[0].get('stage') not in {'review', 'expedited'} or tickets[0].get('status') != 'active':
        raise ValueError('Neutral review metadata requires the current active review ticket')
    ticket = tickets[0]
    case = next(c for c in manifest['cases'] if c['case_id'] == ticket['case_id'])
    if no_links(case['workspace']) != workspace:
        raise ValueError('Review ticket belongs to a different workspace')
    reference, permit_reference = ticket.get('review_admission'), ticket.get('review_dispatch_permit')
    if not isinstance(reference, dict) or not isinstance(permit_reference, dict):
        raise ValueError('Acquire and verify-review before preparing admitted review metadata')
    admission = load_review_admission(workspace, reference)
    load_review_dispatch_permit(workspace, reference, permit_reference)
    return {'review_admission': reference, 'review_dispatch_permit': permit_reference,
            'run_id': admission['run_id']}


def current_admitted_metadata(workspace):
    """Bind an existing verified attempt automatically; do not require a future one."""
    from batch_control import media_binding
    binding = media_binding(workspace)
    if not binding: return {}
    queue = no_links(binding['root']) / 'queue.json'
    if not queue.is_file(): return {}
    tickets = [q for q in read_json(queue)
               if q.get('batch_id') == binding['batch_id'] and q.get('case_id') == binding['case_id']
               and q.get('stage') in {'review', 'expedited'} and q.get('status') == 'active']
    if len(tickets) > 1: raise ValueError('Ambiguous active review attempt; preserve existing leases')
    if not tickets or not tickets[0].get('review_dispatch_permit'): return {}
    return admitted_metadata(workspace, binding['root'], binding['batch_id'], tickets[0]['token'])


def recorded_review_dispatch(workspace, item, entry):
    """Locate only an already recorded actual dispatch, including old call records."""
    path = no_links(workspace) / '.product-v2/model-dispatch.json'
    if path.is_file():
        record = read_json(path).get('stages', {}).get('review', {})
        if (isinstance(record, dict) and record.get('review_admission') == entry.get('review_admission')
                and record.get('call_id')):
            return dict(record, stage=entry['stage'], status='dispatched')
    dispatched = [c for c in item.get('calls', []) if c.get('stage') in {'review', 'expedited'}
                  and c.get('status') == 'dispatched' and c.get('call_id')]
    for record in reversed(dispatched):
        if record.get('token', entry['token']) != entry['token']: continue
        completed = [c for c in item.get('calls', []) if c.get('call_id') == record['call_id']
                     and c.get('status', '').startswith('completed')]
        if not completed: return record
        latest = completed[-1]
        if latest.get('token') == entry['token']: return record
        proof_path = latest.get('review_evidence')
        if proof_path:
            proof = read_json(no_links(proof_path))
            reference = proof.get('review_admission') if isinstance(proof, dict) else None
            # A malformed current report is precisely the case that must keep
            # its reservation. A prior valid attempt with a different admission
            # does not block cancellation of an undispatched new attempt.
            if reference is None or reference == entry.get('review_admission'): return record
    return None


def complete_handoff(root, target, manifest, state, pool, entry, request_path, authorization):
    """Record an authenticated independent result before releasing its reservation.

    Failure leaves state and queue intact. The independent proof is only read;
    pass here records the reviewer's decision and does not finalize a product.
    """
    from copy import deepcopy
    from common import write_json
    from scheduler_policy import config
    from scheduler_repair import authenticate, freeze_binding
    request = read_json(request_path)
    if not isinstance(request, dict): raise ValueError('Review completion request must be an object')
    case_id = entry['case_id']; case = next(c for c in manifest['cases'] if c['case_id'] == case_id)
    work = no_links(case['workspace']); metadata = admitted_metadata(work, root, manifest['batch_id'], entry['token'])
    if request.get('outcome') in {'cancelled', 'diagnostic'}:
        return exit_handoff(root, target, manifest, state, pool, entry, request_path, request)
    proof_path = no_links(request.get('review_evidence', ''))
    if work not in proof_path.parents or digest(proof_path) != request.get('review_evidence_sha256'):
        raise ValueError('Exact independent report path/hash inside this workspace required')
    proof = read_json(proof_path)
    if not isinstance(proof, dict): raise ValueError('Independent review report must be an object')
    for key in ('run_id', 'review_admission', 'review_dispatch_permit'):
        if proof.get(key) != metadata[key]:
            raise ValueError('Independent report missing or mismatched ' + key + '; preserve report and review lease')
    decision = proof.get('decision')
    if decision not in {'pass', 'revise', 'blocked'}:
        raise ValueError('Actual independent pass/revise/blocked decision required')
    item = state['cases'][case_id]; dispatched = recorded_review_dispatch(work, item, entry)
    if not dispatched: raise ValueError('Record the actual independent dispatch before completing its review')
    proposed = deepcopy(state); current = proposed['cases'][case_id]
    # If this dispatch came from model-dispatch.json, retain that real call in
    # batch state too. The common authenticator re-reads the real JSONL call.
    if not any(c.get('call_id') == dispatched['call_id'] and c.get('status') == 'dispatched' for c in current.get('calls', [])):
        current.setdefault('calls', []).append(dispatched)
    completed = {'stage': entry['stage'], 'status': 'completed_' + decision,
                 'call_id': dispatched['call_id'], 'agent_id': proof.get('reviewer_agent_id'),
                 'review_evidence': str(proof_path), 'review_evidence_sha256': digest(proof_path),
                 'token': entry['token']}
    duplicates = [c for c in current.get('calls', []) if c.get('call_id') == dispatched['call_id'] and c.get('status', '').startswith('completed')]
    if duplicates and any(c.get('review_evidence_sha256') != completed['review_evidence_sha256'] or c.get('status') != completed['status'] for c in duplicates):
        raise ValueError('This actual dispatch already has a different completed result; preserve both records')
    if not duplicates: current.setdefault('calls', []).append(completed)
    current['phase'] = {'revise': 'repairing', 'pass': 'waiting_review', 'blocked': 'blocked'}[decision]
    current['review_result'] = {'decision': decision, 'review_evidence': str(proof_path),
                                'review_evidence_sha256': completed['review_evidence_sha256']}
    if decision == 'blocked': current['blocked_fingerprint'] = completed['review_evidence_sha256']
    settings = config(root)
    authenticated = authenticate(root, target, manifest, proposed, case_id, settings, authorization, decision)
    repair = freeze_binding(target, authenticated) if decision == 'revise' else None
    if repair:
        settings.setdefault('repair_bindings', {}).setdefault(manifest['batch_id'], {})[case_id] = repair
    # Queue replacement is last. If either earlier persistence fails, the slot
    # stays active and the same exact completed report can be retried safely.
    write_json(target / 'state.json', proposed)
    if repair: write_json(no_links(root) / 'scheduler-config.json', settings)
    entry['review_completion'] = {'schema_version': 1, 'decision': decision, 'call_id': dispatched['call_id'],
        'review_evidence': completed['review_evidence'], 'review_evidence_sha256': completed['review_evidence_sha256'],
        'authenticated_group': authenticated['group'], 'repair_binding': repair}
    entry['status'] = 'released'; entry['released_ns'] = __import__('time').time_ns()
    write_json(no_links(root) / 'queue.json', pool)
    return entry


def exit_handoff(root, target, manifest, state, pool, entry, request_path, request):
    """Safe cancellation/diagnostic bookkeeping; never manufacture a review report."""
    from copy import deepcopy
    from common import write_json
    from scheduler_policy import config
    from scheduler_repair import authenticate_exit
    outcome = request['outcome']; reason = request.get('reason')
    if not isinstance(reason, str) or not reason.strip(): raise ValueError('Actual cancellation/diagnostic reason required')
    if outcome == 'cancelled' and not state['drain']:
        raise ValueError('Cancellation requires the existing authorized drain; diagnostic exit still requires actual terminal evidence')
    case_id = entry['case_id']; case = next(c for c in manifest['cases'] if c['case_id'] == case_id)
    dispatched = recorded_review_dispatch(case['workspace'], state['cases'][case_id], entry)
    if not dispatched: raise ValueError('Actual dispatched review required; undispatched cancellation uses release-slot')
    verified = authenticate_exit(root, manifest, state, case_id, config(root), entry, dispatched)
    proposed = deepcopy(state); item = proposed['cases'][case_id]
    if not any(c.get('call_id') == dispatched['call_id'] and c.get('status') == 'dispatched' for c in item.get('calls', [])):
        item.setdefault('calls', []).append(dispatched)
    completed = {'stage': entry['stage'], 'status': 'completed_' + outcome, 'call_id': dispatched['call_id'],
                 'agent_id': verified['reviewer_agent_id'], 'token': entry['token'], 'reason': reason,
                 'termination_evidence': verified}
    previous = [c for c in item.get('calls', []) if c.get('call_id') == dispatched['call_id'] and c.get('status', '').startswith('completed')]
    differing = previous and any(c.get('status') != completed['status'] for c in previous)
    if differing and outcome != 'cancelled':
        raise ValueError('Existing independent result must be preserved; do not replace it with cancellation/diagnostic status')
    if differing:
        # An authorized stop may close a terminated attempt whose report still
        # needs metadata correction. Retain its result verbatim, and append an
        # exit fact rather than overwriting the independent decision.
        completed['status'] = 'attempt_exit_cancelled'
        if not any(c.get('call_id') == completed['call_id'] and c.get('status') == completed['status'] for c in item['calls']):
            item['calls'].append(completed)
    elif not previous:
        item.setdefault('calls', []).append(completed)
    if not differing: item['phase'] = 'waiting_review'
    item['review_exit'] = {'outcome': outcome, 'reason': reason, 'token': entry['token'], 'termination_evidence': verified}
    write_json(target / 'state.json', proposed)
    entry['review_completion'] = {'schema_version': 1, 'outcome': outcome, 'call_id': dispatched['call_id'],
        'request_sha256': digest(no_links(request_path)), 'termination_evidence': verified,
        'scope': 'Attempt ended without a review decision; product review remains incomplete.'}
    entry['status'] = 'released'; entry['released_ns'] = __import__('time').time_ns()
    write_json(no_links(root) / 'queue.json', pool)
    return entry


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=['check', 'draft', 'stage-check'])
    parser.add_argument('--workspace', required=True); parser.add_argument('--execution')
    parser.add_argument('--stage', choices=STAGES)
    parser.add_argument('--plan', help='Existing recording plan for build-complete/pre-review construction checks')
    parser.add_argument('--root'); parser.add_argument('--batch-id'); parser.add_argument('--token')
    parser.add_argument('--compact', action='store_true', help='Short neutral facts reference the complete unchanged evidence index; no coverage is inferred')
    scope = parser.add_mutually_exclusive_group()
    scope.add_argument('--index'); scope.add_argument('--manifest'); parser.add_argument('--output')
    args = parser.parse_args(argv)
    try:
        if args.action == 'stage-check':
            if not args.stage:
                raise ValueError('stage-check requires an explicit --stage')
            result = stage_check(args.workspace, args.stage, args.execution, args.index, args.manifest, args.plan)
        elif not args.execution:
            raise ValueError('check/draft requires --execution')
        elif args.action == 'draft':
            if not args.output:
                raise ValueError('draft requires an explicit private --output directory')
            result = draft(args.workspace, args.execution, args.output, args.index, args.manifest, args.root, args.batch_id, args.token, args.compact)
        else:
            result = inspect(args.workspace, args.execution, args.index, args.manifest)
    except (ValueError, OSError, KeyError, TypeError) as exc:
        result = {'status': 'blocked', 'errors': [{'code': 'schema', 'location': args.action, 'message': str(exc)}]}
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 2 if result['status'] == 'blocked' else 0


if __name__ == '__main__':
    raise SystemExit(main())
