"""Independent result authentication must precede original review lease release."""
import copy
import json
from pathlib import Path
import unittest
from unittest.mock import patch
import test_scheduler_repair as helpers
import scheduler_repair
from common import digest, read_json, write_json
from review_packet import admitted_metadata, current_admitted_metadata


class ReviewHandoffTests(unittest.TestCase):
    for _name in ('setUp', 'tearDown', 'call', 'create', 'request', 'bind', 'queue', 'acquire', 'release', 'configure', 'revise'):
        locals()[_name] = getattr(helpers.RepairBudgetTests, _name)

    def ready(self):
        self.create('a', 'a'); self.configure(); facts = self.revise('a', 0, bind=False)
        pool = read_json(self.pool / 'queue.json')
        ticket = next(q for q in pool if q['token'] == facts['review']['token'])
        ticket['status'] = 'active'; ticket.pop('released_ns', None); write_json(self.pool / 'queue.json', pool)
        facts['request'] = self.root / 'completion.json'
        write_json(facts['request'], {'review_evidence': str(facts['proof']), 'review_evidence_sha256': digest(facts['proof'])})
        return facts

    def complete(self, facts):
        return self.call('a', 'complete-review', '0', token=facts['review']['token'],
                         value=facts['request'], authorization='existing authorized batch workflow')

    def ended_attempt(self, outcome='diagnostic', preserve_result=False):
        facts = self.ready(); state_path = self.pool / 'a/state.json'; state = read_json(state_path)
        if not preserve_result:
            state['cases']['0']['calls'] = [c for c in state['cases']['0']['calls'] if not c.get('status', '').startswith('completed')]
        write_json(state_path, state)
        write_json(facts['request'], {'outcome': outcome, 'reason': 'actual safe diagnostic/stop end, review incomplete'})
        terminal = {'timestamp': '2026-10-15T10:00:00Z', 'type': 'event_msg', 'payload': {'type': 'task_complete'}}
        with facts['child_log'].open('a') as stream: stream.write(json.dumps(terminal) + '\n')
        agent = read_json(facts['proof'])['reviewer_agent_id']
        census = [{'type': 'response_item', 'timestamp': '2026-10-15T10:00:01Z',
                   'payload': {'type': 'function_call', 'name': 'collaboration.list_agents', 'call_id': 'exit-census', 'arguments': '{}'}},
                  {'type': 'response_item', 'timestamp': '2026-10-15T10:00:02Z',
                   'payload': {'type': 'function_call_output', 'call_id': 'exit-census',
                               'output': json.dumps({'agents': [{'agent_name': agent, 'agent_status': 'completed'}]})}}]
        with facts['parent_log'].open('a') as stream: stream.write(''.join(json.dumps(e) + '\n' for e in census))
        return facts

    def test_admitted_metadata_is_neutral_and_binds_exact_current_ticket(self):
        facts = self.ready(); work = facts['proof'].parents[1]
        value = admitted_metadata(work, self.pool, 'a', facts['review']['token'])
        self.assertEqual(value['review_admission'], facts['review']['review_admission'])
        self.assertEqual(value['review_dispatch_permit'], read_json(facts['proof'])['review_dispatch_permit'])
        self.assertEqual(current_admitted_metadata(work), value)
        self.assertNotIn('decision', value); self.assertNotIn('reviewer_agent_id', value)
        with self.assertRaisesRegex(ValueError, 'different workspace'):
            admitted_metadata(self.root / 'a-1', self.pool, 'a', facts['review']['token'])

    def test_missing_admission_is_clear_failure_and_original_review_slot_stays_active(self):
        facts = self.ready(); proof = read_json(facts['proof']); proof.pop('review_admission'); write_json(facts['proof'], proof)
        write_json(facts['request'], {'review_evidence': str(facts['proof']), 'review_evidence_sha256': digest(facts['proof'])})
        state_path = self.pool / 'a/state.json'; state = read_json(state_path)
        state['cases']['0']['calls'][-1]['review_evidence_sha256'] = digest(facts['proof']); write_json(state_path, state)
        before = {p: p.read_bytes() for p in (facts['proof'], state_path, self.pool / 'queue.json')}
        with self.assertRaisesRegex(ValueError, 'missing or mismatched review_admission'): self.complete(facts)
        with self.assertRaisesRegex(ValueError, 'complete-review'):
            self.release(facts['review'])
        with self.assertRaisesRegex(ValueError, 'missing required neutral metadata'):
            self.call('a', 'bind-repair', '0', value=facts['request'], authorization='real revise')
        self.assertEqual(before, {p: p.read_bytes() for p in before})

    def test_authentic_revise_is_bound_and_recorded_before_release_without_changing_proof(self):
        facts = self.ready(); original = facts['proof'].read_bytes()
        result = self.complete(facts)
        self.assertEqual(result['status'], 'released')
        self.assertEqual(result['review_completion']['decision'], 'revise')
        binding = result['review_completion']['repair_binding']; self.assertTrue(Path(binding['path']).is_file())
        settings = read_json(self.pool / 'scheduler-config.json'); state = read_json(self.pool / 'a/state.json')
        self.assertEqual(settings['repair_bindings']['a']['0'], binding)
        self.assertEqual(scheduler_repair.ready(self.pool, read_json(self.pool / 'a/manifest.json'), state, '0', settings, {}), binding)
        self.assertEqual(facts['proof'].read_bytes(), original)
        self.assertEqual(self.complete(facts), result)
        self.assertEqual(self.acquire(self.queue('a', 0))['work_kind'], 'repair')

    def test_wrong_independent_final_never_releases_or_changes_state(self):
        facts = self.ready(); events = [json.loads(line) for line in facts['child_log'].read_text().splitlines()]
        attestation = json.loads(events[-1]['payload']['content'][0]['text']); attestation['review_evidence_sha256'] = '0' * 64
        events[-1]['payload']['content'][0]['text'] = json.dumps(attestation)
        facts['child_log'].write_text(''.join(json.dumps(e) + '\n' for e in events))
        paths = (self.pool / 'a/state.json', self.pool / 'queue.json', facts['proof'])
        before = {p: p.read_bytes() for p in paths}
        with self.assertRaisesRegex(ValueError, 'does not attest'): self.complete(facts)
        self.assertEqual(before, {p: p.read_bytes() for p in paths})

    def test_authentic_pass_records_only_existing_reviewer_result_without_repair_budget_or_delivery(self):
        facts = self.ready(); proof = read_json(facts['proof']); proof['decision'] = 'pass'; write_json(facts['proof'], proof)
        write_json(facts['request'], {'review_evidence': str(facts['proof']), 'review_evidence_sha256': digest(facts['proof'])})
        state_path = self.pool / 'a/state.json'; state = read_json(state_path)
        completed = state['cases']['0']['calls'][-1]
        completed.update(status='completed_pass', review_evidence_sha256=digest(facts['proof']))
        write_json(state_path, state)
        events = [json.loads(line) for line in facts['child_log'].read_text().splitlines()]
        attestation = json.loads(events[-1]['payload']['content'][0]['text'])
        attestation.update(decision='pass', review_evidence_sha256=digest(facts['proof']))
        events[-1]['payload']['content'][0]['text'] = json.dumps(attestation)
        facts['child_log'].write_text(''.join(json.dumps(e) + '\n' for e in events))
        original = facts['proof'].read_bytes(); result = self.complete(facts)
        self.assertEqual(result['status'], 'released'); self.assertIsNone(result['review_completion']['repair_binding'])
        item = read_json(state_path)['cases']['0']
        self.assertEqual(item['phase'], 'waiting_review'); self.assertEqual(item['review_result']['decision'], 'pass')
        self.assertFalse((facts['proof'].parents[0] / 'final-receipt.json').exists())
        self.assertEqual(facts['proof'].read_bytes(), original)

    def test_persistence_failure_preserves_lease_and_exact_retry_completes(self):
        facts = self.ready(); queue_path = self.pool / 'queue.json'; original_queue = queue_path.read_bytes()
        actual_write = write_json
        def failed(path, value):
            if Path(path) == queue_path: raise OSError('fixture final queue replacement failure')
            return actual_write(path, value)
        with patch('common.write_json', side_effect=failed):
            with self.assertRaisesRegex(OSError, 'queue replacement'): self.complete(facts)
        self.assertEqual(queue_path.read_bytes(), original_queue)
        self.assertEqual(self.complete(facts)['status'], 'released')

    def test_diagnostic_terminal_releases_without_fabricating_a_review_decision(self):
        facts = self.ended_attempt(); original = facts['proof'].read_bytes(); result = self.complete(facts)
        self.assertEqual(result['status'], 'released'); self.assertEqual(result['review_completion']['outcome'], 'diagnostic')
        self.assertNotIn('decision', result['review_completion']); self.assertNotIn('repair_binding', result['review_completion'])
        item = read_json(self.pool / 'a/state.json')['cases']['0']
        self.assertEqual(item['calls'][-1]['status'], 'completed_diagnostic'); self.assertEqual(item['phase'], 'waiting_review')
        self.assertEqual(facts['proof'].read_bytes(), original); self.assertEqual(self.complete(facts), result)
        self.assertEqual(self.queue('a', 0, stage='review')['status'], 'waiting')

    def test_cancellation_requires_existing_authorized_drain_and_true_terminal_child(self):
        facts = self.ended_attempt('cancelled')
        with self.assertRaisesRegex(ValueError, 'authorized drain'): self.complete(facts)
        self.call('a', 'drain', authorization='existing explicit user stop')
        self.assertEqual(self.complete(facts)['review_completion']['outcome'], 'cancelled')
        self.assertTrue(read_json(self.pool / 'a/state.json')['drain'])

    def test_authorized_stop_preserves_preexisting_independent_result_and_ends_only_attempt(self):
        facts = self.ended_attempt('cancelled', preserve_result=True)
        state_path = self.pool / 'a/state.json'; original = read_json(state_path)['cases']['0']['calls'][-1]
        proof_before = facts['proof'].read_bytes()
        self.call('a', 'drain', authorization='existing explicit user stop')
        result = self.complete(facts); calls = read_json(state_path)['cases']['0']['calls']
        self.assertEqual(result['status'], 'released'); self.assertIn(original, calls)
        self.assertEqual(calls[-1]['status'], 'attempt_exit_cancelled'); self.assertEqual(facts['proof'].read_bytes(), proof_before)

    def test_resumed_or_running_review_cannot_release_as_diagnostic(self):
        facts = self.ended_attempt(); queue_before = (self.pool / 'queue.json').read_bytes()
        continuation = {'type': 'response_item', 'timestamp': '2026-10-15T10:00:03Z',
            'payload': {'type': 'function_call', 'name': 'collaboration.followup_task', 'call_id': 'resume-after-census',
                        'arguments': json.dumps({'target': read_json(facts['proof'])['reviewer_agent_id'], 'message': 'continue'})}}
        with facts['parent_log'].open('a') as stream: stream.write(json.dumps(continuation) + '\n')
        with self.assertRaisesRegex(ValueError, 'without later continuation'): self.complete(facts)
        self.assertEqual((self.pool / 'queue.json').read_bytes(), queue_before)
        with facts['child_log'].open('a') as stream:
            stream.write(json.dumps({'type': 'event_msg', 'payload': {'type': 'task_started'}}) + '\n')
        with self.assertRaisesRegex(ValueError, 'live/resumed'): self.complete(facts)
        self.assertEqual((self.pool / 'queue.json').read_bytes(), queue_before)

    def test_old_final_cannot_complete_after_child_restarts_even_if_it_stops_without_a_new_final(self):
        facts = self.ready(); original_state = (self.pool / 'a/state.json').read_bytes()
        original_queue = (self.pool / 'queue.json').read_bytes(); original_proof = facts['proof'].read_bytes()
        with facts['child_log'].open('a') as stream:
            stream.write(json.dumps({'type': 'event_msg', 'payload': {'type': 'task_started'}}) + '\n')
        with self.assertRaisesRegex(ValueError, 'live/resumed after'): self.complete(facts)
        with facts['child_log'].open('a') as stream:
            stream.write(json.dumps({'type': 'event_msg', 'payload': {'type': 'task_complete'}}) + '\n')
        with self.assertRaisesRegex(ValueError, 'live/resumed after'): self.complete(facts)
        self.assertEqual((self.pool / 'a/state.json').read_bytes(), original_state)
        self.assertEqual((self.pool / 'queue.json').read_bytes(), original_queue)
        self.assertEqual(facts['proof'].read_bytes(), original_proof)

    def test_parent_followup_or_message_after_final_cannot_complete_the_old_report(self):
        facts = self.ready(); parent_before = facts['parent_log'].read_bytes(); original_queue = (self.pool / 'queue.json').read_bytes()
        for tool in ('followup_task', 'send_message'):
            with self.subTest(tool=tool):
                event = {'type': 'response_item', 'timestamp': '2026-10-15T10:00:03Z', 'payload': {
                    'type': 'function_call', 'name': 'collaboration.' + tool, 'call_id': 'later-' + tool,
                    'arguments': json.dumps({'target': read_json(facts['proof'])['reviewer_agent_id'], 'message': 'continue verification'})}}
                facts['parent_log'].write_bytes(parent_before + (json.dumps(event) + '\n').encode())
                with self.assertRaisesRegex(ValueError, 'later continuation'): self.complete(facts)
                self.assertEqual((self.pool / 'queue.json').read_bytes(), original_queue)

    def test_legitimate_continuation_can_complete_with_its_fresh_final_and_terminal_lifecycle(self):
        facts = self.ready(); proof_before = facts['proof'].read_bytes()
        agent = read_json(facts['proof'])['reviewer_agent_id']
        parent_event = {'type': 'response_item', 'timestamp': '2026-10-15T10:00:00Z', 'payload': {
            'type': 'function_call', 'name': 'collaboration.followup_task', 'call_id': 'fresh-followup',
            'arguments': json.dumps({'target': agent, 'message': 'finish actual verification'})}}
        with facts['parent_log'].open('a') as stream: stream.write(json.dumps(parent_event) + '\n')
        original_final = json.loads(facts['child_log'].read_text().splitlines()[-1])
        original_final['timestamp'] = '2026-10-15T10:00:03Z'
        events = [{'type': 'event_msg', 'timestamp': '2026-10-15T10:00:01Z', 'payload': {'type': 'task_started'}},
                  {'type': 'turn_context', 'timestamp': '2026-10-15T10:00:02Z', 'payload': {'model': 'gpt-6.1-sol', 'effort': 'ultra'}},
                  original_final,
                  {'type': 'event_msg', 'timestamp': '2026-10-15T10:00:04Z', 'payload': {'type': 'task_complete'}}]
        with facts['child_log'].open('a') as stream: stream.write(''.join(json.dumps(e) + '\n' for e in events))
        self.assertEqual(self.complete(facts)['status'], 'released')
        self.assertEqual(facts['proof'].read_bytes(), proof_before)


if __name__ == '__main__': unittest.main()
