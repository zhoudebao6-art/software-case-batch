"""Owner-applied pause/resume journal ordered by authentic user event time."""
from datetime import datetime
import hashlib
import json
import time
from common import no_links, read_json

CONTRACT = 'user-event-control-v1'
MAX_FUTURE_SKEW_SECONDS = 300


def user_event(reference):
    from contracts import SESSION_ROOT
    if not isinstance(reference, dict):
        raise ValueError('Control requires a real user_evidence byte-range reference')
    path = no_links(reference.get('path', ''))
    if no_links(SESSION_ROOT) not in path.parents or path.suffix != '.jsonl':
        raise ValueError('Control evidence must be an actual Codex session JSONL')
    offset, size = reference.get('offset'), reference.get('size')
    if type(offset) is not int or offset < 0 or type(size) is not int or not 0 < size <= 1024 * 1024:
        raise ValueError('Bounded actual user event offset/size required')
    with path.open('rb') as stream:
        meta_event = json.loads(stream.readline()); meta = meta_event.get('payload', {})
        if (meta_event.get('type') != 'session_meta' or not meta.get('id') or
                meta.get('thread_source') != 'user' or meta.get('parent_thread_id') or
                isinstance(meta.get('source'), dict) or not path.name.endswith('-' + meta['id'] + '.jsonl')):
            raise ValueError('Control authorization requires an independent real user session')
        if offset:
            stream.seek(offset - 1)
            if stream.read(1) != b'\n':
                raise ValueError('Control byte range must start at an actual event boundary')
        stream.seek(offset); raw = stream.read(size)
    if hashlib.sha256(raw).hexdigest() != reference.get('sha256'):
        raise ValueError('Actual user control evidence changed')
    event = json.loads(raw); payload = event.get('payload', {})
    if (event.get('type') != 'response_item' or payload.get('type') != 'message' or
            payload.get('role') != 'user'):
        raise ValueError('Model text, quoted receipts and tool output are not new user authorization')
    content = payload.get('content', [])
    if not content or any(part.get('type') != 'input_text' or not isinstance(part.get('text'), str) for part in content):
        raise ValueError('Actual plain user instruction required')
    text = '\n'.join(part['text'] for part in content).strip()
    timestamp = event.get('timestamp')
    try:
        moment = datetime.fromisoformat(timestamp.replace('Z', '+00:00'))
        if moment.tzinfo is None: raise ValueError('UTC offset required')
        event_us = int(moment.timestamp() * 1000000)
    except (ValueError, TypeError, AttributeError) as exc:
        raise ValueError('Actual user event timestamp with timezone required') from exc
    if reference.get('timestamp', timestamp) != timestamp:
        raise ValueError('Supplied control timestamp differs from the actual user event')
    if event_us > time.time_ns() // 1000 + MAX_FUTURE_SKEW_SECONDS * 1000000:
        raise ValueError('Actual user control event is in the future beyond the five-minute clock tolerance')
    return {'path': str(path), 'offset': offset, 'size': size, 'sha256': reference['sha256'],
            'timestamp': timestamp, 'event_us': event_us, 'session_id': meta['id'],
            'message_id': payload.get('id'), 'statement_sha256': hashlib.sha256(text.encode()).hexdigest()}, text


def apply(state, batch_id, action, value, authorization):
    if not authorization or not str(authorization).strip():
        raise ValueError('Drain/continue require the existing explicit user request reference')
    latest = state.get('control_decision')
    # Old unversioned batches retain their API. Once real ordering is registered,
    # bare model text cannot replace it; a running continue remains idempotent.
    if value is None:
        if latest:
            user_event(latest['user_evidence'])
            if action == 'continue' and not state['drain']: return
            raise ValueError('Versioned control requires actual user evidence; text cannot supersede the latest user decision')
        state['drain'] = action == 'drain'; state['control_authorization'] = authorization
        return
    request = read_json(value)
    requested_action = request.get('action') if isinstance(request, dict) else None
    if requested_action is None and isinstance(request, dict) and type(request.get('drain')) is bool:
        requested_action = 'drain' if request['drain'] else 'continue'
    if not isinstance(request, dict) or request.get('batch_id') != batch_id or requested_action != action:
        raise ValueError('Control request must bind this registered batch and exact drain/continue action')
    evidence, text = user_event(request.get('user_evidence'))
    statement = request.get('statement', text)
    if not isinstance(statement, str) or statement.strip() != text:
        raise ValueError('Control statement must equal the actual user message')
    if latest:
        saved, _ = user_event(latest['user_evidence'])
        if evidence['event_us'] < saved['event_us']:
            raise ValueError('Stale control instruction superseded by the newer user decision')
        if evidence['event_us'] == saved['event_us']:
            if evidence == saved and action == latest['action']: return
            if (evidence['path'] != saved['path'] or evidence['offset'] <= saved['offset']):
                raise ValueError('Ambiguous or stale control order; use a newer actual user event')
    journal = state.setdefault('control_decisions', [])
    record = {'contract': CONTRACT, 'revision': len(journal) + 1, 'batch_id': batch_id,
              'action': action, 'user_evidence': evidence, 'authorization': str(authorization),
              'applied_ns': time.time_ns(), 'supersedes_revision': latest.get('revision') if latest else None}
    journal.append(record); state['control_decision'] = record
    state['drain'] = action == 'drain'; state['control_authorization'] = authorization
