"""Real JSONL-shaped user event ordering; no production control files written."""
import copy
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import unittest
import uuid
from unittest.mock import patch
import test_scheduler_groups as helpers
import batch_control as batch
from common import digest, read_json, write_json


class ControlDecisionTests(unittest.TestCase):
    setUp = helpers.SchedulerGroupsTests.setUp
    tearDown = helpers.SchedulerGroupsTests.tearDown
    call = helpers.SchedulerGroupsTests.call
    create = helpers.SchedulerGroupsTests.create
    request = helpers.SchedulerGroupsTests.request
    bind = helpers.SchedulerGroupsTests.bind
    queue = helpers.SchedulerGroupsTests.queue
    acquire = helpers.SchedulerGroupsTests.acquire

    def instruction(self, action, timestamp, role='user', batch_id='a'):
        source_id = str(uuid.uuid4()); log = self.sessions / ('rollout-test-' + source_id + '.jsonl')
        meta = {'type': 'session_meta', 'payload': {'id': source_id, 'thread_source': 'user', 'source': 'vscode'}}
        header = (json.dumps(meta) + '\n').encode()
        statement = '先让其他两批建设加急' if action == 'drain' else '莉莉2还没做完，继续一下'
        event = {'timestamp': timestamp, 'type': 'response_item', 'payload': {'type': 'message',
            'role': role, 'content': [{'type': 'input_text', 'text': statement}]}}
        raw = (json.dumps(event, ensure_ascii=False) + '\n').encode(); log.write_bytes(header + raw)
        path = self.root / (uuid.uuid4().hex + '.json')
        write_json(path, {'batch_id': batch_id, 'action': action, 'statement': statement,
            'user_evidence': {'path': str(log), 'offset': len(header), 'size': len(raw),
                              'sha256': hashlib.sha256(raw).hexdigest(), 'timestamp': timestamp}})
        return path

    def test_new_resume_rejects_two_replays_of_yesterdays_pause_without_touching_tickets(self):
        self.create('a', 'a'); active = self.acquire(self.queue('a', 0)); waiting = self.queue('a', 1)
        before = copy.deepcopy(read_json(self.pool / 'queue.json'))
        old = self.instruction('drain', '2026-10-14T07:34:02.241Z')
        self.call('a', 'drain', value=old, authorization='original real user event')
        self.assertFalse(self.acquire(waiting)['acquired'])
        new = self.instruction('continue', '2026-10-15T08:19:04.428Z')
        resumed = self.call('a', 'continue', value=new, authorization='later real user resume')
        self.assertFalse(resumed['drain']); self.assertEqual(resumed['control_decision']['revision'], 2)
        for _ in range(2):
            with self.assertRaisesRegex(ValueError, 'Stale control instruction'):
                self.call('a', 'drain', value=old, authorization='reapplied old receipt')
        self.assertEqual(before, read_json(self.pool / 'queue.json'))
        self.assertEqual(self.acquire(waiting)['status'], 'active')
        self.assertEqual(next(q for q in read_json(self.pool / 'queue.json') if q['token'] == active['token']), active)

    def test_model_text_tool_output_foreign_scope_and_forged_time_are_not_authorization(self):
        self.create('a', 'a')
        for role in ('assistant', 'tool', 'developer'):
            with self.subTest(role=role), self.assertRaisesRegex(ValueError, 'not new user authorization'):
                self.call('a', 'drain', value=self.instruction('drain', '2026-10-15T01:00:00Z', role), authorization='model said so')
        foreign = self.instruction('drain', '2026-10-15T01:00:00Z', batch_id='b')
        with self.assertRaisesRegex(ValueError, 'registered batch'):
            self.call('a', 'drain', value=foreign, authorization='foreign')
        request = self.instruction('drain', '2026-10-15T01:00:00Z'); value = read_json(request)
        value['user_evidence']['timestamp'] = '2026-10-16T01:00:00Z'; write_json(request, value)
        with self.assertRaisesRegex(ValueError, 'timestamp differs'):
            self.call('a', 'drain', value=request, authorization='forged newer time')
        self.assertFalse(read_json(self.pool / 'a/state.json')['drain'])

    def test_legacy_calls_and_already_authorized_continue_remain_compatible(self):
        self.create('a', 'a')
        self.assertTrue(self.call('a', 'drain', authorization='legacy pause')['drain'])
        self.assertFalse(self.call('a', 'continue', authorization='legacy resume')['drain'])
        request = self.instruction('continue', '2026-10-15T02:00:00Z')
        self.call('a', 'continue', value=request, authorization='real resume')
        before = digest(self.pool / 'a/state.json')
        self.call('a', 'continue', authorization='existing authorized resume')
        self.assertEqual(before, digest(self.pool / 'a/state.json'))
        with self.assertRaisesRegex(ValueError, 'text cannot supersede'):
            self.call('a', 'drain', authorization='assistant repeats old pause')
        # A newer genuine pause is accepted and the subsequent genuine resume
        # remains available; there is no permanent pause or resume latch.
        pause = self.instruction('drain', '2026-10-15T03:00:00Z')
        self.call('a', 'drain', value=pause, authorization='new human pause')
        resume = self.instruction('continue', '2026-10-15T04:00:00Z')
        self.assertFalse(self.call('a', 'continue', value=resume, authorization='new human resume')['drain'])

    def test_same_event_cannot_reverse_action_and_changed_event_fails_closed(self):
        self.create('a', 'a'); request = self.instruction('continue', '2026-10-15T02:00:00Z')
        self.call('a', 'continue', value=request, authorization='real resume')
        value = read_json(request); value['action'] = 'drain'; write_json(request, value)
        with self.assertRaisesRegex(ValueError, 'Ambiguous or stale'):
            self.call('a', 'drain', value=request, authorization='reuse resume as pause')
        Path(value['user_evidence']['path']).write_bytes(b'changed event')
        with self.assertRaises((ValueError, json.JSONDecodeError)):
            self.call('a', 'continue', authorization='idempotent cannot hide changed user proof')

    def test_future_raw_event_is_rejected_without_poisoning_a_later_human_resume(self):
        self.create('a', 'a'); state_path = self.pool / 'a/state.json'; original = state_path.read_bytes()
        for action in ('drain', 'continue'):
            with self.subTest(action=action), self.assertRaisesRegex(ValueError, 'future beyond'):
                self.call('a', action, value=self.instruction(action, '2099-10-15T01:00:00Z'), authorization='far future raw user event')
            self.assertEqual(state_path.read_bytes(), original)
        resumed = self.call('a', 'continue', value=self.instruction('continue', '2026-10-15T01:00:00Z'), authorization='real human resume')
        self.assertFalse(resumed['drain']); self.assertEqual(resumed['control_decision']['revision'], 1)

    def test_small_clock_skew_is_bounded_to_five_minutes(self):
        self.create('a', 'a'); now_ns = int(datetime(2026, 10, 15, 10, tzinfo=timezone.utc).timestamp()) * 1000000000
        with patch('control_decisions.time.time_ns', return_value=now_ns):
            accepted = self.call('a', 'drain', value=self.instruction('drain', '2026-10-15T10:05:00Z'), authorization='bounded clock skew')
            self.assertTrue(accepted['drain'])
            before = (self.pool / 'a/state.json').read_bytes()
            with self.assertRaisesRegex(ValueError, 'future beyond'):
                self.call('a', 'drain', value=self.instruction('drain', '2026-10-15T10:05:01Z'), authorization='out of tolerance')
            self.assertEqual((self.pool / 'a/state.json').read_bytes(), before)
        with patch('control_decisions.time.time_ns', return_value=now_ns + 360 * 1000000000):
            resumed = self.call('a', 'continue', value=self.instruction('continue', '2026-10-15T10:06:00Z'), authorization='later actual resume')
            self.assertFalse(resumed['drain'])


if __name__ == '__main__': unittest.main()
