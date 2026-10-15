"""Adaptive reservation regressions with isolated, authenticated fixture owners.

No model, browser or media dispatch; all mutable state lives in TemporaryDirectory.
"""
import copy
import hashlib
import io
import json
from pathlib import Path
import time
import unittest
from unittest.mock import patch
import test_scheduler_groups as helpers
import test_scheduler_repair as repair_helpers
import batch_control as batch
import scheduler_policy as scheduler
from common import digest, read_json, write_json


class AdaptiveSchedulerTests(unittest.TestCase):
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
    revise = repair_helpers.RepairBudgetTests.revise
    test_copied_same_session_still_one_group = helpers.SchedulerGroupsTests.test_same_identity_copied_log_still_one_group_and_worker_override_refuses
    test_invalid_candidate_does_not_block_other_group = helpers.SchedulerGroupsTests.test_invalid_early_source_preflight_and_binding_cannot_block_valid_group
    test_active_cannot_move_groups = helpers.SchedulerGroupsTests.test_active_group_cannot_be_rebound_to_different_real_session
    test_media_exclusion_and_job_release_remain_enforced = helpers.SchedulerGroupsTests.test_record_evidence_exclusion_and_windows_job_release_survive_enabled_policy

    def configure(self, name='a', mode=scheduler.ADAPTIVE_CONTRACT, **options):
        path = self.root / 'adaptive-request.json'
        write_json(path, {'mode': mode, **options})
        return self.call(name, 'configure-scheduler', value=path, authorization='fixture explicit adaptive scheduling authorization')

    def repairing(self, name, indexes):
        path = self.pool / name / 'state.json'; state = read_json(path)
        for index in indexes: state['cases'][str(index)]['phase'] = 'repairing'
        write_json(path, state)

    def runtime(self, name, group, total_slots, role='developer', authenticated=True):
        request = self.request(name, group); _, log = self.logs[group]
        event = {'type': 'response_item', 'payload': {'type': 'message', 'role': role,
            'content': [{'type': 'input_text', 'text': '<multi_agent_role>There are ' + str(total_slots) +
                ' available concurrency slots, meaning that up to ' + str(total_slots) +
                ' agents can be active at once, including you.</multi_agent_role>'}]}}
        if authenticated:
            event['payload']['internal_chat_message_metadata_passthrough'] = {'content_item_kinds': ['multi_agent.role_instructions']}
        with log.open('a', encoding='utf-8') as stream: stream.write(json.dumps(event) + '\n')
        return self.call(name, 'bind-controller', value=request, authorization='fixture real runtime instruction evidence')

    def test_one_verified_larger_runtime_borrows_more_than_three_without_manifest_change(self):
        self.create('a', 'A'); self.create('idle', 'Idle'); self.configure()
        path = self.pool / 'a/manifest.json'; before = path.read_bytes()
        self.runtime('a', 'A', 8)
        self.fill('a', range(7))
        self.assertFalse(self.acquire(self.queue('a', 7))['acquired'])
        self.assertEqual(before, path.read_bytes())
        rows = scheduler.snapshot(self.pool, read_json(self.pool / 'queue.json'), scheduler.config(self.pool))
        a = next(row for row in rows['groups'] if 'a' in row['batch_ids'])
        self.assertEqual([a['worker_ceiling'], a['reserved_model_slots']], [7, 7])

    def test_twelve_total_counts_all_old_and_new_model_stages_and_does_not_evenly_split(self):
        self.create('a', 'A'); self.create('b', 'B'); self.configure()
        self.runtime('a', 'A', 13); self.runtime('b', 'B', 13)
        self.fill('a', range(9))
        self.fill('b', range(3))
        before = copy.deepcopy(read_json(self.pool / 'queue.json'))
        waiting = self.queue('b', 3, stage='review')
        self.assertFalse(self.acquire(waiting)['acquired'])
        self.assertEqual(before, read_json(self.pool / 'queue.json')[:-1])
        self.assertEqual(scheduler.snapshot(self.pool, read_json(self.pool / 'queue.json'), scheduler.config(self.pool))['unreserved_global_model_slots'], 0)

    def test_same_parent_new_runtime_not_multiplied_by_old_binding_or_arbitrary_requests(self):
        self.create('a', 'A'); self.create('b', 'A'); self.configure()
        self.runtime('a', 'A', 7); self.fill('a', range(4)); self.fill('b', range(2))
        self.assertFalse(self.acquire(self.queue('b', 2))['acquired'])
        request = self.request('b', 'A'); data = read_json(request); data['runtime_capacity'] = {'worker_capacity': 12}; write_json(request, data)
        with self.assertRaisesRegex(ValueError, 'platform developer evidence'):
            self.call('b', 'bind-controller', value=request, authorization='fixture bad override')

    def test_user_quoted_or_unmarked_runtime_claim_cannot_increase_real_four_slot_parent(self):
        self.create('a', 'A'); self.configure()
        self.runtime('a', 'A', 4)
        self.runtime('a', 'A', 13, role='user')
        self.runtime('a', 'A', 13, authenticated=False)
        self.fill('a')
        self.assertFalse(self.acquire(self.queue('a', 3))['acquired'])
        row = scheduler.snapshot(self.pool, read_json(self.pool / 'queue.json'), scheduler.config(self.pool))['groups'][0]
        self.assertEqual(row['worker_ceiling'], 3)

    def test_normal_acquire_and_status_only_read_frozen_runtime_ranges(self):
        self.create('a', 'A'); self.configure(); self.runtime('a', 'A', 7)
        with patch('scheduler_policy.runtime_capacity', side_effect=AssertionError('full scan prohibited')):
            self.assertEqual(self.acquire(self.queue('a', 0))['status'], 'active')
            row = scheduler.snapshot(self.pool, read_json(self.pool / 'queue.json'), scheduler.config(self.pool))['groups'][0]
            self.assertEqual(row['worker_ceiling'], 6)

    def test_changed_binding_cannot_create_capacity(self):
        self.create('a', 'A'); self.create('b', 'B'); self.configure()
        session_id, log = self.logs['A']
        with log.open('a') as stream: stream.write('{partial')
        self.assertIsNotNone(scheduler.verified_binding(self.pool, 'a', scheduler.config(self.pool)))
        log.write_bytes(log.read_bytes().replace(session_id.encode(), b'0' * len(session_id)))
        self.assertIsNone(scheduler.verified_binding(self.pool, 'a', scheduler.config(self.pool)))
        self.assertFalse(self.acquire(self.queue('a', 0))['acquired'])
        self.fill('b'); self.assertFalse(self.acquire(self.queue('b', 3))['acquired'])

    def test_runtime_refresh_uses_control_order_when_clock_moves_backwards(self):
        self.create('a', 'A'); self.create('b', 'A'); self.configure(); self.runtime('a', 'A', 9)
        with patch('scheduler_policy.time.time_ns', return_value=1): self.runtime('b', 'A', 4)
        rows = scheduler.snapshot(self.pool, [], scheduler.config(self.pool))['groups']
        self.assertEqual(len(rows), 1); self.assertEqual(rows[0]['worker_ceiling'], 3)

    def assert_latest_runtime_fault_blocks_admission(self, fault, total_slots, old_reference):
        label = fault + '-' + str(total_slots) + '-' + str(old_reference)
        a, b, group = 'a-' + label, 'b-' + label, 'parent-' + label
        self.pool = self.root / ('pool-' + label)
        self.create(a, group); self.create(b, group); self.configure(a)
        self.runtime(a, group, 13)
        with patch('scheduler_policy.time.time_ns', return_value=1): self.runtime(b, group, total_slots)
        workers = total_slots - 1; self.fill(a, range(workers))
        waiting = self.queue(a, workers); invalid_waiting = self.queue(b, 0)
        self.assertFalse(self.acquire(waiting)['acquired'])
        settings = scheduler.config(self.pool); latest = read_json(settings['bindings'][b]['path'])
        before = scheduler.snapshot(self.pool, read_json(self.pool / 'queue.json'), settings)['groups'][0]
        self.assertEqual(before['worker_ceiling'], workers)
        active = [q for q in read_json(self.pool / 'queue.json') if q['status'] == 'active']
        manifests = {name: (self.pool / name / 'manifest.json').read_bytes() for name in (a, b)}
        if old_reference:
            for reference in settings['bindings'].values():
                for key in ('group', 'control_revision', 'bound_ns'): reference.pop(key)
            write_json(self.pool / 'scheduler-config.json', settings)
        if fault == 'runtime':
            log = Path(latest['proof']['session_log']); raw = log.read_bytes(); saved = latest['runtime_capacity']
            start = saved['event_offset']; end = start + saved['event_size']
            changed = raw[start:end].replace(('There are ' + str(total_slots)).encode(), b'There are 9', 1)
            self.assertNotEqual(changed, raw[start:end]); log.write_bytes(raw[:start] + changed + raw[end:])
        else:
            path = Path(settings['bindings'][b]['path']); path.write_bytes(path.read_bytes() + b' ')
        config_before = (self.pool / 'scheduler-config.json').read_bytes()
        with patch('scheduler_policy.runtime_capacity', side_effect=AssertionError('full scan prohibited')):
            settings = scheduler.config(self.pool)
            self.assertIsNotNone(scheduler.verified_binding(self.pool, a, settings))
            self.assertIsNone(scheduler.verified_binding(self.pool, b, settings))
            row = scheduler.snapshot(self.pool, read_json(self.pool / 'queue.json'), settings)['groups'][0]
            self.assertEqual([row['worker_ceiling'], row['unreserved_model_slots']], [0, 0])
            self.assertFalse(self.acquire(waiting)['acquired'])
            self.assertFalse(self.acquire(invalid_waiting)['acquired'])
        self.assertEqual(config_before, (self.pool / 'scheduler-config.json').read_bytes())
        self.assertEqual(active, [q for q in read_json(self.pool / 'queue.json') if q['status'] == 'active'])
        self.assertEqual(manifests, {name: (self.pool / name / 'manifest.json').read_bytes() for name in (a, b)})

    def test_latest_same_parent_runtime_byte_change_cannot_restore_old_high_capacity(self):
        for total_slots in (4, 2):
            for old_reference in (False, True):
                with self.subTest(total_slots=total_slots, old_reference=old_reference):
                    self.assert_latest_runtime_fault_blocks_admission('runtime', total_slots, old_reference)

    def test_latest_same_parent_binding_hash_change_cannot_restore_old_high_capacity(self):
        for total_slots in (4, 2):
            for old_reference in (False, True):
                with self.subTest(total_slots=total_slots, old_reference=old_reference):
                    self.assert_latest_runtime_fault_blocks_admission('binding', total_slots, old_reference)

    def test_valid_same_parent_refresh_can_grow_and_shrink_despite_equal_or_backward_clock(self):
        self.create('a', 'A'); self.create('b', 'A'); self.configure()
        manifests = {name: (self.pool / name / 'manifest.json').read_bytes() for name in ('a', 'b')}
        for name, total_slots, clock in (('a', 4, 100), ('b', 9, 100), ('a', 2, 0), ('b', 13, -1)):
            with patch('scheduler_policy.time.time_ns', return_value=clock): self.runtime(name, 'A', total_slots)
            row = scheduler.snapshot(self.pool, [], scheduler.config(self.pool))['groups'][0]
            self.assertEqual(row['worker_ceiling'], total_slots - 1)
        self.fill('a', range(6)); self.fill('b', range(6))
        self.assertFalse(self.acquire(self.queue('b', 6))['acquired'])
        self.assertEqual(manifests, {name: (self.pool / name / 'manifest.json').read_bytes() for name in ('a', 'b')})

    def test_later_valid_refresh_supersedes_older_invalid_same_parent_binding(self):
        self.create('a', 'A'); self.create('b', 'A'); self.create('c', 'C'); self.configure()
        self.runtime('a', 'A', 4)
        settings = scheduler.config(self.pool); path = Path(settings['bindings']['a']['path'])
        path.write_bytes(path.read_bytes() + b' ')
        self.assertEqual(self.acquire(self.queue('c', 0))['status'], 'active')
        waiting = self.queue('b', 0); self.assertFalse(self.acquire(waiting)['acquired'])
        with patch('scheduler_policy.time.time_ns', return_value=0): self.runtime('b', 'A', 8)
        self.assertEqual(self.acquire(waiting)['status'], 'active'); self.fill('b', range(1, 7))
        row = next(row for row in scheduler.snapshot(self.pool, read_json(self.pool / 'queue.json'), scheduler.config(self.pool))['groups'] if 'b' in row['batch_ids'])
        self.assertEqual([row['worker_ceiling'], row['reserved_model_slots']], [7, 7])
        self.assertFalse(self.acquire(self.queue('b', 7))['acquired'])

    def test_latest_same_parent_binding_without_runtime_does_not_reuse_old_high_capacity(self):
        self.create('a', 'A'); self.create('b', 'A'); self.configure(); self.runtime('a', 'A', 13)
        request = self.request('b', 'A'); value = read_json(request); original = Path(value['session_log'])
        copied = self.sessions / 'copied' / original.name; copied.parent.mkdir()
        copied.write_bytes(b''.join(raw for raw in original.read_bytes().splitlines(keepends=True)
                                   if scheduler.runtime_workers(json.loads(raw)) is None))
        value['session_log'] = str(copied); write_json(request, value)
        self.call('b', 'bind-controller', value=request, authorization='fixture latest parent without runtime declaration')
        row = scheduler.snapshot(self.pool, [], scheduler.config(self.pool))['groups'][0]
        self.assertEqual(row['worker_ceiling'], 3)
        self.fill('a'); self.assertFalse(self.acquire(self.queue('b', 0))['acquired'])

    def test_capacity_reduction_and_lower_pool_preserve_old_active_until_natural_release(self):
        self.create('a', 'A'); self.configure(); self.runtime('a', 'A', 9); self.fill('a', range(8))
        before = copy.deepcopy(read_json(self.pool / 'queue.json'))
        self.runtime('a', 'A', 4); self.configure(model_pool_capacity=5)
        self.assertEqual(before, read_json(self.pool / 'queue.json'))
        waiting = self.queue('a', 8); self.assertFalse(self.acquire(waiting)['acquired'])
        for ticket in before[:6]: self.release(ticket)
        self.assertEqual(self.acquire(waiting)['status'], 'active')

    def test_old_configuration_omission_defaults_to_twelve_and_invalid_pool_update_is_atomic(self):
        self.create('a', 'A'); self.configure(); path = self.pool / 'scheduler-config.json'
        config = read_json(path); config.pop('model_pool_capacity'); write_json(path, config)
        self.assertEqual(scheduler.model_pool_capacity(scheduler.config(self.pool)), 12)
        before = path.read_bytes()
        for value in (0, 13, True, '12'):
            with self.assertRaisesRegex(ValueError, 'Model pool capacity'): self.configure(model_pool_capacity=value)
            self.assertEqual(before, path.read_bytes())

    def test_v1_old_active_above_twelve_counts_once_and_is_not_stopped_on_enable(self):
        for name in ('a', 'b', 'c', 'd', 'e'): self.create(name, name)
        self.configure(mode=scheduler.CONTRACT, capacities={'build': 8, 'review': 8, 'expedited': 4})
        for name, count, stage in (('a', 3, 'build'), ('b', 3, 'build'), ('c', 2, 'build'),
                                    ('d', 3, 'review'), ('e', 2, 'review')):
            for index in range(count): self.assertEqual(self.acquire(self.queue(name, index, stage=stage))['status'], 'active')
        before = copy.deepcopy(read_json(self.pool / 'queue.json')); self.configure()
        self.assertEqual(before, read_json(self.pool / 'queue.json'))
        waiting = self.queue('c', 2); self.assertFalse(self.acquire(waiting)['acquired'])
        facts = scheduler.snapshot(self.pool, read_json(self.pool / 'queue.json'), scheduler.config(self.pool))
        self.assertEqual([facts['active_model_reservations'], facts['unreserved_global_model_slots']], [13, 0])
        for ticket in before[:2]: self.release(ticket)
        self.assertEqual(self.acquire(waiting)['status'], 'active')

    def next_ticket(self):
        pool = read_json(self.pool / 'queue.json')
        ready = batch.ready_model_tickets(self.pool, batch.runnable_waiting(self.pool, pool))
        return scheduler.choose(self.pool, ready, [q for q in pool if q['status'] == 'active'], pool, scheduler.config(self.pool))[0]

    def test_six_reviews_borrow_both_real_groups_without_fixed_four_or_supplied_one(self):
        self.create('a', 'A'); self.create('b', 'B')
        self.configure(capacities={'build': 1, 'review': 1, 'expedited': 1})
        for name in ('a', 'b'):
            for index in range(3):
                active = self.acquire(self.queue(name, index, stage='review'))
                self.assertEqual(active['status'], 'active')
                admission = read_json(active['review_admission']['path'])
                self.assertEqual([admission['model'], admission['effort']], ['gpt-6.1-sol', 'ultra'])
                self.assertFalse(active['scheduler_admission']['fixed_stage_quotas'])
            self.assertFalse(self.acquire(self.queue(name, 3, stage='review'))['acquired'])
        self.assertEqual(sum(q['status'] == 'active' for q in read_json(self.pool / 'queue.json')), 6)

    def test_build_and_record_prep_repair_borrow_six_without_extra_binding_or_model_change(self):
        for kind in ('build', 'repair'):
            with self.subTest(kind=kind):
                names = [kind + suffix for suffix in ('a', 'b')]
                self.pool = self.root / (kind + '-pool')
                for name in names: self.create(name, name)
                self.configure(names[0], capacities={'build': 1, 'review': 1, 'expedited': 1})
                for name in names:
                    if kind == 'repair': self.repairing(name, range(4))
                    for index in range(3):
                        active = self.acquire(self.queue(name, index)); self.assertEqual(active['status'], 'active')
                        self.assertEqual(active['scheduler_admission']['lane'], kind)
                        self.assertFalse(active['scheduler_admission']['repair_extra_budget_used'])
                        self.assertEqual(active['scheduler_admission']['work_kind'], 'build')
                        self.assertNotIn('repair_binding', active['scheduler_admission'])
                        if kind == 'repair': self.assertEqual([active['model'], active['effort']], ['gpt-6.1-sol', 'ultra'])
                    self.assertFalse(self.acquire(self.queue(name, 3))['acquired'])
                self.assertEqual(sum(q['status'] == 'active' for q in read_json(self.pool / 'queue.json')), 6)

    def test_three_verified_groups_supply_nine_build_reservations_but_never_four_per_group(self):
        for name in ('a', 'b', 'c'): self.create(name, name)
        self.configure()
        for name in ('a', 'b', 'c'): self.fill(name)
        self.assertEqual(sum(q['status'] == 'active' for q in read_json(self.pool / 'queue.json')), 9)
        for name in ('a', 'b', 'c'): self.assertFalse(self.acquire(self.queue(name, 3))['acquired'])

    def test_duplicate_binding_same_parent_and_dormant_groups_cannot_lend_capacity(self):
        self.create('a', 'A'); self.create('b', 'A'); self.create('stopped', 'Stopped'); self.create('done', 'Done')
        self.configure(); self.fill('a', range(2)); self.fill('b', range(1))
        self.call('stopped', 'drain', authorization='fixture maintenance pause')
        state = read_json(self.pool / 'done/state.json')
        for item in state['cases'].values(): item['phase'] = 'delivered'
        write_json(self.pool / 'done/state.json', state)
        before = copy.deepcopy(read_json(self.pool / 'queue.json')); self.bind('b', 'A')
        self.assertEqual(before, read_json(self.pool / 'queue.json'))
        self.assertFalse(self.acquire(self.queue('b', 1, stage='review'))['acquired'])
        self.assertFalse(self.acquire(self.queue('stopped', 0))['acquired'])
        self.assertFalse(self.acquire(self.queue('done', 0))['acquired'])
        self.assertEqual(sum(q['status'] == 'active' for q in read_json(self.pool / 'queue.json')), 3)

    def test_unknown_legacy_active_reserves_each_verified_group_conservatively(self):
        self.create('old'); old = self.acquire(self.queue('old', 0))
        self.create('a', 'A'); self.create('b', 'B'); self.configure()
        self.fill('a', range(2)); self.fill('b', range(2))
        self.assertFalse(self.acquire(self.queue('a', 2, stage='review'))['acquired'])
        self.assertFalse(self.acquire(self.queue('b', 2, stage='review'))['acquired'])
        self.assertEqual(old, read_json(self.pool / 'queue.json')[0])
        self.assertEqual(sum(q['status'] == 'active' for q in read_json(self.pool / 'queue.json')), 5)

    def test_live_enable_and_rollback_preserve_old_queue_permits_manifest_and_run_bytes(self):
        self.create('a'); self.create('b'); active = self.acquire(self.queue('a', 0, stage='review'))
        work = read_json(self.pool / 'a/manifest.json')['cases'][0]['workspace']
        permit = self.call('a', 'verify-review', '0', token=active['token'], value=work)
        paths = [self.pool / 'a/manifest.json', Path(work) / '.product-v2/run.json',
                 Path(active['review_admission']['path']), Path(permit['review_dispatch_permit']['path'])]
        hashes = {str(path): digest(path) for path in paths}; before = copy.deepcopy(read_json(self.pool / 'queue.json')[0])
        self.bind('a', 'A'); self.bind('b', 'B'); self.configure()
        for name, indexes in (('a', (1, 2)), ('b', (0, 1, 2))):
            for index in indexes: self.assertEqual(self.acquire(self.queue(name, index, stage='review'))['status'], 'active')
        self.configure(mode='legacy'); waiting = self.queue('b', 3, stage='review')
        self.assertFalse(self.acquire(waiting)['acquired'])
        self.assertEqual(before, read_json(self.pool / 'queue.json')[0])
        self.assertEqual(hashes, {str(path): digest(path) for path in paths})
        self.assertEqual(self.call('a', 'verify-review', '0', token=active['token'], value=work), permit)

    def test_older_bulk_builds_do_not_block_review_or_record_prep_repair_and_build_is_not_starved(self):
        self.create('a', 'A'); self.configure(); self.repairing('a', range(6, 9))
        builds = [self.queue('a', index) for index in range(6)]
        repairs = [self.queue('a', index) for index in range(6, 9)]
        reviews = [self.queue('a', index, stage='review') for index in range(9, 12)]
        order = []
        for expected in sum(([reviews[i], repairs[i], builds[i]] for i in range(3)), []):
            chosen = self.next_ticket(); self.assertEqual(chosen['token'], expected['token'])
            active = self.acquire(chosen); self.assertEqual(active['status'], 'active')
            order.append(active['scheduler_admission']['lane']); self.release(chosen)
        self.assertEqual(order, ['review', 'repair', 'build'] * 3)

    def test_each_continuously_eligible_stage_with_priority_churn_waits_at_most_three_admissions(self):
        self.create('a', 'A'); self.create('b', 'B'); self.configure()
        self.repairing('a', range(4, 8)); self.repairing('b', range(4, 8))
        for name in ('a', 'b'):
            for index in range(12):
                self.queue(name, index, urgent=index % 2 == 0, stage='review' if index >= 8 else 'build')
        lanes = []
        for _ in range(24):
            chosen = self.next_ticket(); active = self.acquire(chosen); lanes.append(active['scheduler_admission']['lane']); self.release(chosen)
        for offset in range(0, 24, 3): self.assertEqual(set(lanes[offset:offset + 3]), {'review', 'repair', 'build'})

    def test_lane_fairness_rotates_groups_and_batches_and_keeps_fifo_within_batch(self):
        self.create('a', 'A'); self.create('b', 'A'); self.create('c', 'C'); self.configure()
        a0 = self.queue('a', 0, stage='review'); a1 = self.queue('a', 1, stage='review')
        b0 = self.queue('b', 0, stage='review'); c0 = self.queue('c', 0, stage='review')
        for expected in (a0, c0, b0, a1):
            self.assertEqual(self.next_ticket()['token'], expected['token'])
            self.assertEqual(self.acquire(expected)['status'], 'active'); self.release(expected)

    def test_repeated_or_backward_clock_cannot_break_stage_rotation(self):
        self.create('a', 'A'); self.configure(); self.repairing('a', range(4, 8))
        for index in range(12): self.queue('a', index, stage='review' if index >= 8 else 'build')
        lanes = []; turns = []; clock = time.time_ns()
        for index in range(12):
            with patch('batch_control.time.time_ns', return_value=clock - index // 2):
                chosen = self.next_ticket(); active = self.acquire(chosen); self.release(chosen)
            lanes.append(active['scheduler_admission']['lane']); turns.append(active['scheduler_turn'])
        self.assertEqual(lanes, ['review', 'repair', 'build'] * 4)
        self.assertEqual(turns, list(range(1, 13)))

    def test_aged_fifo_prevents_same_class_priority_churn_without_rewriting_priority(self):
        self.create('a', 'A'); self.configure(aging_seconds=10)
        old = self.queue('a', 0); new = self.queue('a', 1)
        path = self.pool / 'queue.json'; pool = read_json(path)
        pool[0]['submitted_ns'] = time.time_ns() - 11_000_000_000; pool[1]['priority'] = 9; write_json(path, pool)
        self.assertEqual(self.next_ticket()['token'], old['token'])
        active = self.acquire(old); self.assertTrue(active['scheduler_admission']['aged']); self.release(old)
        self.assertEqual(self.acquire(new)['status'], 'active')
        pool = read_json(path); self.assertEqual([q['priority'] for q in pool], [0, 9])
        self.assertEqual([q['stage'] for q in pool], ['build', 'build'])

    def test_capacity_cooldown_review_cannot_hold_build_queue_and_route_is_unchanged(self):
        self.create('a', 'A'); self.configure(); cooling = self.queue('a', 0, stage='review')
        path = self.pool / 'queue.json'; pool = read_json(path)
        pool[0].update(capacity_retry={'not_before_ns': time.time_ns() + 60_000_000_000}, model='gpt-6.1-sol', effort='ultra'); write_json(path, pool)
        saved = copy.deepcopy(pool[0]); build = self.queue('a', 1)
        self.assertEqual(self.acquire(build)['status'], 'active')
        self.assertFalse(self.acquire(cooling)['acquired']); self.assertEqual(saved, read_json(path)[0])

    def test_selected_action_names_real_owner_and_does_not_acquire_another_batch(self):
        self.create('a', 'A'); self.create('b', 'B'); self.configure()
        build = self.queue('a', 0); review = self.queue('b', 0, stage='review')
        before = copy.deepcopy(read_json(self.pool / 'queue.json')); denied = self.acquire(build)
        self.assertFalse(denied['acquired']); self.assertEqual(denied['selected']['token'], review['token'])
        self.assertEqual(denied['selected']['owner'], review['owner'])
        self.assertEqual(denied['selected']['action'], 'selected_owner_acquire_then_dispatch')
        self.assertFalse(denied['selected']['requester_can_acquire'])
        self.assertEqual(before, read_json(self.pool / 'queue.json'))

    def test_verified_repair_binding_remains_authentic_and_extra_capacity_is_not_spent(self):
        self.create('a', 'a'); self.configure(repair_extra_capacity=2)
        facts = self.revise('a', 0); active = self.acquire(self.queue('a', 0))
        self.assertEqual(active['work_kind'], 'repair'); self.assertIn('repair_binding', active['scheduler_admission'])
        self.assertFalse(active['scheduler_admission']['repair_extra_budget_used']); self.release(active)
        facts['proof'].write_bytes(facts['proof'].read_bytes() + b' ')
        bad = self.queue('a', 0); good = self.queue('a', 1)
        self.assertEqual(self.acquire(good)['status'], 'active'); self.assertFalse(self.acquire(bad)['acquired'])

    def test_six_genuinely_authorized_astra_reviews_share_capacity_but_labels_cannot_authorize(self):
        self.create('a', 'A'); self.create('b', 'B'); self.configure()
        for name in ('a', 'b'):
            for index in range(3):
                case_id = str(index); scope = name + '/' + case_id; statement = scope + ' 使用原加急模式'
                log = self.sessions / (name + case_id + '-grant.jsonl')
                log.write_text(json.dumps({'type': 'response_item', 'payload': {'type': 'message', 'role': 'user',
                    'content': [{'type': 'input_text', 'text': statement}]}}) + '\n', encoding='utf-8')
                work = self.root / (name + '-' + case_id); request = self.root / (name + case_id + '-grant.json')
                write_json(request, {'run_id': name + '-' + case_id, 'workspace': str(work), 'scope_name': scope,
                    'statement': statement, 'session_log': str(log), 'user_message_sha256': hashlib.sha256(statement.encode()).hexdigest()})
                self.call(name, 'expedite', case_id, authorization=request)
                active = self.acquire(self.queue(name, case_id, stage='review')); self.assertEqual(active['status'], 'active')
                self.assertEqual(active['stage'], 'expedited')
                permit = self.call(name, 'verify-review', case_id, token=active['token'], value=work)
                self.assertEqual([permit['model'], permit['effort']], ['gpt-6-astra', 'low'])
        with self.assertRaisesRegex(ValueError, 'Unscoped'): self.queue('a', 4, urgent=True, stage='expedited')

    def test_v1_fixed_limit_and_legacy_default_remain_opt_in_compatible(self):
        self.create('a', 'A'); self.create('b', 'B')
        self.assertEqual(scheduler.config(self.pool)['mode'], 'legacy')
        self.configure(mode=scheduler.CONTRACT, capacities={'build': 8, 'review': 4, 'expedited': 4})
        for name, index in (('a', 0), ('a', 1), ('b', 0), ('b', 1)):
            self.assertEqual(self.acquire(self.queue(name, index, stage='review'))['status'], 'active')
        fifth = self.queue('b', 2, stage='review'); self.assertFalse(self.acquire(fifth)['acquired'])
        self.configure(); self.assertEqual(self.acquire(fifth)['status'], 'active')
        self.configure(mode=scheduler.CONTRACT, capacities={'build': 8, 'review': 4, 'expedited': 4})
        self.assertFalse(self.acquire(self.queue('a', 2, stage='review'))['acquired'])

    def test_status_explains_dynamic_reservations_without_claiming_actual_model_capacity(self):
        self.create('a', 'A'); self.create('b', 'A'); self.create('done', 'Done'); self.create('old'); self.configure()
        self.assertEqual(self.acquire(self.queue('old', 0))['status'], 'active')
        self.fill('a', range(1))
        state = read_json(self.pool / 'done/state.json')
        for item in state['cases'].values(): item['phase'] = 'delivered'
        write_json(self.pool / 'done/state.json', state)
        config_before = (self.pool / 'scheduler-config.json').read_bytes(); queue_before = (self.pool / 'queue.json').read_bytes()
        output = io.StringIO()
        with patch('sys.argv', ['batch_control.py', 'status', '--root', str(self.pool), '--batch-id', 'a']), patch('sys.stdout', output):
            self.assertEqual(batch.main(), 0)
        result = json.loads(output.getvalue()); policy = result['scheduler_runtime_policy']
        self.assertFalse(policy['fixed_stage_quotas']); self.assertFalse(policy['fixed_group_quotas'])
        self.assertEqual(policy['model_pool_capacity'], 12)
        self.assertIn('actual model service availability remains external', policy['capacity_scope'])
        rows = {tuple(row['batch_ids']): row for row in result['scheduler_reservations']['groups']}
        self.assertEqual(rows[('a', 'b')]['worker_ceiling'], 3)
        self.assertEqual(rows[('a', 'b')]['reserved_model_slots'], 2)
        self.assertEqual(rows[('a', 'b')]['unknown_active_slots'], 1)
        self.assertEqual(rows[('a', 'b')]['unreserved_model_slots'], 1)
        self.assertEqual(rows[('done',)]['unreserved_model_slots'], 0)
        self.assertEqual(result['scheduler_reservations']['unknown_active_model_reservations'], 1)
        self.assertEqual(config_before, (self.pool / 'scheduler-config.json').read_bytes())
        self.assertEqual(queue_before, (self.pool / 'queue.json').read_bytes())

    def test_media_memory_and_cpu_gates_are_not_borrowed_from_idle_model_slots(self):
        self.create('a', 'A'); self.configure(); capture = self.queue('a', 0, stage='record')
        with patch('batch_control.memory_available_mb', return_value=1):
            self.assertEqual(self.acquire(capture)['reason'], 'memory_exhausted')
        with patch('batch_control.cpu_snapshot', return_value={'logical_processors': 32, 'cpu_load_percent': 100}):
            self.assertEqual(self.acquire(capture)['reason'], 'cpu_busy')
        self.assertEqual(self.acquire(capture)['status'], 'active')
        with patch('media_job.job_pids', return_value=[]): self.release(capture)

    def test_aging_configuration_is_bounded_and_failed_update_preserves_config_bytes(self):
        self.create('a', 'A'); self.configure(); path = self.pool / 'scheduler-config.json'; before = path.read_bytes()
        for value in (0, 3601, True, '30'):
            with self.subTest(value=value):
                with self.assertRaisesRegex(ValueError, 'Aging seconds'): self.configure(aging_seconds=value)
                self.assertEqual(before, path.read_bytes())


if __name__ == '__main__': unittest.main()
