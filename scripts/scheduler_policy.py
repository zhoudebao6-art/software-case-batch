"""Opt-in live-safe controller groups; no dispatch, process changes or case writes."""
import hashlib
import json
from pathlib import Path
import re
import time
import uuid
from copy import deepcopy
from common import digest, no_links, read_json, write_json, session_filename_matches

CONTRACT = 'verified-controller-fair-v1'
ADAPTIVE_CONTRACT = 'verified-controller-adaptive-v2'
FAIR_MODES = {CONTRACT, ADAPTIVE_CONTRACT}
DEFAULT_AGING_SECONDS = 300
DEFAULT_MODEL_POOL_CAPACITY = 12
GLOBAL_CAPACITY_SCOPE = 'global-model-pool'
RUNTIME_CAPACITY_SCOPE = 'verified-parent-runtime'
LEGACY_PARENT_WORKERS = 3
DEFAULT_CAPACITIES = {'build': 8, 'review': 3, 'expedited': 1}
MAX_CAPACITIES = {'build': 8, 'review': 8, 'expedited': 4}
MODEL_STAGES = set(DEFAULT_CAPACITIES)


def parent_runtime_scope(settings):
    return settings.get('mode') == ADAPTIVE_CONTRACT and settings.get('capacity_scope') == RUNTIME_CAPACITY_SCOPE


def model_pool_capacity(settings):
    if parent_runtime_scope(settings): return None
    value = settings.get('model_pool_capacity', DEFAULT_MODEL_POOL_CAPACITY)
    return value if type(value) is int and 1 <= value <= DEFAULT_MODEL_POOL_CAPACITY else 1


def runtime_workers(event):
    p = event.get('payload', {})
    metadata = p.get('internal_chat_message_metadata_passthrough', {})
    if (event.get('type') != 'response_item' or p.get('type') != 'message' or
        p.get('role') != 'developer' or
        'multi_agent.role_instructions' not in metadata.get('content_item_kinds', [])): return None
    text = '\n'.join(item.get('text', '') for item in p.get('content', []) if item.get('type') == 'input_text')
    matches = re.findall(r'There are ([1-9][0-9]*) available concurrency slots, meaning that up to \1 agents can be active at once, including you\.', text)
    return int(matches[0]) - 1 if len(matches) == 1 and '<multi_agent_role>' in text else 0


def runtime_capacity(log):
    """Explicit owner bind/refresh only: freeze the latest platform developer fact.

    Normal acquire/status only rechecks its bounded byte range. Runtime changes
    require the original owner to refresh the same binding before dispatch.
    """
    result = None
    with log.open('rb') as stream:
        while True:
            offset = stream.tell(); raw = stream.readline()
            if not raw: break
            try: event = json.loads(raw)
            except (ValueError, UnicodeDecodeError): continue
            workers = runtime_workers(event)
            if workers is None: continue
            result = {'worker_capacity': workers, 'event_offset': offset,
                      'event_size': len(raw), 'event_sha256': hashlib.sha256(raw).hexdigest()}
    return result


def binding_workers(binding, manifest, settings):
    if settings.get('mode') == ADAPTIVE_CONTRACT and binding and binding.get('runtime_capacity'):
        workers = binding['runtime_capacity']['worker_capacity']
        return workers if parent_runtime_scope(settings) else min(model_pool_capacity(settings), workers)
    return min(LEGACY_PARENT_WORKERS, manifest['execution_profile']['worker_capacity'],
               binding['worker_capacity'] if binding else LEGACY_PARENT_WORKERS)


