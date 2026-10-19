"""Freeze evidence that a registered run actually needs independent-review repair."""
import hashlib
import json
import re
from pathlib import Path
import time
import uuid
from common import digest, no_links, read_json, session_filename_matches

CONTRACT = 'verified-review-repair-budget-v1'


class ReviewFreshness:
    """Collect current-attempt facts during existing reads; never reread a log."""
    def __init__(self, reviewer, call_id):
        if not isinstance(reviewer, str) or not reviewer:
            raise ValueError('Actual independent reviewer identity required for FINAL freshness')
        self.reviewer = reviewer; self.call_id = call_id
        self.dispatch_position = -1; self.continuations = []
        self.final = None; self.context = -1; self.started = -1; self.lifecycle = None

    def parent(self, event, position, raw=None):
        payload = event.get('payload', {})
        if event.get('type') != 'response_item': return False
        if payload.get('call_id') == self.call_id and payload.get('type') == 'function_call_output':
            self.dispatch_position = position
        if (payload.get('type') == 'function_call' and
                payload.get('name', '').split('.')[-1] in {'followup_task', 'send_message'}):
            arguments = json.loads(payload.get('arguments', '{}'))
            if arguments.get('target') in {self.reviewer, self.reviewer.rsplit('/', 1)[-1]}:
                self.continuations.append((event.get('timestamp'), position)); return True
        return False

    def child(self, event, position):
        payload = event.get('payload', {})
        if event.get('type') == 'turn_context': self.context = position
        if event.get('type') == 'event_msg' and payload.get('type') in {'task_started', 'task_complete', 'turn_aborted'}:
            self.lifecycle = payload
            if payload.get('type') == 'task_started': self.started = position
        if (event.get('type') == 'response_item' and payload.get('type') == 'message' and payload.get('role') == 'assistant' and
                (payload.get('phase') == 'final_answer' or ('phase' not in payload and payload.get('channel') == 'final'))):
            self.final = (position, event.get('timestamp'))

    def verify(self):
        from contracts import _dispatch_timestamp_ns
        if self.final is None:
            raise ValueError('Actual independent reviewer FINAL required for freshness')
        position, timestamp = self.final
        if (self.context > position or self.started > position or
                (self.lifecycle and (self.lifecycle.get('type') != 'task_complete' or self.lifecycle.get('error')))):
            raise ValueError('Independent review child is live/resumed after the attested FINAL; preserve the original review lease')
        for continued_at, continued_position in self.continuations:
            if continued_position <= self.dispatch_position: continue
            if not timestamp or not continued_at or _dispatch_timestamp_ns(continued_at) >= _dispatch_timestamp_ns(timestamp):
                raise ValueError('Independent review received a later continuation after its attested FINAL; preserve the original review lease')


def chunks(path):
    """Initial evidence read only; saved offsets are used on subsequent admission."""
    from contracts import SESSION_ROOT
    path = no_links(path)
    if no_links(SESSION_ROOT) not in path.parents or path.suffix != '.jsonl': raise ValueError('Repair requires actual Codex review sessions')
    with path.open('rb') as stream:
        while True:
            offset = stream.tell(); raw = stream.readline()
            if not raw: break
            try: event = json.loads(raw)
            except json.JSONDecodeError: continue
            yield event, {'path': str(path), 'offset': offset, 'size': len(raw), 'sha256': hashlib.sha256(raw).hexdigest()}


