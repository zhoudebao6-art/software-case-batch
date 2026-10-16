"""Explicit parent runtime scope; isolated reservations, no real dispatch."""
import copy
import hashlib
import io
import json
from pathlib import Path
import time
import unittest
from unittest.mock import patch
import test_scheduler_adaptive as helpers
import batch_control as batch
import scheduler_policy as scheduler
from common import digest, read_json, write_json


class ParentRuntimeScopeTests(unittest.TestCase):
    setUp = helpers.AdaptiveSchedulerTests.setUp
    tearDown = helpers.AdaptiveSchedulerTests.tearDown
    call = helpers.AdaptiveSchedulerTests.call
    create = helpers.AdaptiveSchedulerTests.create
    request = helpers.AdaptiveSchedulerTests.request
    bind = helpers.AdaptiveSchedulerTests.bind
    queue = helpers.AdaptiveSchedulerTests.queue
    acquire = helpers.AdaptiveSchedulerTests.acquire
    release = helpers.AdaptiveSchedulerTests.release
    fill = helpers.AdaptiveSchedulerTests.fill
    runtime = helpers.AdaptiveSchedulerTests.runtime
    repairing = helpers.AdaptiveSchedulerTests.repairing

    def configure(self, **options):
        return helpers.AdaptiveSchedulerTests.configure(self,
            capacity_scope=scheduler.RUNTIME_CAPACITY_SCOPE, **options)

    def census(self):
        return scheduler.snapshot(self.pool, read_json(self.pool / 'queue.json'), scheduler.config(self.pool))

    def test_two_independent_parents_each_twelve_reserve_twenty_four(self):
        self.create('a', 'A'); self.create('b', 'B'); self.configure()
        self.runtime('a', 'A', 13); self.runtime('b', 'B', 13)
        self.fill('a', range(12)); self.fill('b', range(12))
        snapshot = self.census()
        self.assertEqual(snapshot['active_model_reservations'], 24)
        self.assertIsNone(snapshot['model_pool_capacity']); self.assertIsNone(snapshot['unreserved_global_model_slots'])
        self.assertFalse(snapshot['global_model_hard_limit'])
        self.assertEqual([(q['worker_ceiling'], q['reserved_model_slots']) for q in snapshot['groups']], [(12, 12)] * 2)

    def test_two_batches_same_parent_share_twelve_not_twenty_four(self):
        self.create('a', 'A'); self.create('b', 'A'); self.configure(); self.runtime('a', 'A', 13)
        self.fill('a', range(7)); self.fill('b', range(5))
        self.assertFalse(self.acquire(self.queue('b', 5))['acquired'])
        rows = self.census()['groups']; self.assertEqual(len(rows), 1)
        self.assertEqual([rows[0]['worker_ceiling'], rows[0]['reserved_model_slots']], [12, 12])

    def test_real_three_worker_runtime_and_latest_refresh_remain_authoritative(self):
        self.create('a', 'A'); self.create('b', 'A'); self.configure(); self.runtime('a', 'A', 21)
        self.runtime('b', 'A', 4); self.fill('a', range(3))
        self.assertFalse(self.acquire(self.queue('b', 0))['acquired'])
        self.assertEqual(self.census()['groups'][0]['worker_ceiling'], 3)

    def test_future_runtime_twenty_is_not_cropped_at_twelve(self):
        self.create('a', 'A'); self.create('b', 'A'); self.configure(); self.runtime('a', 'A', 21)
        self.fill('a', range(10)); self.fill('b', range(10))
        self.assertFalse(self.acquire(self.queue('b', 10))['acquired'])
        row = self.census()['groups'][0]
        self.assertEqual([row['worker_ceiling'], row['reserved_model_slots']], [20, 20])

    def authorize(self, name, index):
        case_id = str(index); scope = name + '/' + case_id; statement = scope + ' 使用原加急模式'
        log = self.sessions / (name + case_id + '-grant.jsonl')
        log.write_text(json.dumps({'type': 'response_item', 'payload': {'type': 'message', 'role': 'user',
            'content': [{'type': 'input_text', 'text': statement}]}}) + '\n', encoding='utf-8')
        request = self.root / (name + case_id + '-grant.json')
        write_json(request, {'run_id': name + '-' + case_id, 'workspace': str(self.root / (name + '-' + case_id)),
            'scope_name': scope, 'statement': statement, 'session_log': str(log),
            'user_message_sha256': hashlib.sha256(statement.encode()).hexdigest()})
        self.call(name, 'expedite', case_id, authorization=request)

    def test_urgent_uses_capacity_above_normal_quota_and_precedes_normal_but_not_runtime(self):
        self.create('a', 'A'); self.create('b', 'A'); self.configure(capacities={'build': 1, 'review': 1, 'expedited': 1})
        self.runtime('a', 'A', 13); self.fill('a', range(9))
        ordinary = self.queue('a', 9, stage='review')
        for index in range(4): self.authorize('b', index)
        urgents = [self.queue('b', index, urgent=True, stage='expedited') for index in range(4)]
        before = copy.deepcopy(read_json(self.pool / 'queue.json'))
        denied = self.acquire(ordinary)
        self.assertEqual(denied['selected']['token'], urgents[0]['token'])
        self.assertEqual(denied['selected']['owner'], urgents[0]['owner'])
        self.assertFalse(denied['selected']['requester_can_acquire'])
        self.assertEqual(before, read_json(self.pool / 'queue.json'))
        for ticket in urgents[:3]:
            active = self.acquire(ticket); self.assertEqual(active['status'], 'active')
            permit = self.call('b', 'verify-review', ticket['case_id'], token=active['token'], value=self.root / ('b-' + ticket['case_id']))
            self.assertEqual([permit['model'], permit['effort']], ['gpt-6-astra', 'low'])
        self.assertFalse(self.acquire(urgents[3])['acquired'])
        self.assertFalse(self.acquire(ordinary)['acquired'])
        self.assertEqual(self.census()['active_model_reservations'], 12)
        with self.assertRaisesRegex(ValueError, 'another owner|batch|token'):
            self.call('a', 'acquire', token=urgents[3]['token'])

    def test_idle_foreign_owner_cannot_block_an_independent_parent(self):
        self.create('a', 'A'); self.create('b', 'B'); self.configure()
        self.runtime('a', 'A', 13); self.runtime('b', 'B', 13)
        foreign = self.queue('a', 0, urgent=True, stage='review')
        saved = copy.deepcopy(read_json(self.pool / 'queue.json')[0])
        for index in range(12): self.assertEqual(self.acquire(self.queue('b', index))['status'], 'active')
        self.assertEqual(saved, read_json(self.pool / 'queue.json')[0])
        self.assertEqual(self.acquire(foreign)['status'], 'active')

    def test_same_parent_selection_keeps_owner_and_normal_batch_lane_fairness(self):
        self.create('a', 'A'); self.create('b', 'A'); self.configure(); self.runtime('a', 'A', 13)
        build = self.queue('a', 0); review = self.queue('b', 0, stage='review')
        denied = self.acquire(build); self.assertEqual(denied['selected']['token'], review['token'])
        self.assertFalse(denied['selected']['requester_can_acquire'])
        self.assertEqual(self.acquire(review)['status'], 'active'); self.release(review)
        self.assertEqual(self.acquire(build)['status'], 'active'); self.release(build)
        self.repairing('a', [1]); repair = self.queue('a', 1)
        a = self.queue('a', 2); b = self.queue('b', 1)
        self.assertEqual(self.acquire(repair)['status'], 'active'); self.release(repair)
        self.assertEqual(self.acquire(b)['status'], 'active'); self.release(b)
        self.assertEqual(self.acquire(a)['status'], 'active')

    def test_normal_aging_and_fifo_preserved_inside_parent(self):
        self.create('a', 'A'); self.configure(aging_seconds=10); self.runtime('a', 'A', 13)
        old = self.queue('a', 0); new = self.queue('a', 1)
        pool = read_json(self.pool / 'queue.json'); pool[0]['submitted_ns'] = time.time_ns() - 11_000_000_000
        pool[1]['priority'] = 9; write_json(self.pool / 'queue.json', pool)
        denied = self.acquire(new); self.assertEqual(denied['selected']['token'], old['token'])
        active = self.acquire(old); self.assertTrue(active['scheduler_admission']['aged'])
        self.assertEqual([q['priority'] for q in read_json(self.pool / 'queue.json')], [0, 9])

    def test_unknown_active_is_counted_in_every_parent_and_never_expands_capacity(self):
        self.create('old'); old = self.acquire(self.queue('old', 0))
        self.create('a', 'A'); self.create('b', 'B'); self.configure()
        self.runtime('a', 'A', 13); self.runtime('b', 'B', 13)
        for name in ('a', 'b'):
            self.fill(name, range(2)); self.assertFalse(self.acquire(self.queue(name, 2))['acquired'])
        rows = self.census()['groups']
        self.assertEqual([(row['worker_ceiling'], row['reserved_model_slots'], row['unknown_active_slots']) for row in rows], [(3, 3, 1)] * 2)
        self.assertEqual(old, read_json(self.pool / 'queue.json')[0])

    def test_separate_media_does_not_reduce_parent_model_capacity_and_keeps_resource_gates(self):
        self.create('a', 'A'); self.create('b', 'A'); self.configure(); self.runtime('a', 'A', 13)
        capture = self.queue('a', 11, stage='record')
        with patch('batch_control.memory_available_mb', return_value=1): self.assertEqual(self.acquire(capture)['reason'], 'memory_exhausted')
        with patch('batch_control.cpu_snapshot', return_value={'logical_processors': 32, 'cpu_load_percent': 100}):
            self.assertEqual(self.acquire(capture)['reason'], 'cpu_busy')
        media = self.acquire(capture); self.fill('a', range(11)); self.fill('b', range(1))
        self.assertFalse(self.acquire(self.queue('b', 1))['acquired'])
        row = self.census()['groups'][0]
        self.assertEqual([row['worker_ceiling'], row['reserved_model_slots']], [12, 12])
        self.assertEqual(media, read_json(self.pool / 'queue.json')[0])

    def test_invalid_binding_and_no_runtime_stay_conservative(self):
        self.create('a', 'A'); self.create('b', 'B'); self.configure(); self.runtime('a', 'A', 13)
        binding = scheduler.config(self.pool)['bindings']['a']; path = Path(binding['path'])
        path.write_bytes(path.read_bytes() + b' ')
        self.assertFalse(self.acquire(self.queue('a', 0))['acquired'])
        self.fill('b', range(3)); self.assertFalse(self.acquire(self.queue('b', 3))['acquired'])

    def test_switch_and_rollback_preserve_active_waiting_owner_run_permit_and_bindings(self):
        self.create('a', 'A'); helpers.AdaptiveSchedulerTests.configure(self); self.runtime('a', 'A', 13)
        active = self.acquire(self.queue('a', 0, stage='review'))
        work = self.root / 'a-0'; self.call('a', 'verify-review', '0', token=active['token'], value=work)
        waiting = self.queue('a', 1)
        queue_before = (self.pool / 'queue.json').read_bytes()
        protected = {str(p): digest(p) for p in self.pool.rglob('*.json') if p.name not in {'scheduler-config.json', 'mutation.lock'}}
        run_before = digest(work / '.product-v2/run.json'); bindings = copy.deepcopy(scheduler.config(self.pool)['bindings'])
        self.configure(); settings = scheduler.config(self.pool)
        self.assertEqual(settings['history'][-1]['previous']['capacity_scope'], scheduler.GLOBAL_CAPACITY_SCOPE)
        helpers.AdaptiveSchedulerTests.configure(self)
        settings = scheduler.config(self.pool)
        self.assertEqual(settings['history'][-1]['previous']['capacity_scope'], scheduler.RUNTIME_CAPACITY_SCOPE)
        self.assertEqual(settings['capacity_scope'], scheduler.GLOBAL_CAPACITY_SCOPE)
        self.assertEqual(queue_before, (self.pool / 'queue.json').read_bytes())
        self.assertEqual(bindings, settings['bindings']); self.assertEqual(run_before, digest(work / '.product-v2/run.json'))
        self.assertEqual(protected, {p: digest(Path(p)) for p in protected})

    def test_default_global_twelve_and_cross_parent_selection_remain_compatible(self):
        self.create('a', 'A'); self.create('b', 'B'); helpers.AdaptiveSchedulerTests.configure(self)
        self.runtime('a', 'A', 13); self.runtime('b', 'B', 13)
        a = self.queue('a', 0); b = self.queue('b', 0, stage='review')
        self.assertEqual(self.acquire(a)['selected']['token'], b['token'])
        self.acquire(b); self.release(b); self.acquire(a)
        self.fill('a', range(1, 10)); self.fill('b', range(1, 3))
        self.assertFalse(self.acquire(self.queue('b', 3))['acquired'])
        self.assertEqual(self.census()['active_model_reservations'], 12)
        self.assertEqual(self.census()['model_pool_capacity'], 12)

    def test_status_full_and_compact_make_no_global_or_actual_dispatch_claim(self):
        self.create('a', 'A'); self.configure(); self.runtime('a', 'A', 13); self.fill('a', range(2))
        before = {str(p): p.read_bytes() for p in self.pool.rglob('*') if p.is_file()}
        for extra in ([], ['--compact']):
            output = io.StringIO()
            with patch('sys.argv', ['batch_control.py', 'status', '--root', str(self.pool), '--batch-id', 'a', *extra]), patch('sys.stdout', output):
                self.assertEqual(batch.main(), 0)
            result = json.loads(output.getvalue())
            policy = result['scheduler']['runtime_policy'] if extra else result['scheduler_runtime_policy']
            self.assertEqual(policy['reservation_capacity_scope'], scheduler.RUNTIME_CAPACITY_SCOPE)
            self.assertFalse(policy['global_model_hard_limit']); self.assertIsNone(policy['model_pool_capacity'])
            self.assertIn('actual model service availability remains external', policy['capacity_scope'])
            census = result['scheduler']['reservations'] if extra else result['scheduler_reservations']
            self.assertEqual(census['groups'][0]['reserved_model_slots'], 2)
            self.assertIsNone(census['unreserved_global_model_slots'])
        self.assertEqual(before, {str(p): p.read_bytes() for p in self.pool.rglob('*') if p.is_file()})

    def test_scope_rejects_ambiguous_global_cap_and_nonadaptive_mode_atomically(self):
        self.create('a', 'A'); self.configure(); before = (self.pool / 'scheduler-config.json').read_bytes()
        for options in ({'model_pool_capacity': 12}, {'mode': scheduler.CONTRACT}, {'mode': 'legacy'}):
            with self.subTest(options=options), self.assertRaisesRegex(ValueError, 'scope'):
                self.configure(**options)
            self.assertEqual(before, (self.pool / 'scheduler-config.json').read_bytes())


if __name__ == '__main__': unittest.main()