def group_workers(root, binding, manifest, settings, cache):
    adaptive = settings.get('mode') == ADAPTIVE_CONTRACT
    if not binding:
        if adaptive and manifest['batch_id'] in settings.get('bindings', {}): return 0
        return binding_workers(None, manifest, settings)
    import batch_control as batch
    siblings = []; controls = []
    for batch_id, reference in settings.get('bindings', {}).items():
        other = verified_binding(root, batch_id, settings, cache)
        if other and other['group'] == binding['group']: siblings.append(other)
        if not adaptive: continue
        control = other or reference
        # An old reference may lack group/order fields even when its frozen
        # snapshot still proves that it belongs to another parent. Exclude only
        # that independently identified group; an ambiguous or same-group
        # invalid reference must continue to block admission.
        if not other and not all(key in reference for key in ('group', 'control_revision', 'bound_ns')):
            try:
                old_path = no_links(reference['path'])
                old_target, _ = batch.batch(root, batch_id)
                if digest(old_path) != reference['sha256']:
                    return 0
                old = read_json(old_path)
                if (old.get('batch_id') != batch_id or old.get('root') != str(no_links(root)) or
                        old.get('manifest_sha256') != digest(old_target / 'manifest.json') or
                        not isinstance(old.get('group'), str) or not old['group']):
                    return 0
            except (ValueError, OSError, KeyError, TypeError):
                return 0
            if old['group'] != binding['group']:
                continue
            return 0
        if control['group'] == binding['group']: controls.append((control, other))
    if adaptive:
        latest, verified = max(controls, key=lambda row: (row[0].get('control_revision', 0), row[0]['bound_ns']))
        # The latest known control stays authoritative even when its evidence
        # fails. A later valid owner refresh can restore capacity; active is intact.
        if not verified: return 0
        return binding_workers(latest, batch.batch(root, latest['batch_id'])[1], settings)
    return min(binding_workers(row, batch.batch(root, row['batch_id'])[1], settings) for row in siblings)


def config(root):
    path = no_links(root) / 'scheduler-config.json'
    return read_json(path) if path.exists() else {'mode': 'legacy', 'bindings': {}, 'active_groups': {}, 'history': []}


def option(arguments, name):
    positions = [i for i, value in enumerate(arguments) if value == '--' + name]
    return arguments[positions[0] + 1] if len(positions) == 1 and positions[0] + 1 < len(arguments) else None


def _direct_statements(source):
    """Conservative static PowerShell subset, never execute text from a log.

    Only complete top-level statements can prove a call. Strings and comments
    are consumed as data; blocks, expressions, pipelines and dynamic arguments
    are ineligible. Unsupported or malformed syntax fails closed.
    """
    statements = []; tokens = []; depth = []; unsafe = False; index = 0
    while index < len(source):
        char = source[index]
        if source.startswith('<#', index):
            level = 1; index += 2
            while index < len(source) and level:
                if source.startswith('<#', index): level += 1; index += 2
                elif source.startswith('#>', index): level -= 1; index += 2
                else: index += 1
            if level: return []
            continue
        if char == '#':
            end = source.find('\n', index); index = len(source) if end < 0 else end
            continue
        if source.startswith(("@'", '@"'), index):
            # Here-strings cannot be controller arguments; skip all their data.
            quote = source[index + 1]; end = re.search(r'(?m)^' + re.escape(quote + '@') + r'(?=\r?$)', source[index + 2:])
            if not end: return []
            unsafe = True; index += 2 + end.end(); continue
        if char in "'\"":
            if index and not source[index - 1].isspace() and source[index - 1] not in ';|&(){}[]': unsafe = True
            quote = char; index += 1; value = ''
            while index < len(source):
                char = source[index]
                if char == quote:
                    if quote == "'" and source[index:index + 2] == "''": value += quote; index += 2; continue
                    index += 1; break
                if quote == '"' and char == '`': return []
                value += char; index += 1
            else: return []
            if quote == '"' and '$' in value: unsafe = True
            if index < len(source) and not source[index].isspace() and source[index] not in ';|&(){}[]#': unsafe = True
            tokens.append((value, True)); continue
        if char in '({[':
            depth.append(char); unsafe = True; index += 1; continue
        if char in ')}]':
            if not depth or depth.pop() != {')': '(', '}': '{', ']': '['}[char]: return []
            index += 1; continue
        if char in ';\r\n':
            if not depth:
                statements.append((tokens, unsafe)); tokens = []; unsafe = False
            index += 1; continue
        if char.isspace(): index += 1; continue
        if char in '|<>`': unsafe = True; index += 1; continue
        if char == '&': tokens.append(('&', False)); index += 1; continue
        end = index + 1
        while end < len(source) and not source[end].isspace() and source[end] not in "'\";|&(){}[]#<>`": end += 1
        tokens.append((source[index:end], False)); index = end
    if depth: return []
    statements.append((tokens, unsafe))
    return statements