def authenticate(root, target, manifest, state, case_id, settings, authorization, decision='revise'):
    """Authenticate an existing report and its actual final; never repair its bytes.

    Completion and repair admission share this boundary, including the neutral
    admission/permit metadata that must exist before any review lease release.
    """
    import batch_control as batch
    from scheduler_policy import verified_binding
    from contracts import _dispatch_events, _encrypted_dispatch_message, _encrypted_review_binding
    parent = verified_binding(root, manifest['batch_id'], settings)
    if not parent: raise ValueError('Repair budget requires the verified real controller binding first')
    item = state['cases'][case_id]
    if decision == 'revise' and item.get('phase') != 'repairing': raise ValueError('Repair budget requires the current registered repairing phase')
    completed = [c for c in item.get('calls', []) if c.get('stage') in {'review', 'expedited'} and c.get('status', '').startswith('completed')]
    if not completed or completed[-1].get('status') != 'completed_' + decision or not completed[-1].get('review_evidence'):
        raise ValueError('Actual latest completed independent ' + decision + ' evidence required for review handoff')
    completed = completed[-1]
    dispatched = [c for c in item['calls'] if c.get('call_id') == completed.get('call_id') and c.get('status') == 'dispatched' and c.get('review_session_log')]
    if len(dispatched) != 1: raise ValueError('Exact original independent review dispatch and child log required')
    dispatched = dispatched[0]; case = next(c for c in manifest['cases'] if c['case_id'] == case_id)
    work = no_links(case['workspace']); proof_path = no_links(completed['review_evidence']); proof = read_json(proof_path)
    if not isinstance(proof, dict) or work not in proof_path.parents or digest(proof_path) != completed.get('review_evidence_sha256') or proof.get('decision') != decision:
        raise ValueError('Exact independent ' + decision + ' proof hash inside this case required')
    missing = [key for key in ('review_admission', 'review_dispatch_permit') if not isinstance(proof.get(key), dict)]
    if missing:
        raise ValueError('Independent report missing required neutral metadata: ' + ', '.join(missing) + '; preserve the report and original review lease')
    admission = batch.load_review_admission(work, proof['review_admission'])
    permit = batch.load_review_dispatch_permit(work, proof['review_admission'], proof['review_dispatch_permit'])
    if admission['case_id'] != case_id or admission['batch_id'] != manifest['batch_id'] or proof.get('run_id') != admission['run_id']:
        raise ValueError('Repair evidence belongs to a different registered case/run')
    reviewer = proof.get('reviewer_agent_id'); freshness = ReviewFreshness(reviewer, completed['call_id']); frozen = []
    def observe_parent(event, position, raw):
        continuation = freshness.parent(event, position)
        if event.get('type') == 'session_meta' or event.get('payload', {}).get('call_id') == completed['call_id'] or continuation:
            frozen.append({'path': str(no_links(dispatched['session_log'])), 'offset': position,
                           'size': len(raw), 'sha256': hashlib.sha256(raw).hexdigest()})
    call, result, parent_id = _dispatch_events(dispatched['session_log'], completed['call_id'], observe_parent)
    arguments = json.loads(call['payload']['arguments']); output = result['payload']['output']
    if isinstance(output, str): output = json.loads(output)
    if (parent_id != parent['group'] or call['payload'].get('name', '').split('.')[-1] != 'spawn_agent' or
        arguments.get('fork_turns') != 'none' or arguments.get('model') != admission['model'] or arguments.get('reasoning_effort') != admission['effort'] or
        not isinstance(output, dict) or output.get('task_name') != reviewer or reviewer != completed.get('agent_id') or
        any(output.get(k) for k in ('error', 'isError', 'is_error')) or
        any(c.get('agent_id') == reviewer and c.get('stage', '').startswith(('build', 'repair')) for c in item['calls'])):
        raise ValueError('Repair evidence must come from the actual admitted independent reviewer')
    message = arguments.get('message', '')
    encrypted = _encrypted_dispatch_message(message)
    expected_cipher = _encrypted_review_binding(admission, permit, call, result, parent_id) if encrypted else None
    if encrypted:
        if proof.get('review_dispatch_binding') != expected_cipher: raise ValueError('Repair review cipher binding changed')
    elif (not isinstance(message, str) or admission['token'] not in message or permit['dispatch_nonce'] not in message or
          admission['run_id'] not in message or str(work).casefold() not in message.casefold()):
        raise ValueError('Repair review dispatch must name its actual admission, permit, run and workspace')
    child_chunks = chunks(dispatched['review_session_log']); meta = []; context = None; final = None
    lifecycle = None; latest_started = None
    for event, reference in child_chunks:
        freshness.child(event, reference['offset'])
        payload = event.get('payload', {})
        if event.get('type') == 'session_meta': meta.append((payload, reference))
        if event.get('type') == 'turn_context': context = (payload, reference)
        if event.get('type') == 'event_msg' and payload.get('type') in {'task_started', 'task_complete', 'turn_aborted'}:
            lifecycle = (payload, reference)
            if payload.get('type') == 'task_started': latest_started = reference
        if (event.get('type') == 'response_item' and payload.get('type') == 'message' and payload.get('role') == 'assistant' and
            (payload.get('phase') == 'final_answer' or ('phase' not in payload and payload.get('channel') == 'final'))):
            final = (payload, reference, context, event.get('timestamp'))
    if len(meta) != 1 or not final or not final[2]: raise ValueError('Actual independent reviewer final and model identity required')
    freshness.verify()
    source = meta[0][0].get('source', {})
    spawned = source.get('subagent', {}).get('thread_spawn', {}) if isinstance(source, dict) else {}
    if spawned.get('agent_path') != reviewer or spawned.get('parent_thread_id') != parent_id:
        raise ValueError('Actual review child belongs to a different parent/agent')
    if [final[2][0].get('model'), final[2][0].get('effort')] != [admission['model'], admission['effort']]:
        raise ValueError('Actual repair review final used a different model/effort')
    content = final[0].get('content', [])
    if not content or any(not isinstance(part.get('text'), str) or part.get('encrypted_content') for part in content):
        raise ValueError('Actual independent reviewer final must attest exact revise proof')
    text = ''.join(part['text'] for part in content)
    text = re.sub(r'\s*<oai-mem-citation>[\s\S]*?</oai-mem-citation>\s*$', '', text)
    attestation = json.loads(text)
    if (not isinstance(attestation, dict) or attestation.get('reviewer_agent_id') != reviewer or attestation.get('review_evidence_sha256') != digest(proof_path) or
        ('decision' in attestation and attestation['decision'] != proof['decision']) or
        (encrypted and attestation.get('review_dispatch_binding') != expected_cipher)):
        raise ValueError('Actual independent reviewer final does not attest this exact revise proof')
    frozen.extend([meta[0][1], final[2][1], final[1]])
    if latest_started: frozen.append(latest_started)
    if lifecycle: frozen.append(lifecycle[1])
    binding = {'contract': CONTRACT, 'batch_id': manifest['batch_id'], 'case_id': case_id, 'workspace': str(work), 'run_id': admission['run_id'],
               'manifest_sha256': digest(target / 'manifest.json'), 'source_sha256': case['source_sha256'], 'group': parent_id,
               'proof': {'path': str(proof_path), 'sha256': digest(proof_path)}, 'review_admission': proof['review_admission'],
               'review_dispatch_permit': proof['review_dispatch_permit'], 'session_chunks': frozen, 'bound_ns': time.time_ns(), 'authorization': authorization}
    return binding


