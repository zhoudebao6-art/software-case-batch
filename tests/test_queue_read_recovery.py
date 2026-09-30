"""Queue admission shares the bounded Windows state-read recovery contract."""
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import test_caseflow as fixtures
from test_caseflow import flow
import case_queue


class QueueReadRecoveryTests(unittest.TestCase):
    def test_transient_ticket_read_denial_retries_without_losing_admission(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp) / 'slot'
            original = Path.open
            denied = []

            def opening(path, mode='r', *args, **kwargs):
                if path.parent.name == 'queue' and not path.name.startswith('.') and mode == 'r' and not denied:
                    denied.append(path)
                    raise PermissionError(13, 'transient sharing race')
                return original(path, mode, *args, **kwargs)

            with patch.object(Path, 'open', opening), patch.object(case_queue.time, 'sleep'):
                with case_queue.fair_slot(root, 1, flow.BatchLock, flow.Busy, flow.atomic_json):
                    self.assertEqual(len(denied), 1)
            self.assertEqual(list((root / 'queue').glob('*.json')), [])

    def test_persistent_ticket_read_denial_is_bounded_and_propagates(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp) / 'slot'
            original = Path.open
            attempts = []

            def opening(path, mode='r', *args, **kwargs):
                if path.parent.name == 'queue' and not path.name.startswith('.') and mode == 'r':
                    attempts.append(path)
                    raise PermissionError(13, 'persistent denied')
                return original(path, mode, *args, **kwargs)

            with patch.object(Path, 'open', opening), patch.object(case_queue.time, 'sleep'), self.assertRaises(PermissionError):
                with case_queue.fair_slot(root, 1, flow.BatchLock, flow.Busy, flow.atomic_json):
                    self.fail('Denied ticket cannot acquire a slot')
            self.assertEqual(len(attempts), 10 if case_queue.os.name == 'nt' else 1)
            self.assertEqual(list((root / 'queue').glob('*.json')), [])

    def test_malformed_published_ticket_is_not_retried_or_silently_dropped(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp) / 'slot'
            queue = root / 'queue'
            queue.mkdir(parents=True)
            invalid = queue / 'invalid.json'
            invalid.write_text('{malformed', encoding='utf-8')
            with patch.object(case_queue.time, 'sleep') as sleep, self.assertRaises(json.JSONDecodeError):
                with case_queue.fair_slot(root, 1, flow.BatchLock, flow.Busy, flow.atomic_json):
                    self.fail('Malformed state cannot be ignored')
            sleep.assert_not_called()
            self.assertTrue(invalid.is_file())


if __name__ == '__main__':
    unittest.main()