def controller_commands(command):
    """Return literal argv from actual direct Python calls, never printed examples."""
    python = lambda value: re.fullmatch(r'(?:python(?:\d+(?:\.\d+)*)?|py)(?:\.exe)?', re.split(r'[\\/]', value)[-1], re.I)
    if not command: return []
    executable = re.split(r'[\\/]', command[0])[-1].casefold()
    direct_python = bool(python(command[0]))
    if direct_python:
        statements = [([(value, True) for value in command], False)]
    elif executable in {'pwsh', 'pwsh.exe', 'powershell', 'powershell.exe'}:
        flags = [value.casefold() for value in command[1:-2]]
        if len(command) < 3 or command[-2].casefold() != '-command' or any(value not in {'-noprofile', '-noninteractive', '-nologo'} for value in flags): return []
        if '`' in command[-1]: return []  # Unsupported escapes/continuations invalidate this entire source.
        statements = _direct_statements(command[-1])
    else: return []
    result = []
    for tokens, unsafe in statements:
        if not tokens: continue
        if any(not literal and value.casefold() in {'return', 'exit', 'break', 'continue'} for value, literal in tokens): break
        if not tokens[0][1] and tokens[0][0].casefold() in {'return', 'exit', 'throw'}: break
        if unsafe: continue
        called = tokens[0] == ('&', False)
        if called: tokens = tokens[1:]
        if len(tokens) < 3: continue
        interpreter, quoted = tokens[0]
        if not (python(interpreter) and (called or not quoted or direct_python) or
                called and not quoted and interpreter.casefold() == '$env:scb_pro_python'): continue
        if re.split(r'[\\/]', tokens[1][0])[-1].casefold() != 'batch_control.py': continue
        if any(not literal and (value.startswith(('$', '@')) or value == '&') for value, literal in tokens[1:]): continue
        arguments = [value for value, _ in tokens[1:]]
        if arguments[1] in {'claim', 'recover-owner', 'preflight', 'update', 'queue', 'acquire', 'priority', 'verify-review', 'bind-controller'}: result.append(arguments)
    return result


def _desktop_root_without_thread_source(meta):
    """Recognize only the observed Desktop 0.160.1 root metadata omission.

    This is not identity proof: session_proof still checks the authoritative
    path/UUID, platform capacity and successful batch/root/owner command. An
    explicit thread_source (including null) never enters this compatibility path.
    """
    return ('thread_source' not in meta and meta.get('source') == 'vscode' and
            meta.get('originator') == 'Codex Desktop' and meta.get('cli_version') == '0.160.1' and
            not any(key in meta for key in ('parent_thread_id', 'parent_session_id', 'parent_id',
                                           'parent', 'subagent', 'thread_spawn', 'agent_path', 'agent_id')))


def session_proof(root, batch_id, pid, request):
    """Only a registered owner's completed controller command proves association.

    SESSION_ROOT is the same authoritative JSONL store used by model contracts.
    A supplied name, shared app-server PID, quoted message or foreign batch log
    cannot create an independent group. Append-only offsets allow cheap rechecks.
    """
    from contracts import SESSION_ROOT
    path = no_links(request['session_log']); session_id = str(uuid.UUID(request['session_id']))
    if no_links(SESSION_ROOT) not in path.parents or not session_filename_matches(path, session_id):
        raise ValueError('Controller requires actual Codex session JSONL and filename identity')
    with path.open('rb') as stream:
        raw_meta = stream.readline(); meta_event = json.loads(raw_meta)
        meta = meta_event.get('payload', {})
        desktop_root = _desktop_root_without_thread_source(meta)
        if (meta_event.get('type') != 'session_meta' or meta.get('id') != session_id or
            meta.get('session_id', session_id) != session_id or
            (meta.get('thread_source') not in ('user', 'agent_created_thread') and not desktop_root) or
            meta.get('parent_thread_id') or isinstance(meta.get('source'), dict)):
            raise ValueError('Controller requires an actual independent user parent session identity')
        if desktop_root:
            capacity = runtime_capacity(path)
            if not capacity or capacity['worker_capacity'] <= 0:
                raise ValueError('Desktop root without thread_source requires actual platform worker capacity evidence')
        # Native create_thread opens a user-owned root chat. Child/worker identity
        # remains excluded above, and the real matching owner command is required below.
        while True:
            offset = stream.tell(); raw = stream.readline()
            if not raw: break
            try: event = json.loads(raw)
            except json.JSONDecodeError: continue
            if event.get('type') != 'event_msg': continue
            payload = event.get('payload', {}); item = payload.get('item', {})
            if (payload.get('type') != 'item_completed' or payload.get('thread_id') != session_id or
                item.get('type') != 'CommandExecution' or item.get('status') != 'completed' or item.get('exit_code') != 0): continue
            commands = item.get('command', []); output = item.get('aggregated_output', '')
            if not isinstance(commands, list) or not all(isinstance(c, str) for c in commands): continue
            # Do not turn a failed Python command hidden by shell success into evidence.
            if not output.strip() or 'ERROR:' in output or re.search(r'exit=[1-9]', output): continue
            for command in controller_commands(commands):
                if option(command, 'batch-id') != batch_id or option(command, 'pid') != str(pid): continue
                supplied_root = option(command, 'root')
                if not supplied_root or no_links(supplied_root) != no_links(root): continue
                return {'session_id': session_id, 'session_log': str(path),
                        'meta_sha256': hashlib.sha256(raw_meta).hexdigest(),
                        'event_offset': offset, 'event_size': len(raw), 'event_sha256': hashlib.sha256(raw).hexdigest()}
    raise ValueError('No actual successful controller command proves this batch/root/owner in this session')