def bind(root, target, manifest, state, case_id, settings, authorization):
    binding = authenticate(root, target, manifest, state, case_id, settings, authorization)
    return freeze_binding(target, binding)


def freeze_binding(target, binding):
    import batch_control as batch
    path = target / 'repair-bindings' / (uuid.uuid4().hex + '.json'); batch.new_json(path, binding)
    return {'path': str(path), 'sha256': digest(path)}


def authenticate_exit(root, manifest, state, case_id, settings, entry, dispatched):
    """Prove a terminated attempt, without asserting any product review verdict."""
    import batch_control as batch
    from scheduler_policy import verified_binding
    from contracts import _dispatch_events, _encrypted_dispatch_message, _encrypted_review_binding, _dispatch_timestamp_ns
    parent = verified_binding(root, manifest['batch_id'], settings)
    if not parent: raise ValueError('Review exit requires the verified real controller')
    case = next(c for c in manifest['cases'] if c['case_id'] == case_id); work = no_links(case['workspace'])
    admission = batch.load_review_admission(work, entry['review_admission'])
    permit = batch.load_review_dispatch_permit(work, entry['review_admission'], entry['review_dispatch_permit'])
    call, result, parent_id = _dispatch_events(dispatched['session_log'], dispatched['call_id'])
    arguments = json.loads(call['payload']['arguments']); output = result['payload']['output']
    if isinstance(output, str): output = json.loads(output)
    reviewer = output.get('task_name') if isinstance(output, dict) else None
    if (parent_id != parent['group'] or call['payload'].get('name', '').split('.')[-1] != 'spawn_agent' or
            arguments.get('fork_turns') != 'none' or arguments.get('model') != admission['model'] or
            arguments.get('reasoning_effort') != admission['effort'] or reviewer != dispatched.get('agent_id') or
            any(output.get(k) for k in ('error', 'isError', 'is_error')) or
            any(c.get('agent_id') == reviewer and c.get('stage', '').startswith(('build', 'repair')) for c in state['cases'][case_id]['calls'])):
        raise ValueError('Review exit must belong to the actual admitted independent child')
    message = arguments.get('message', ''); cipher = None
    if _encrypted_dispatch_message(message):
        cipher = _encrypted_review_binding(admission, permit, call, result, parent_id)
    elif (not isinstance(message, str) or admission['token'] not in message or permit['dispatch_nonce'] not in message or
          admission['run_id'] not in message or str(work).casefold() not in message.casefold()):
        raise ValueError('Terminated review dispatch must bind its exact admission/permit/run/workspace')
    meta = []; context = None; terminal = None
    for event, reference in chunks(dispatched['review_session_log']):
        payload = event.get('payload', {})
        if event.get('type') == 'session_meta': meta.append((payload, reference))
        if event.get('type') == 'turn_context': context = (payload, reference)
        if event.get('type') == 'event_msg' and payload.get('type') in {'task_started', 'task_complete', 'turn_aborted'}:
            terminal = (event, reference)
    if len(meta) != 1 or not context or not terminal or terminal[0]['payload']['type'] not in {'task_complete', 'turn_aborted'}:
        raise ValueError('Review child is live/resumed or lacks an actual terminal lifecycle event')
    child_path = no_links(dispatched['review_session_log']); child_meta = meta[0][0]
    spawn = child_meta.get('source', {}).get('subagent', {}).get('thread_spawn', {})
    if (not session_filename_matches(child_path, child_meta.get('id')) or
            spawn.get('agent_path') != reviewer or spawn.get('parent_thread_id') != parent_id or
            [context[0].get('model'), context[0].get('effort')] != [admission['model'], admission['effort']]):
        raise ValueError('Actual terminated review child identity/model changed')
    pending = {}; census = None; resumed_after = False
    for event, reference in chunks(dispatched['session_log']):
        payload = event.get('payload', {})
        if event.get('type') != 'response_item': continue
        if payload.get('type') == 'function_call':
            pending[payload.get('call_id')] = payload
            if census and payload.get('name', '').split('.')[-1] in {'followup_task', 'send_message'}:
                arguments = json.loads(payload.get('arguments', '{}'))
                if arguments.get('target') in {reviewer, reviewer.rsplit('/', 1)[-1]}: resumed_after = True
        if (payload.get('type') != 'function_call_output' or
                pending.get(payload.get('call_id'), {}).get('name', '').split('.')[-1] != 'list_agents'): continue
        rows = payload.get('output'); rows = json.loads(rows) if isinstance(rows, str) else rows
        census = (rows, event, reference); resumed_after = False
    rows, census_event, census_reference = census if census else ({}, {}, {})
    found = [row for row in rows.get('agents', []) if row.get('agent_name') == reviewer]
    status = found[0].get('agent_status') if len(found) == 1 else None
    finished = status in {'completed', 'shutdown', 'interrupted', 'idle', 'errored'} if isinstance(status, str) else (
        isinstance(status, dict) and bool(set(status) & {'completed', 'shutdown', 'interrupted', 'idle', 'errored'}))
    if (not finished or resumed_after or
            _dispatch_timestamp_ns(census_event.get('timestamp')) < _dispatch_timestamp_ns(terminal[0].get('timestamp'))):
        raise ValueError('Latest real agent census must prove the terminated child without later continuation')
    return {'kind': 'authenticated-review-exit', 'reviewer_agent_id': reviewer, 'call_id': dispatched['call_id'],
            'group': parent_id, 'review_admission': entry['review_admission'], 'review_dispatch_permit': entry['review_dispatch_permit'],
            'review_dispatch_binding': cipher, 'session_chunks': [meta[0][1], context[1], terminal[1], census_reference],
            'scope': 'Actual attempt ended; no review decision, viewed coverage or product acceptance is asserted.'}


