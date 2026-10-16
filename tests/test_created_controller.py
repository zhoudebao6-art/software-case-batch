"""Native create_thread creates an independent user-owned chat, not a worker."""
import copy
import json
import unittest
from test_scheduler_adaptive import AdaptiveSchedulerTests as Helpers
import scheduler_policy as scheduler
from common import read_json, write_json


class CreatedControllerTests(unittest.TestCase):
    setUp = Helpers.setUp
    tearDown = Helpers.tearDown
    create = Helpers.create
    call = Helpers.call
    request = Helpers.request
    bind = Helpers.bind
    configure = Helpers.configure
    runtime = Helpers.runtime
    queue = Helpers.queue
    acquire = Helpers.acquire
    fill = Helpers.fill

    def rewrite_meta(self, log, **updates):
        lines = log.read_bytes().splitlines(keepends=True)
        meta = json.loads(lines[0]); meta['payload'].update(updates)
        log.write_bytes((json.dumps(meta) + '\n').encode() + b''.join(lines[1:]))

    def created_request(self):
        self.create('a')
        request = self.request('a', 'A'); _, log = self.logs['A']
        self.rewrite_meta(log, thread_source='agent_created_thread')
        return request, log

    def test_created_root_binds_actual_owner_and_preserves_runtime_capacity(self):
        request, log = self.created_request()
        self.call('a', 'bind-controller', value=request, authorization='user explicitly asked for this independent chat')
        self.configure(); self.runtime('a', 'A', 13)
        self.fill('a', range(4))
        settings = scheduler.config(self.pool)
        binding = scheduler.verified_binding(self.pool, 'a', settings)
        self.assertEqual(binding['group'], self.logs['A'][0])
        row = scheduler.snapshot(self.pool, read_json(self.pool/'queue.json'), settings)['groups'][0]
        self.assertEqual([row['worker_ceiling'], row['reserved_model_slots']], [12, 4])

    def test_created_label_does_not_allow_child_foreign_or_unknown_identity(self):
        request, log = self.created_request(); original = log.read_bytes()
        for update in (
            {'parent_thread_id': 'another-parent'},
            {'source': {'subagent': {'thread_spawn': {}}}},
            {'source': {}},
            {'thread_source': 'subagent'},
            {'thread_source': 'unknown'},
            {'thread_source': None},
            {'session_id': 'different-id'},
        ):
            with self.subTest(update=update):
                log.write_bytes(original); self.rewrite_meta(log, **update)
                with self.assertRaises(ValueError):
                    self.call('a', 'bind-controller', value=request, authorization='cannot impersonate independent owner')
                self.assertFalse((self.pool/'scheduler-config.json').exists())

    def test_created_root_still_needs_actual_successful_matching_command(self):
        request, log = self.created_request(); original = log.read_bytes()
        for fault in ('foreign_batch', 'failed', 'quoted', 'different_pid'):
            with self.subTest(fault=fault):
                rows=[json.loads(line) for line in original.splitlines()]
                item=rows[1]['payload']['item']
                if fault == 'foreign_batch': item['command'][-1]=item['command'][-1].replace("--batch-id 'a'", "--batch-id 'foreign'")
                if fault == 'different_pid': item['command'][-1]=item['command'][-1].replace('--pid 101', '--pid 102')
                if fault == 'failed': item['exit_code']=1
                if fault == 'quoted': rows[1]={'type':'response_item','payload':{'type':'message','role':'user','content':[{'text':json.dumps(rows[1])}]}}
                log.write_text(''.join(json.dumps(row)+'\n' for row in rows),encoding='utf-8')
                with self.assertRaises(ValueError):
                    self.call('a', 'bind-controller', value=request, authorization='actual matching command required')

    def test_changed_created_root_metadata_invalidates_frozen_binding(self):
        request, log = self.created_request()
        self.call('a', 'bind-controller', value=request, authorization='authorized root')
        settings=scheduler.config(self.pool)
        self.assertIsNotNone(scheduler.verified_binding(self.pool, 'a', settings))
        self.rewrite_meta(log, parent_thread_id='changed-to-child')
        self.assertIsNone(scheduler.verified_binding(self.pool, 'a', settings))


if __name__ == '__main__': unittest.main()