def verified_binding(root, batch_id, settings, cache=None):
    cache = cache if cache is not None else {}
    if batch_id in cache: return cache[batch_id]
    reference = settings.get('bindings', {}).get(batch_id)
    result = None
    if reference:
        try:
            from contracts import SESSION_ROOT
            import batch_control as batch
            target, manifest = batch.batch(root, batch_id); path = no_links(reference['path'])
            if path.parent != target / 'scheduler-bindings' or digest(path) != reference['sha256']:
                raise ValueError('Controller binding snapshot changed')
            binding = read_json(path); proof = binding['proof']; log = no_links(proof['session_log'])
            if (binding['contract'] != CONTRACT or binding['batch_id'] != batch_id or binding['root'] != str(no_links(root)) or
                any(reference.get(key, binding.get(key)) != binding.get(key) for key in ('group', 'control_revision', 'bound_ns')) or
                binding['manifest_sha256'] != digest(target / 'manifest.json') or
                binding['owner'] != read_json(target / 'owner.json') or batch.identity(binding['owner']['pid']) != binding['owner'] or
                no_links(SESSION_ROOT) not in log.parents or not session_filename_matches(log, proof['session_id'])):
                raise ValueError('Controller binding identity changed')
            with log.open('rb') as stream:
                if hashlib.sha256(stream.readline()).hexdigest() != proof['meta_sha256']: raise ValueError('Session identity changed')
                stream.seek(proof['event_offset'])
                if hashlib.sha256(stream.read(proof['event_size'])).hexdigest() != proof['event_sha256']: raise ValueError('Session association changed')
                saved = binding.get('runtime_capacity')
                if saved:
                    stream.seek(saved['event_offset'])
                    raw_runtime = stream.read(saved['event_size'])
                    if hashlib.sha256(raw_runtime).hexdigest() != saved['event_sha256']: raise ValueError('Runtime capacity evidence changed')
                    workers = runtime_workers(json.loads(raw_runtime))
                    if workers is None or workers != saved['worker_capacity']: raise ValueError('Runtime capacity evidence mismatch')
            result = binding
        except (ValueError, OSError, KeyError, TypeError):
            result = None  # Changed binding never creates capacity; it falls back conservatively.
    cache[batch_id] = result
    return result


