"""Opt-in live-safe controller groups; no dispatch, process changes or case writes."""
import hashlib
import json
from pathlib import Path
import re
import time
import uuid
from copy import deepcopy
from common import digest, no_links, read_json, write_json

CONTRACT = 'verified-controller-fair-v1'
DEFAULT_CAPACITIES = {'build': 8, 'review': 3, 'expedited': 1}
MAX_CAPACITIES = {'build': 8, 'review': 8, 'expedited': 4}
MODEL_STAGES = set(DEFAULT_CAPACITIES)


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


def session_proof(root, batch_id, pid, request):
    """Only a registered owner's completed controller command proves association.

    SESSION_ROOT is the same authoritative JSONL store used by model contracts.
    A supplied name, shared app-server PID, quoted message or foreign batch log
    cannot create an independent group. Append-only offsets allow cheap rechecks.
    """
    from contracts import SESSION_ROOT
    path = no_links(request['session_log']); session_id = str(uuid.UUID(request['session_id']))
    if no_links(SESSION_ROOT) not in path.parents or not path.name.endswith('-' + session_id + '.jsonl'):
        raise ValueError('Controller requires actual Codex session JSONL and filename identity')
    with path.open('rb') as stream:
        raw_meta = stream.readline(); meta_event = json.loads(raw_meta)
        meta = meta_event.get('payload', {})
        if (meta_event.get('type') != 'session_meta' or meta.get('id') != session_id or
            meta.get('session_id', session_id) != session_id or meta.get('thread_source') != 'user' or
            meta.get('parent_thread_id') or isinstance(meta.get('source'), dict)):
            raise ValueError('Controller requires an actual independent user parent session identity')
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
                binding['manifest_sha256'] != digest(target / 'manifest.json') or
                binding['owner'] != read_json(target / 'owner.json') or batch.identity(binding['owner']['pid']) != binding['owner'] or
                no_links(SESSION_ROOT) not in log.parents or not log.name.endswith('-' + proof['session_id'] + '.jsonl')):
                raise ValueError('Controller binding identity changed')
            with log.open('rb') as stream:
                if hashlib.sha256(stream.readline()).hexdigest() != proof['meta_sha256']: raise ValueError('Session identity changed')
                stream.seek(proof['event_offset'])
                if hashlib.sha256(stream.read(proof['event_size'])).hexdigest() != proof['event_sha256']: raise ValueError('Session association changed')
            result = binding
        except (ValueError, OSError, KeyError, TypeError):
            result = None  # Changed binding never creates capacity; it falls back conservatively.
    cache[batch_id] = result
    return result


def control(root, target, manifest, pid, action, value, authorization, pool, case_id=None):
    """Called under batch_control's existing shared transaction/owner check."""
    import batch_control as batch
    if not authorization or not authorization.strip(): raise ValueError('Explicit current scheduling authorization reference required')
    settings = config(root); previous = deepcopy({key: settings.get(key) for key in ('mode', 'capacities', 'bindings', 'active_groups', 'repair_extra_capacity', 'repair_bindings')})
    if action == 'configure-scheduler':
        update = read_json(value)
        if update.get('mode') not in {'legacy', CONTRACT}: raise ValueError('Unknown scheduling policy; use verified-controller-fair-v1 or legacy')
        capacities = dict(DEFAULT_CAPACITIES); capacities.update(update.get('capacities', {}))
        if set(capacities) != MODEL_STAGES or any(type(v) is not int or v < 1 or v > MAX_CAPACITIES[k] for k, v in capacities.items()):
            raise ValueError('Bounded model capacities required: build<=8 review<=8 expedited<=4')
        extra = update.get('repair_extra_capacity', 0)
        if type(extra) is not int or not 0 <= extra <= 2: raise ValueError('Verified repair extra capacity must be 0, 1 or 2')
        settings.update(mode=update['mode'], capacities=capacities, repair_extra_capacity=extra)
    elif action == 'bind-controller':
        request = read_json(value); proof = session_proof(root, manifest['batch_id'], pid, request)
        if 'worker_capacity' in request and request['worker_capacity'] != min(3, manifest['execution_profile']['worker_capacity']):
            raise ValueError('Controller capacity is derived from the frozen host and capped at three; it cannot be supplied')
        group = proof['session_id']; active_groups = settings.setdefault('active_groups', {})
        for ticket in pool:
            if ticket['batch_id'] != manifest['batch_id'] or ticket['status'] != 'active': continue
            recorded = ticket.get('scheduler_admission', {}).get('group') or active_groups.get(ticket['token'])
            if recorded and recorded != group: raise ValueError('Active reservations cannot move to a different controller group')
        binding = {'contract': CONTRACT, 'root': str(no_links(root)), 'batch_id': manifest['batch_id'],
                   'manifest_sha256': digest(target / 'manifest.json'), 'owner': batch.identity(pid), 'proof': proof,
                   'group': group, 'worker_capacity': min(3, manifest['execution_profile']['worker_capacity']),
                   'bound_ns': time.time_ns(), 'authorization': authorization}
        path = target / 'scheduler-bindings' / (uuid.uuid4().hex + '.json')
        batch.new_json(path, binding)
        settings.setdefault('bindings', {})[manifest['batch_id']] = {'path': str(path), 'sha256': digest(path)}
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


def limits(root, manifest, active, stage, settings, cache):
    import batch_control as batch
    binding = verified_binding(root, manifest['batch_id'], settings, cache)
    group = binding['group'] if binding else None
    workers = binding['worker_capacity'] if binding else min(3, manifest['execution_profile']['worker_capacity'])
    profiles = [manifest['execution_profile']]; count = 0
    for ticket in active:
        live_group = active_group(root, ticket, settings)
        # Unidentified active work may belong to ANY known group: reserve it in
        # each group until a verified binding exists. Never multiply batch count.
        if group is None or live_group is None or live_group == group:
            profile = batch.batch(root, ticket['batch_id'])[1]['execution_profile']; profiles.append(profile)
            if ticket['stage'] in MODEL_STAGES or profile.get('resource_accounting') != 'separate-model-media-v1': count += 1
            workers = min(workers, min(3, profile['worker_capacity']))
    # All bindings for one real session share its lowest frozen worker allowance.
    if group:
        for batch_id in settings.get('bindings', {}):
            other = verified_binding(root, batch_id, settings, cache)
            if other and other['group'] == group: workers = min(workers, other['worker_capacity'])
    limit = settings['capacities'][stage] + (settings.get('repair_extra_capacity', 0) if stage == 'build' else 0)
    return limit, count < workers, group


def choose(root, ready, active, pool, settings):
    """Filter before class/group/batch arbitration; unused shares are immediately lent.

    With both classes continuously eligible, admissions alternate (urgent first).
    Within a class, least-recently-served real group and batch rotate, then priority
    and immutable FIFO order decide. No active ticket is reordered or rewritten.
    """
    import batch_control as batch
    from scheduler_repair import ready as repair_ready
    cache = {}; repair_cache = {}; candidates = []; groups = {}
    for ticket in ready:
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
            if candidate['work_kind'] != 'repair' and ordinary_builds >= settings['capacities']['build']: continue
        limit, available, group = limits(root, manifest, active, ticket['stage'], settings, cache)
        if available and sum(q['stage'] == ticket['stage'] for q in active) < limit:
            candidates.append(candidate); groups[ticket['token']] = group
    if not candidates: return None, None
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
