"""Media jobs must not lower independently accounted model concurrency."""
import unittest
from unittest.mock import patch
from test_scheduler_adaptive import AdaptiveSchedulerTests
import scheduler_policy as scheduler
from common import read_json


class MediaModelCapacityTests(unittest.TestCase):
    setUp = AdaptiveSchedulerTests.setUp
    tearDown = AdaptiveSchedulerTests.tearDown
    call = AdaptiveSchedulerTests.call
    create = AdaptiveSchedulerTests.create
    request = AdaptiveSchedulerTests.request
    bind = AdaptiveSchedulerTests.bind
    queue = AdaptiveSchedulerTests.queue
    acquire = AdaptiveSchedulerTests.acquire
    fill = AdaptiveSchedulerTests.fill
    configure = AdaptiveSchedulerTests.configure
    runtime = AdaptiveSchedulerTests.runtime

    def test_unbound_separate_media_keeps_twelve_model_slots(self):
        self.create('a', 'A'); self.configure(); self.runtime('a', 'A', 13)
        media = self.acquire(self.queue('a', 11, stage='record'))
        self.assertEqual(media['status'], 'active')
        settings = scheduler.config(self.pool)
        self.assertIsNone(scheduler.active_group(self.pool, media, settings))
        self.fill('a', range(3))
        row = scheduler.snapshot(self.pool, read_json(self.pool / 'queue.json'), settings)['groups'][0]
        self.assertEqual([row['worker_ceiling'], row['reserved_model_slots'], row['unreserved_model_slots']], [12, 3, 9])
        self.assertEqual(self.acquire(self.queue('a', 3, stage='review'))['status'], 'active')
        self.fill('a', range(4, 11))
        self.create('b', 'B'); self.runtime('b', 'B', 13)
        self.assertEqual(self.acquire(self.queue('b', 0))['status'], 'active')
        self.assertFalse(self.acquire(self.queue('b', 1))['acquired'])
        self.assertEqual(media, read_json(self.pool / 'queue.json')[0])

    def test_unbound_legacy_media_still_limits_model_capacity(self):
        self.create('old', legacy=True)
        media = self.acquire(self.queue('old', 0, stage='record'))
        self.create('a', 'A'); self.configure(); self.runtime('a', 'A', 13)
        self.fill('a', range(2))
        self.assertFalse(self.acquire(self.queue('a', 2, stage='review'))['acquired'])
        row = scheduler.snapshot(self.pool, read_json(self.pool / 'queue.json'), scheduler.config(self.pool))['groups'][0]
        self.assertEqual([row['worker_ceiling'], row['reserved_model_slots']], [3, 3])
        self.assertEqual(media, read_json(self.pool / 'queue.json')[0])

    def test_unknown_model_ticket_still_limits_every_group(self):
        self.create('old'); self.acquire(self.queue('old', 0))
        self.create('a', 'A'); self.configure(); self.runtime('a', 'A', 13)
        self.fill('a', range(2))
        self.assertFalse(self.acquire(self.queue('a', 2, stage='review'))['acquired'])
        row = scheduler.snapshot(self.pool, read_json(self.pool / 'queue.json'), scheduler.config(self.pool))['groups'][0]
        self.assertEqual([row['worker_ceiling'], row['reserved_model_slots']], [3, 3])


if __name__ == '__main__':
    unittest.main()