def control(root, target, manifest, pid, action, value, authorization, pool, case_id=None):
    """Called under batch_control's existing shared transaction/owner check."""
    import batch_control as batch
    if not authorization or not authorization.strip(): raise ValueError('Explicit current scheduling authorization reference required')
    settings = config(root); previous = deepcopy({key: settings.get(key) for key in ('mode', 'capacity_scope', 'capacities', 'bindings', 'active_groups', 'repair_extra_capacity', 'repair_bindings', 'aging_seconds', 'model_pool_capacity')})
    if action == 'configure-scheduler':
        update = read_json(value)
        if update.get('mode') not in {'legacy', *FAIR_MODES}: raise ValueError('Unknown scheduling policy; use verified-controller-adaptive-v2, verified-controller-fair-v1 or legacy')
        scope = update.get('capacity_scope', GLOBAL_CAPACITY_SCOPE)
        if scope not in {GLOBAL_CAPACITY_SCOPE, RUNTIME_CAPACITY_SCOPE} or (scope == RUNTIME_CAPACITY_SCOPE and update['mode'] != ADAPTIVE_CONTRACT):
            raise ValueError('Capacity scope must be global-model-pool, or verified-parent-runtime with adaptive-v2')
        if scope == RUNTIME_CAPACITY_SCOPE and 'model_pool_capacity' in update:
            raise ValueError('Parent runtime scope has no global model_pool_capacity; omit that field')
        capacities = dict(DEFAULT_CAPACITIES); capacities.update(update.get('capacities', {}))
        if set(capacities) != MODEL_STAGES or any(type(v) is not int or v < 1 or v > MAX_CAPACITIES[k] for k, v in capacities.items()):
            raise ValueError('Bounded model capacities required: build<=8 review<=8 expedited<=4')
        extra = update.get('repair_extra_capacity', 0)
        if type(extra) is not int or not 0 <= extra <= 2: raise ValueError('Verified repair extra capacity must be 0, 1 or 2')
        aging = update.get('aging_seconds', DEFAULT_AGING_SECONDS)
        if type(aging) is not int or not 1 <= aging <= 3600: raise ValueError('Aging seconds must be an integer from 1 to 3600')
        total = update.get('model_pool_capacity', settings.get('model_pool_capacity', DEFAULT_MODEL_POOL_CAPACITY) if scope == RUNTIME_CAPACITY_SCOPE else DEFAULT_MODEL_POOL_CAPACITY)
        if type(total) is not int or not 1 <= total <= DEFAULT_MODEL_POOL_CAPACITY: raise ValueError('Model pool capacity must be an integer from 1 to 12')
        settings.update(mode=update['mode'], capacity_scope=scope, capacities=capacities, repair_extra_capacity=extra, aging_seconds=aging, model_pool_capacity=total)
    elif action == 'bind-controller':
        request = read_json(value); proof = session_proof(root, manifest['batch_id'], pid, request)
        if any(key in request for key in ('runtime_capacity', 'host_total_slots', 'model_pool_capacity')):
            raise ValueError('Runtime capacity must come from platform developer evidence, not request JSON')
        if 'worker_capacity' in request and request['worker_capacity'] != min(LEGACY_PARENT_WORKERS, manifest['execution_profile']['worker_capacity']):
            raise ValueError('Controller capacity cannot be supplied; legacy fallback capped at three, runtime evidence is required')
        group = proof['session_id']; active_groups = settings.setdefault('active_groups', {})
        for ticket in pool:
            if ticket['batch_id'] != manifest['batch_id'] or ticket['status'] != 'active': continue
            recorded = ticket.get('scheduler_admission', {}).get('group') or active_groups.get(ticket['token'])
            if recorded and recorded != group: raise ValueError('Active reservations cannot move to a different controller group')
        binding = {'contract': CONTRACT, 'root': str(no_links(root)), 'batch_id': manifest['batch_id'],
                   'manifest_sha256': digest(target / 'manifest.json'), 'owner': batch.identity(pid), 'proof': proof,
                   'group': group, 'worker_capacity': min(LEGACY_PARENT_WORKERS, manifest['execution_profile']['worker_capacity']),
                   'runtime_capacity': runtime_capacity(no_links(proof['session_log'])),
                   'control_revision': len(settings.get('history', [])) + 1,
                   'bound_ns': time.time_ns(), 'authorization': authorization}
        path = target / 'scheduler-bindings' / (uuid.uuid4().hex + '.json')
        batch.new_json(path, binding)
        settings.setdefault('bindings', {})[manifest['batch_id']] = {'path': str(path), 'sha256': digest(path),
            **{key: binding[key] for key in ('group', 'control_revision', 'bound_ns')}}
        for ticket in pool:
            if ticket['batch_id'] == manifest['batch_id'] and ticket['status'] == 'active': active_groups[ticket['token']] = group
    elif action == 'bind-repair':
        from scheduler_repair import bind
        state = read_json(target / 'state.json'); request = read_json(value)
        if case_id is not None and request.get('case_id', case_id) != case_id: raise ValueError('Repair request must match the explicit case_id')
        case_id = case_id if case_id is not None else request['case_id']
        if case_id not in state['cases']: raise ValueError('Repair binding requires this batch registered case')
        settings.setdefault('repair_bindings', {}).setdefault(manifest['batch_id'], {})[case_id] = bind(root, target, manifest, state, case_id, settings, authorization)
    else: raise ValueError('Unsupported scheduling control')
    settings.setdefault('history', []).append({'at_ns': time.time_ns(), 'action': action, 'authorization': authorization,
                                              'owner': batch.identity(pid), 'batch_id': manifest['batch_id'], 'previous': previous})
    write_json(no_links(root) / 'scheduler-config.json', settings)
    return settings