def ready(root, manifest, state, case_id, settings, cache):
    key = (manifest['batch_id'], case_id)
    if key in cache: return cache[key]
    reference = settings.get('repair_bindings', {}).get(manifest['batch_id'], {}).get(case_id); result = None
    if reference and state['cases'][case_id].get('phase') == 'repairing':
        try:
            import batch_control as batch
            from scheduler_policy import verified_binding
            from contracts import SESSION_ROOT
            target, _ = batch.batch(root, manifest['batch_id']); path = no_links(reference['path'])
            if path.parent != target / 'repair-bindings' or digest(path) != reference['sha256']: raise ValueError('Repair binding changed')
            binding = read_json(path); case = next(c for c in manifest['cases'] if c['case_id'] == case_id); work = no_links(case['workspace'])
            parent = verified_binding(root, manifest['batch_id'], settings)
            latest = [c for c in state['cases'][case_id].get('calls', []) if c.get('stage') in {'review', 'expedited'} and c.get('status', '').startswith('completed')]
            if (not latest or latest[-1].get('status') != 'completed_revise' or latest[-1].get('review_evidence') != binding['proof']['path'] or
                latest[-1].get('review_evidence_sha256') != binding['proof']['sha256']): raise ValueError('Latest repair decision changed')
            if (binding['contract'] != CONTRACT or not parent or binding['group'] != parent['group'] or binding['case_id'] != case_id or
                binding['batch_id'] != manifest['batch_id'] or binding['manifest_sha256'] != digest(target / 'manifest.json') or
                binding['workspace'] != str(work) or binding['run_id'] != read_json(work / '.product-v2/run.json')['run_id'] or
                binding['source_sha256'] != case['source_sha256'] or digest(no_links(binding['proof']['path'])) != binding['proof']['sha256']):
                raise ValueError('Repair binding no longer belongs to this controller/case/run')
            for proof in [binding['review_admission'], binding['review_dispatch_permit']]:
                if digest(no_links(proof['path'])) != proof['sha256']: raise ValueError('Original repair review admission/permit changed')
            for chunk in binding['session_chunks']:
                log = no_links(chunk['path'])
                if no_links(SESSION_ROOT) not in log.parents: raise ValueError('Actual repair review log required')
                with log.open('rb') as stream:
                    stream.seek(chunk['offset'])
                    if hashlib.sha256(stream.read(chunk['size'])).hexdigest() != chunk['sha256']: raise ValueError('Actual repair review evidence changed')
            result = reference
        except (ValueError, OSError, KeyError, TypeError): result = None
    cache[key] = result
    return result
