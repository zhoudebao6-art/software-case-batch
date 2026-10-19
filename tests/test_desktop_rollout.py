"""Desktop continuation filenames preserve exact-file identity and evidence gates."""
import copy
from contextlib import contextmanager
import hashlib
import json
from pathlib import Path
import sys
import unittest
import uuid
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import batch_control as batch
import contracts
import control_decisions
import scheduler_policy as scheduler
import test_capacity_defer as capacity_fixtures
import test_control_decisions as control_fixtures
import test_review_handoff as handoff_fixtures
import test_scheduler_groups as group_fixtures
from common import read_json, session_filename_matches, write_json


@contextmanager
def fixture(kind):
    case = kind(); case.setUp()
    try: yield case
    finally: case.tearDown()


def desktop_path(path):
    return path.with_name(path.stem + '_' + str(uuid.uuid4()) + '.jsonl')


def rename_request_log(request, key):
    value = read_json(request); original = Path(value[key]); renamed = desktop_path(original)
    original.rename(renamed); value[key] = str(renamed); write_json(request, value)
    return renamed


class DesktopRolloutTests(unittest.TestCase):
    def test_legacy_and_desktop_require_canonical_session_and_one_uuid_fragment(self):
        identity = str(uuid.uuid4()); fragment = str(uuid.uuid4())
        for prefix in ('rollout-', 'rollout-test-', 'rollout-2026-10-19T21-34-31-'):
            for suffix in ('', '_' + fragment):
                with self.subTest(prefix=prefix, suffix=suffix):
                    self.assertTrue(session_filename_matches(Path(prefix + identity + suffix + '.jsonl'), identity))
        for name in ('rollout-' + identity + '_arbitrary.jsonl',
                     'rollout-' + identity + '_' + fragment + '_' + fragment + '.jsonl',
                     'rollout-' + identity + '_' + fragment + '-extra.jsonl',
                     'rollout-' + identity + '_' + fragment + '.jsonl.bak',
                     'rollout-' + identity + '_' + fragment.upper() + '.jsonl',
                     'rollout-' + fragment + '_' + identity + '.jsonl',
                     'foreign-' + identity + '.jsonl',
                     'rollout-' + identity.replace('-', '') + '.jsonl'):
            with self.subTest(name=name): self.assertFalse(session_filename_matches(Path(name), identity))
        for invalid in (None, 1, '', 'not-a-uuid', identity.upper(), identity.replace('-', '')):
            with self.subTest(identity=invalid):
                self.assertFalse(session_filename_matches(Path('rollout-' + str(invalid) + '.jsonl'), invalid))

    def test_controller_desktop_fragment_binds_and_rechecks_same_bounded_evidence(self):
        with fixture(group_fixtures.SchedulerGroupsTests) as f:
            f.create('a'); request = f.request('a', 'A'); log = rename_request_log(request, 'session_log')
            runtime = {'type': 'response_item', 'payload': {'type': 'message', 'role': 'developer',
                'internal_chat_message_metadata_passthrough': {'content_item_kinds': ['multi_agent.role_instructions']},
                'content': [{'type': 'input_text', 'text': '<multi_agent_role>There are 4 available concurrency slots, meaning that up to 4 agents can be active at once, including you.</multi_agent_role>'}]}}
            with log.open('a', encoding='utf-8') as stream: stream.write(json.dumps(runtime) + '\n')
            settings = f.call('a', 'bind-controller', value=request, authorization='fixture Desktop compatibility')
            binding = scheduler.verified_binding(f.pool, 'a', settings)
            self.assertEqual(binding['proof']['session_log'], str(log))
            self.assertEqual(binding['runtime_capacity']['worker_capacity'], 3)
            original = log.read_bytes()
            for section in ('proof', 'runtime_capacity'):
                with self.subTest(section=section):
                    frozen = binding[section]; changed = bytearray(original)
                    changed[frozen['event_offset'] + frozen['event_size'] - 2] ^= 1
                    log.write_bytes(changed)
                    self.assertIsNone(scheduler.verified_binding(f.pool, 'a', settings))
                    log.write_bytes(original)
            changed = bytearray(original); changed[10] ^= 1; log.write_bytes(changed)
            self.assertIsNone(scheduler.verified_binding(f.pool, 'a', settings))

    def test_controller_desktop_name_does_not_relax_root_owner_or_parent_identity(self):
        with fixture(group_fixtures.SchedulerGroupsTests) as f:
            f.create('a'); request = f.request('a', 'A'); log = rename_request_log(request, 'session_log')
            request = read_json(request); original = [json.loads(line) for line in log.read_text().splitlines()]
            faults = [('id', str(uuid.uuid4())), ('session_id', str(uuid.uuid4())),
                      ('parent_thread_id', str(uuid.uuid4())), ('thread_source', 'subagent'),
                      ('source', {'subagent': {'thread_spawn': {'parent_thread_id': request['session_id']}}})]
            for key, value in faults:
                with self.subTest(meta_field=key):
                    events = copy.deepcopy(original); events[0]['payload'][key] = value
                    log.write_text(''.join(json.dumps(e) + '\n' for e in events))
                    with self.assertRaisesRegex(ValueError, 'independent user parent'):
                        scheduler.session_proof(f.pool, 'a', 101, request)
            log.write_text(''.join(json.dumps(e) + '\n' for e in original))
            for root, batch_id, pid in ((f.root / 'foreign', 'a', 101), (f.pool, 'b', 101), (f.pool, 'a', 202)):
                with self.subTest(root=root, batch=batch_id, owner=pid):
                    with self.assertRaisesRegex(ValueError, 'No actual successful'):
                        scheduler.session_proof(root, batch_id, pid, request)
            for key, value in (('exit_code', 1), ('status', 'failed'), ('aggregated_output', 'ERROR: rejected')):
                with self.subTest(command_field=key):
                    events = copy.deepcopy(original); events[1]['payload']['item'][key] = value
                    log.write_text(''.join(json.dumps(e) + '\n' for e in events))
                    with self.assertRaisesRegex(ValueError, 'No actual successful'):
                        scheduler.session_proof(f.pool, 'a', 101, request)

    def test_controller_never_uses_another_fragment_or_external_copy(self):
        with fixture(group_fixtures.SchedulerGroupsTests) as f:
            f.create('a'); request_path = f.request('a', 'A'); original = Path(read_json(request_path)['session_log'])
            request = read_json(request_path); other = desktop_path(original)
            other.write_bytes(original.read_bytes().splitlines(keepends=True)[0])
            request['session_log'] = str(other)
            with self.assertRaisesRegex(ValueError, 'No actual successful'):
                scheduler.session_proof(f.pool, 'a', 101, request)
            outside = f.root / original.name; outside.write_bytes(original.read_bytes()); request['session_log'] = str(outside)
            with self.assertRaisesRegex(ValueError, 'actual Codex session'):
                scheduler.session_proof(f.pool, 'a', 101, request)

    def test_control_desktop_fragment_preserves_user_role_root_and_event_hash(self):
        with fixture(control_fixtures.ControlDecisionTests) as f:
            request = f.instruction('continue', '2026-10-15T02:00:00Z'); value = read_json(request)
            original = Path(value['user_evidence']['path']); log = desktop_path(original); original.rename(log)
            reference = value['user_evidence']; reference['path'] = str(log)
            evidence, text = control_decisions.user_event(reference)
            self.assertEqual(evidence['path'], str(log)); self.assertEqual(text, value['statement'])
            raw = log.read_bytes()
            changed = copy.deepcopy(reference); changed['sha256'] = '0' * 64
            with self.assertRaisesRegex(ValueError, 'evidence changed'): control_decisions.user_event(changed)
            outside = f.root / log.name; outside.write_bytes(raw); changed['path'] = str(outside)
            with self.assertRaisesRegex(ValueError, 'actual Codex session'): control_decisions.user_event(changed)
            meta, event = [json.loads(line) for line in raw.splitlines()]
            meta['payload']['parent_thread_id'] = str(uuid.uuid4())
            log.write_text(json.dumps(meta) + '\n' + json.dumps(event) + '\n')
            with self.assertRaisesRegex(ValueError, 'independent real user'): control_decisions.user_event(reference)

    def test_capacity_parent_and_child_desktop_fragments_keep_exact_dispatch_and_census(self):
        with fixture(capacity_fixtures.CapacityTests) as f:
            active = f.active(); request = f.attempt(active, child=True)
            parent = rename_request_log(request, 'session_log'); child = rename_request_log(request, 'child_session_log')
            result = f.defer(active, request)
            proof = result['capacity_retry']['proof']
            self.assertEqual(proof['session_log'], str(parent))
            self.assertEqual(proof['child_terminal']['session_log'], str(child))
            self.assertEqual(result['status'], 'waiting')

    def test_capacity_desktop_fragment_rejects_wrong_identity_suffix_or_foreign_parent(self):
        with fixture(capacity_fixtures.CapacityTests) as f:
            active = f.active(); request = f.attempt(active, child=True)
            parent = rename_request_log(request, 'session_log'); child = rename_request_log(request, 'child_session_log')
            original_request = read_json(request); original_child = child.read_bytes()
            events = [json.loads(line) for line in original_child.splitlines()]
            for fault in ('identity', 'parent', 'suffix', 'outside'):
                with self.subTest(fault=fault):
                    value = copy.deepcopy(original_request); changed = copy.deepcopy(events)
                    if fault == 'identity': changed[0]['payload']['id'] = str(uuid.uuid4())
                    if fault == 'parent': changed[0]['payload']['source']['subagent']['thread_spawn']['parent_thread_id'] = str(uuid.uuid4())
                    if fault in ('suffix', 'outside'):
                        target = (f.sessions if fault == 'suffix' else f.root) / (child.stem + '_extra.jsonl' if fault == 'suffix' else child.name)
                        target.write_bytes(original_child); value['child_session_log'] = str(target)
                    else: child.write_text(''.join(json.dumps(e) + '\n' for e in changed))
                    write_json(request, value)
                    with self.assertRaises(ValueError): f.defer(active, request)
                    self.assertEqual(read_json(f.pool / 'queue.json')[0]['status'], 'active')
                    child.write_bytes(original_child)
            wrong = parent.with_name(parent.stem + '_invalid.jsonl'); parent.rename(wrong)
            value = copy.deepcopy(original_request); value['session_log'] = str(wrong); write_json(request, value)
            with self.assertRaisesRegex(ValueError, 'filename identity'): f.defer(active, request)

    def test_review_exit_desktop_child_keeps_parent_identity_and_terminal_requirements(self):
        with fixture(handoff_fixtures.ReviewHandoffTests) as f:
            facts = f.ended_attempt(); child = facts['child_log']; renamed = desktop_path(child); child.rename(renamed)
            state_path = f.pool / 'a/state.json'; state = read_json(state_path)
            for call in state['cases']['0']['calls']:
                if call.get('review_session_log') == str(child): call['review_session_log'] = str(renamed)
            write_json(state_path, state); original = renamed.read_bytes()
            events = [json.loads(line) for line in original.splitlines()]
            events[0]['payload']['source']['subagent']['thread_spawn']['parent_thread_id'] = str(uuid.uuid4())
            renamed.write_text(''.join(json.dumps(e) + '\n' for e in events))
            with self.assertRaisesRegex(ValueError, 'identity/model changed'): f.complete(facts)
            self.assertEqual(next(q for q in read_json(f.pool / 'queue.json') if q['token'] == facts['review']['token'])['status'], 'active')
            renamed.write_bytes(original); result = f.complete(facts)
            self.assertEqual(result['status'], 'released')
            self.assertEqual(result['review_completion']['outcome'], 'diagnostic')
            self.assertNotIn('decision', result['review_completion'])

    def test_contract_dispatch_reads_only_requested_desktop_fragment_without_stitching(self):
        with fixture(group_fixtures.SchedulerGroupsTests) as f:
            identity = str(uuid.uuid4()); base = f.sessions / ('rollout-' + identity + '.jsonl')
            first = desktop_path(base); second = desktop_path(base)
            meta = {'type': 'session_meta', 'payload': {'id': identity}}
            call = {'type': 'response_item', 'payload': {'type': 'function_call', 'call_id': 'dispatch', 'name': 'spawn_agent'}}
            result = {'type': 'response_item', 'payload': {'type': 'function_call_output', 'call_id': 'dispatch', 'output': '{}'}}
            first.write_text(''.join(json.dumps(e) + '\n' for e in (meta, call)))
            second.write_text(''.join(json.dumps(e) + '\n' for e in (meta, result)))
            for log in (first, second):
                with self.assertRaisesRegex(ValueError, 'One actual dispatch'):
                    contracts._dispatch_events(log, 'dispatch')
            first.write_text(''.join(json.dumps(e) + '\n' for e in (meta, call, result)))
            self.assertEqual(contracts._dispatch_events(first, 'dispatch'), (call, result, identity))
            outside = f.root / first.name; outside.write_bytes(first.read_bytes())
            with self.assertRaisesRegex(ValueError, 'actual Codex session'):
                contracts._dispatch_events(outside, 'dispatch')


if __name__ == '__main__': unittest.main()