def active_group(root, ticket, settings):
    # Current active tokens keep their admitted group even after binding/rollback.
    return ticket.get('scheduler_admission', {}).get('group') or settings.get('active_groups', {}).get(ticket['token'])


def snapshot(root, pool, settings):
    """Read-only local reservation census, never external model availability."""
    import batch_control as batch
    cache = {}; groups = {}; profiles = {}
    for batch_id in settings.get('bindings', {}):
        binding = verified_binding(root, batch_id, settings, cache)
        if not binding: continue
        target, manifest = batch.batch(root, batch_id)
        workers = group_workers(root, binding, manifest, settings, cache)
        row = groups.setdefault(binding['group'], {'group': binding['group'], 'batch_ids': [],
            'accepting_batch_ids': [], 'worker_ceiling': workers})
        row['batch_ids'].append(batch_id); row['worker_ceiling'] = min(row['worker_ceiling'], workers)
        try:
            target, _ = batch.batch(root, batch_id); state = read_json(target / 'state.json')
            if not state['drain'] and any(c.get('phase') not in {'blocked', 'delivered'} for c in state['cases'].values()):
                row['accepting_batch_ids'].append(batch_id)
        except (ValueError, OSError, KeyError, TypeError): pass
    active = [q for q in pool if q['status'] == 'active']
    model_count = sum(q['stage'] in MODEL_STAGES for q in active)
    global_capacity = model_pool_capacity(settings)
    global_free = None if global_capacity is None else max(0, global_capacity - model_count)
    for ticket in active:
        if ticket['batch_id'] not in profiles: profiles[ticket['batch_id']] = batch.batch(root, ticket['batch_id'])[1]['execution_profile']
    for group, row in groups.items():
        row['reserved_model_slots'] = 0; row['unknown_active_slots'] = 0
        for ticket in active:
            live_group = active_group(root, ticket, settings)
            if live_group is not None and live_group != group: continue
            profile = profiles[ticket['batch_id']]
            if ticket['stage'] not in MODEL_STAGES and profile.get('resource_accounting') == 'separate-model-media-v1':
                continue  # Independent media jobs neither consume nor reduce model capacity.
            if live_group is None:
                row['worker_ceiling'] = min(row['worker_ceiling'], LEGACY_PARENT_WORKERS, profile['worker_capacity'])
            if ticket['stage'] in MODEL_STAGES or profile.get('resource_accounting') != 'separate-model-media-v1':
                row['reserved_model_slots'] += 1
                if live_group is None: row['unknown_active_slots'] += 1
        local_free = max(0, row['worker_ceiling'] - row['reserved_model_slots']) if row['accepting_batch_ids'] else 0
        row['unreserved_model_slots'] = local_free if global_free is None else min(global_free, local_free)
    return {'groups': sorted(groups.values(), key=lambda row: row['group']),
            'capacity_scope': settings.get('capacity_scope', GLOBAL_CAPACITY_SCOPE),
            'global_model_hard_limit': global_capacity is not None,
            'model_pool_capacity': global_capacity, 'unreserved_global_model_slots': global_free,
            'active_model_reservations': model_count,
            'unknown_active_model_reservations': sum(q['stage'] in MODEL_STAGES and active_group(root, q, settings) is None for q in active),
            'scope': 'local reservations only; readiness gates and external model capacity not included'}


