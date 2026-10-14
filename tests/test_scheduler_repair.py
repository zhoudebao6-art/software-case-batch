"""Extra repair budget requires actual independent revise provenance, never labels."""
import copy
import hashlib
import json
from pathlib import Path
import unittest
import uuid
import test_scheduler_groups as helpers
import batch_control as batch
import scheduler_policy as scheduler
from common import digest, read_json, write_json


class RepairBudgetTests(unittest.TestCase):
    setUp = helpers.SchedulerGroupsTests.setUp
    tearDown = helpers.SchedulerGroupsTests.tearDown
    call = helpers.SchedulerGroupsTests.call
    create = helpers.SchedulerGroupsTests.create
    request = helpers.SchedulerGroupsTests.request
    bind = helpers.SchedulerGroupsTests.bind
    queue = helpers.SchedulerGroupsTests.queue
    acquire = helpers.SchedulerGroupsTests.acquire
    release = helpers.SchedulerGroupsTests.release
    fill = helpers.SchedulerGroupsTests.fill

    def configure(self, name='a', extra=2):
        request = self.root / 'config.json'; write_json(request, {'mode': scheduler.CONTRACT, 'capacities': {'build': 8, 'review': 4, 'expedited': 4}, 'repair_extra_capacity': extra})
        return self.call(name, 'configure-scheduler', value=request, authorization='fixture explicit repair capacity authorization')

    def revise(self, name, case_id=0, bind=True):
        case_id = str(case_id); review = self.acquire(self.queue(name, case_id, stage='review'))
        work = Path(read_json(self.pool / name / 'manifest.json')['cases'][int(case_id)]['workspace'])
        permit = self.call(name, 'verify-review', case_id, token=review['token'], value=work)
        source_id, parent_log = self.logs[name]; child_id = str(uuid.uuid4()); reviewer = '/root/' + name + '-review-' + case_id
        proof_path = work / '.product-v2/revise.json'; proof = {'run_id': name + '-' + case_id, 'decision': 'revise', 'reviewer_agent_id': reviewer,
            'review_admission': review['review_admission'], 'review_dispatch_permit': permit['review_dispatch_permit'], 'findings': ['actual fixture content defect']}
        write_json(proof_path, proof); call_id = 'review-' + uuid.uuid4().hex
        arguments = {'fork_turns': 'none', 'model': 'gpt-6.1-sol', 'reasoning_effort': 'ultra',
            'message': ' '.join([review['token'], permit['dispatch_nonce'], name + '-' + case_id, str(work)])}
        call = {'type': 'response_item', 'timestamp': '2026-10-14T05:00:00Z', 'payload': {'type': 'function_call', 'name': 'collaboration.spawn_agent', 'call_id': call_id, 'arguments': json.dumps(arguments)}}
        output = {'type': 'response_item', 'timestamp': '2026-10-14T05:00:01Z', 'payload': {'type': 'function_call_output', 'call_id': call_id, 'output': json.dumps({'task_name': reviewer})}}
        with parent_log.open('a', encoding='utf-8') as stream: stream.write(json.dumps(call) + '\n' + json.dumps(output) + '\n')
        child_log = self.sessions / ('rollout-2026-10-14T12-00-00-' + child_id + '.jsonl')
        child = [
            {'type': 'session_meta', 'payload': {'id': child_id, 'source': {'subagent': {'thread_spawn': {'agent_path': reviewer, 'parent_thread_id': source_id}}}}},
            {'type': 'turn_context', 'payload': {'model': 'gpt-6.1-sol', 'effort': 'ultra'}},
            {'type': 'response_item', 'payload': {'type': 'message', 'role': 'assistant', 'channel': 'final', 'content': [{'text': json.dumps({'decision': 'revise', 'reviewer_agent_id': reviewer, 'review_evidence_sha256': digest(proof_path)})}]}}
        ]
        child_log.write_text(''.join(json.dumps(event) + '\n' for event in child), encoding='utf-8'); self.release(review)
        path = self.pool / name / 'state.json'; state = read_json(path); state['cases'][case_id]['phase'] = 'repairing'
        state['cases'][case_id]['calls'].extend([
            {'stage': 'review', 'status': 'dispatched', 'call_id': call_id, 'agent_id': reviewer, 'session_log': str(parent_log), 'review_session_log': str(child_log)},
            {'stage': 'review', 'status': 'completed_revise', 'call_id': call_id, 'agent_id': reviewer, 'review_evidence': str(proof_path), 'review_evidence_sha256': digest(proof_path)}])
        write_json(path, state)
        request = self.root / (name + case_id + '-repair-request.json'); write_json(request, {'case_id': case_id})
        if bind: self.call(name, 'bind-repair', case_id, value=request, authorization='fixture explicit repair capacity authorization')
        return {'request': request, 'proof': proof_path, 'child_log': child_log, 'parent_log': parent_log, 'review': review}

    def test_final_explicit_pass_or_blocked_cannot_bind_revise_repair(self):
        self.create('a', 'a'); self.configure(); facts = self.revise('a', 0, bind=False)
        original = [json.loads(line) for line in facts['child_log'].read_text(encoding='utf-8').splitlines()]
        for decision in ('pass', 'blocked'):
            with self.subTest(decision=decision):
                events = copy.deepcopy(original); attestation = json.loads(events[-1]['payload']['content'][0]['text'])
                attestation['decision'] = decision; events[-1]['payload']['content'][0]['text'] = json.dumps(attestation)
                facts['child_log'].write_text(''.join(json.dumps(event) + '\n' for event in events), encoding='utf-8')
                with self.assertRaisesRegex(ValueError, 'does not attest this exact revise proof'):
                    self.call('a', 'bind-repair', '0', value=facts['request'], authorization='fixture final decision boundary')

    def test_final_omitted_or_explicit_revise_can_bind_exact_revise_repair(self):
        self.create('a', 'a'); self.configure(); facts = self.revise('a', 0, bind=False)
        original = [json.loads(line) for line in facts['child_log'].read_text(encoding='utf-8').splitlines()]
        for decision in (None, 'revise'):
            with self.subTest(decision=decision):
                events = copy.deepcopy(original); attestation = json.loads(events[-1]['payload']['content'][0]['text'])
                if decision is None: attestation.pop('decision')
                else: attestation['decision'] = decision
                events[-1]['payload']['content'][0]['text'] = json.dumps(attestation)
                facts['child_log'].write_text(''.join(json.dumps(event) + '\n' for event in events), encoding='utf-8')
                result = self.call('a', 'bind-repair', '0', value=facts['request'], authorization='fixture final decision compatibility')
                self.assertIn('0', result['repair_bindings']['a'])

    def test_eight_builds_plus_two_verified_repairs_without_expanding_each_real_group(self):
        for name in ('a', 'b', 'c', 'd', 'e'): self.create(name, name)
        self.configure(); self.revise('d'); self.revise('e'); self.fill('a'); self.fill('b'); self.fill('c', range(2))
        ordinary = self.queue('c', 2); self.assertFalse(self.acquire(ordinary)['acquired'])
        for name in ('d', 'e'):
            active = self.acquire(self.queue(name, 0)); self.assertEqual(active['status'], 'active')
            self.assertEqual(active['work_kind'], 'repair'); self.assertEqual([active['model'], active['effort']], ['gpt-6.1-sol', 'ultra'])
        self.assertEqual(sum(q['status'] == 'active' and q['stage'] == 'build' for q in read_json(self.pool / 'queue.json')), 10)
        self.assertFalse(self.acquire(ordinary)['acquired'])

    def test_phase_or_self_label_without_review_provenance_cannot_claim_extra_budget(self):
        for name in ('a', 'b', 'c'): self.create(name, name)
        self.configure(); self.fill('a'); self.fill('b'); self.fill('c', range(2))
        path = self.pool / 'c/state.json'; state = read_json(path); state['cases']['2'].update(phase='repairing', work_kind='repair'); write_json(path, state)
        request = self.root / 'fake-repair.json'; write_json(request, {'case_id': '2'})
        with self.assertRaisesRegex(ValueError, 'completed independent revise'): self.call('c', 'bind-repair', '2', value=request, authorization='fixture')
        self.assertFalse(self.acquire(self.queue('c', 2))['acquired'])

    def test_repair_can_borrow_idle_build_capacity_beyond_two_but_group_remains_three(self):
        self.create('a', 'a'); self.create('b', 'b'); self.configure()
        for name in ('a', 'b'):
            for index in range(4): self.revise(name, index)
        for name in ('a', 'b'):
            for index in range(3): self.assertEqual(self.acquire(self.queue(name, index))['work_kind'], 'repair')
        self.assertFalse(self.acquire(self.queue('a', 3))['acquired']); self.assertFalse(self.acquire(self.queue('b', 3))['acquired'])

    def test_build_and_repair_rotate_and_selected_ticket_tells_parent_what_to_acquire(self):
        self.create('a', 'a'); self.configure(); self.revise('a', 0); self.revise('a', 1)
        repair0 = self.queue('a', 0); repair1 = self.queue('a', 1); build2 = self.queue('a', 2); build3 = self.queue('a', 3)
        # Last admitted review was ordinary work: first verified repair gets a turn.
        denied = self.acquire(build2); self.assertFalse(denied['acquired']); self.assertEqual(denied['selected']['token'], repair0['token'])
        self.assertEqual(denied['selected']['case_id'], '0'); self.assertEqual(denied['selected']['work_kind'], 'repair'); self.assertEqual(denied['selected']['effort'], 'ultra')
        self.assertEqual(self.acquire(repair0)['status'], 'active'); self.release(repair0)
        denied = self.acquire(repair1); self.assertEqual(denied['selected']['token'], build2['token'])
        self.assertEqual(self.acquire(build2)['status'], 'active'); self.release(build2)
        self.assertEqual(self.acquire(repair1)['status'], 'active'); self.release(repair1)
        self.assertEqual(self.acquire(build3)['status'], 'active')

    def test_bad_or_changed_proof_child_identity_and_run_cannot_expand_capacity(self):
        self.create('a', 'a'); self.configure(); facts = self.revise('a', 0, bind=False)
        original_proof = facts['proof'].read_bytes(); original_child = facts['child_log'].read_bytes()
        state_path = self.pool / 'a/state.json'; original_state = state_path.read_bytes(); work = facts['proof'].parents[1]
        run_path = work / '.product-v2/run.json'; original_run = run_path.read_bytes()
        for fault in ('hash', 'pass', 'child', 'run'):
            with self.subTest(fault=fault):
                if fault == 'hash': facts['proof'].write_bytes(original_proof + b' ')
                if fault == 'pass':
                    proof = read_json(facts['proof']); proof['decision'] = 'pass'; write_json(facts['proof'], proof)
                    state = read_json(state_path); state['cases']['0']['calls'][-1]['review_evidence_sha256'] = digest(facts['proof']); write_json(state_path, state)
                if fault == 'child': facts['child_log'].write_bytes(original_child.replace(b'gpt-6.1-sol', b'gpt-wrong'))
                if fault == 'run': write_json(run_path, {'workspace': str(work), 'run_id': 'another-run'})
                with self.assertRaises(ValueError): self.call('a', 'bind-repair', '0', value=facts['request'], authorization='fixture')
                facts['proof'].write_bytes(original_proof); facts['child_log'].write_bytes(original_child); state_path.write_bytes(original_state); run_path.write_bytes(original_run)
        self.call('a', 'bind-repair', '0', value=facts['request'], authorization='fixture')
        repair = self.queue('a', 0); facts['proof'].write_bytes(original_proof + b' '); ordinary = self.queue('a', 1)
        self.assertEqual(self.acquire(ordinary)['status'], 'active'); self.assertFalse(self.acquire(repair)['acquired'])

    def test_binding_extra_budget_and_reconfiguration_do_not_rewrite_old_active(self):
        self.create('a', 'a'); self.configure(extra=0); facts = self.revise('a', 0, bind=False)
        active = self.acquire(self.queue('a', 0)); before = copy.deepcopy(read_json(self.pool / 'queue.json'))
        self.assertEqual([active['model'], active['effort']], ['gpt-6.1-sol', 'ultra'])
        self.call('a', 'bind-repair', '0', value=facts['request'], authorization='fixture'); self.configure(extra=2)
        self.assertEqual(before, read_json(self.pool / 'queue.json')); self.assertEqual(active['scheduler_admission']['work_kind'], 'build')
        path = self.root / 'bad-extra.json'; write_json(path, {'mode': scheduler.CONTRACT, 'repair_extra_capacity': 3})
        with self.assertRaisesRegex(ValueError, 'extra capacity'): self.call('a', 'configure-scheduler', value=path, authorization='fixture')

    def test_four_scoped_astra_reviews_across_two_groups_and_full_stage_lends_to_build(self):
        self.create('a', 'a'); self.create('b', 'b'); self.configure()
        for name, case_id in (('a', '0'), ('a', '1'), ('b', '0'), ('b', '1'), ('a', '2')):
            scope = name + '/' + case_id; statement = scope + ' 使用原加急模式'
            log = self.sessions / (name + case_id + '-user-grant.jsonl')
            log.write_text(json.dumps({'type': 'response_item', 'payload': {'type': 'message', 'role': 'user', 'content': [{'type': 'input_text', 'text': statement}]}}) + '\n', encoding='utf-8')
            work = self.root / (name + '-' + case_id); request = self.root / (name + case_id + '-grant.json')
            write_json(request, {'run_id': name + '-' + case_id, 'workspace': str(work), 'scope_name': scope, 'statement': statement,
                                 'session_log': str(log), 'user_message_sha256': hashlib.sha256(statement.encode()).hexdigest()})
            self.call(name, 'expedite', case_id, authorization=request)
            ticket = self.queue(name, case_id, stage='review'); active = self.acquire(ticket)
            if case_id == '2': self.assertFalse(active['acquired'])
            else:
                self.assertEqual(active['status'], 'active'); self.assertEqual(active['stage'], 'expedited')
                permit = self.call(name, 'verify-review', case_id, token=active['token'], value=work)
                self.assertEqual([permit['model'], permit['effort']], ['gpt-6-astra', 'low'])
        ordinary = self.acquire(self.queue('a', 3)); self.assertEqual(ordinary['status'], 'active')


if __name__ == '__main__': unittest.main()