def limits(root, manifest, active, stage, settings, cache):
    import batch_control as batch
    binding = verified_binding(root, manifest['batch_id'], settings, cache)
    group = binding['group'] if binding else None
    workers = group_workers(root, binding, manifest, settings, cache)
    profiles = [manifest['execution_profile']]; count = 0
    for ticket in active:
        live_group = active_group(root, ticket, settings)
        # Unidentified active work may belong to ANY known group: reserve it in
        # each group until a verified binding exists. Never multiply batch count.
        if group is None or live_group is None or live_group == group:
            profile = batch.batch(root, ticket['batch_id'])[1]['execution_profile']
            if ticket['stage'] not in MODEL_STAGES and profile.get('resource_accounting') == 'separate-model-media-v1':
                continue  # Its own media gates still control CPU, memory and recording slots.
            profiles.append(profile)
            if ticket['stage'] in MODEL_STAGES or profile.get('resource_accounting') != 'separate-model-media-v1': count += 1
            if live_group is None or group is None or settings.get('mode') != ADAPTIVE_CONTRACT:
                workers = min(workers, LEGACY_PARENT_WORKERS, profile['worker_capacity'])
    # Same-parent batches use one latest verified runtime refresh, never a sum.
    # Adaptive sharing removes stage partitions ONLY for a verified live owner.
    # No aggregate of bindings is used: duplicate, drained or completed groups
    # cannot lend fictional slots to another group. Unbound owners retain the
    # conservative fallback and unknown active work still counts in every group.
    if settings.get('mode') == ADAPTIVE_CONTRACT:
        limit = None if binding else DEFAULT_CAPACITIES[stage]
        if not parent_runtime_scope(settings) and sum(q['stage'] in MODEL_STAGES for q in active) >= model_pool_capacity(settings):
            return limit, False, group
    else:
        limit = settings['capacities'][stage] + (settings.get('repair_extra_capacity', 0) if stage == 'build' else 0)
    return limit, count < workers, group


def lane(ticket):
    admitted = ticket.get('scheduler_admission', {})
    if admitted.get('lane'): return admitted['lane']
    if ticket['stage'] in {'review', 'expedited'}: return 'review'
    return 'repair' if (ticket.get('model_kind') == 'repair' or
                        ticket.get('work_kind', admitted.get('work_kind')) == 'repair') else 'build'


def choose_adaptive(candidates, groups, pool, settings):
    """Three eligible lanes share live group slots without stage quotas.

    Global scope alternates urgency within the least-recently-admitted lane.
    Parent runtime scope selects urgent candidates first, then rotates lanes
    within that class. Each continuously eligible lane of the selected class gets a turn within
    three successful admissions; this is conditional on owners acquiring and
    active work finishing, not a wall-clock or actual-model capacity promise.
    Aged FIFO within a group/batch prevents priority churn starving old work.
    """
    history = sorted((q for q in pool if q['stage'] in MODEL_STAGES and q.get('acquired_ns')),
                     key=lambda q: (q.get('scheduler_turn') is not None,
                                    q.get('scheduler_turn', q['acquired_ns']), q['token']))
    turns = {q['token']: index for index, q in enumerate(history, 1)}
    if parent_runtime_scope(settings):
        # Urgent work gets the next available reservation in THIS parent only.
        # Normal work retains lane/batch rotation and aging; active is never preempted.
        urgent_candidates = [q for q in candidates if q['priority'] >= 10]
        if urgent_candidates: candidates = urgent_candidates
    lane_last = {}
    for ticket in history: lane_last[lane(ticket)] = turns[ticket['token']]
    order = {'review': 0, 'repair': 1, 'build': 2}
    selected_lane = min({lane(q) for q in candidates}, key=lambda k: (lane_last.get(k, 0), order[k]))
    candidates = [q for q in candidates if lane(q) == selected_lane]
    lane_history = [q for q in history if lane(q) == selected_lane]
    urgent = lambda q: q['priority'] >= 10
    classes = {urgent(q) for q in candidates}
    selected_class = not urgent(lane_history[-1]) if lane_history and len(classes) == 2 else (True in classes)
    candidates = [q for q in candidates if urgent(q) == selected_class]
    group_last = {}; batch_last = {}
    for ticket in lane_history:
        if urgent(ticket) != selected_class: continue
        group_last[active_group(None, ticket, settings)] = turns[ticket['token']]
        batch_last[ticket['batch_id']] = turns[ticket['token']]
    cutoff = time.time_ns() - settings.get('aging_seconds', DEFAULT_AGING_SECONDS) * 1_000_000_000
    def rank(q):
        aged = q['submitted_ns'] <= cutoff
        return (group_last.get(groups[q['token']], 0), batch_last.get(q['batch_id'], 0),
                not aged, 0 if aged else -q['priority'], q['submitted_ns'], q['token'])
    chosen = min(candidates, key=rank)
    chosen['scheduler_lane'] = selected_lane
    chosen['scheduler_aged'] = chosen['submitted_ns'] <= cutoff
    return chosen, groups[chosen['token']]


def choose(root, ready, active, pool, settings, requester_batch_id=None):
    """Filter before class/group/batch arbitration; unused shares are immediately lent.

    Global scope alternates continuously eligible classes (urgent first).
    Explicit parent runtime scope selects only the requester's parent and gives
    its urgent candidates precedence; it never acquires a foreign owner's token.
    Within a class, least-recently-served real group and batch rotate, then priority
    and immutable FIFO order decide. No active ticket is reordered or rewritten.
    """
    import batch_control as batch
    from scheduler_repair import ready as repair_ready
    cache = {}; repair_cache = {}; candidates = []; groups = {}
    local = parent_runtime_scope(settings) and requester_batch_id is not None
    if local:
        requested_binding = verified_binding(root, requester_batch_id, settings, cache)
        requested_group = requested_binding['group'] if requested_binding else None
    for ticket in ready:
        if local:
            binding = verified_binding(root, ticket['batch_id'], settings, cache)
            if (binding['group'] if binding else None) != requested_group: continue
        target, manifest = batch.batch(root, ticket['batch_id'])
        candidate = dict(ticket); candidate['work_kind'] = ticket['stage']
        if ticket['stage'] == 'build':
            state = read_json(target / 'state.json')
            candidate['model_kind'] = 'repair' if state['cases'][ticket['case_id']].get('phase') == 'repairing' else 'build'
            reference = repair_ready(root, manifest, state, ticket['case_id'], settings, repair_cache)
            saved = settings.get('repair_bindings', {}).get(ticket['batch_id'], {}).get(ticket['case_id'])
            if saved and state['cases'][ticket['case_id']].get('phase') == 'repairing' and not reference: continue
            if reference:
                candidate['work_kind'] = 'repair'; candidate['repair_binding'] = reference
            ordinary_builds = sum(q['stage'] == 'build' and q.get('scheduler_admission', {}).get('work_kind') != 'repair' for q in active)
            if settings.get('mode') != ADAPTIVE_CONTRACT and candidate['work_kind'] != 'repair' and ordinary_builds >= settings['capacities']['build']: continue
        limit, available, group = limits(root, manifest, active, ticket['stage'], settings, cache)
        if available and (limit is None or sum(q['stage'] == ticket['stage'] for q in active) < limit):
            candidates.append(candidate); groups[ticket['token']] = group
    if not candidates: return None, None
    if settings.get('mode') == ADAPTIVE_CONTRACT:
        # Other independent parents have their own runtime and selection turn.
        # Never let their idle owner become head-of-line for this requester.
        history = [q for q in pool if active_group(root, q, settings) == requested_group] if local else pool
        return choose_adaptive(candidates, groups, history, settings)
    history = sorted((q for q in pool if q.get('scheduler_admission') and q['stage'] in MODEL_STAGES),
                     key=lambda q: (q['acquired_ns'], q['token']))
    urgent = lambda q: q['priority'] >= 10
    classes = {urgent(q) for q in candidates}
    selected_class = not urgent(history[-1]) if history and len(classes) == 2 else (True if True in classes else False)
    candidates = [q for q in candidates if urgent(q) == selected_class]
    is_repair = lambda q: q.get('work_kind', q.get('scheduler_admission', {}).get('work_kind')) == 'repair'
    kinds = {is_repair(q) for q in candidates}
    class_history = [q for q in history if urgent(q) == selected_class]
    selected_kind = not is_repair(class_history[-1]) if class_history and len(kinds) == 2 else (True if True in kinds else False)
    candidates = [q for q in candidates if is_repair(q) == selected_kind]
    group_last = {}; batch_last = {}
    for ticket in history:
        if urgent(ticket) != selected_class or is_repair(ticket) != selected_kind: continue
        group_last[ticket['scheduler_admission'].get('group')] = ticket['acquired_ns']
        batch_last[ticket['batch_id']] = ticket['acquired_ns']
    chosen = min(candidates, key=lambda q: (group_last.get(groups[q['token']], 0), batch_last.get(q['batch_id'], 0),
                                          -q['priority'], q['submitted_ns'], q['token']))
    return chosen, groups[chosen['token']]
