"""A short Windows sharing race is retriable; persistent denial remains failure."""
import io
import json
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch
from test_caseflow import flow


class StateReadRaceTests(unittest.TestCase):
    def test_unreadable_registered_manifest_fails_closed(self):
        import tempfile
        from pathlib import Path
        with tempfile.TemporaryDirectory() as temp:
            cfg = {'_root': Path(temp).resolve()}
            manifest = cfg['_root'] / '.batches' / 'existing' / 'manifest.json'
            manifest.parent.mkdir(parents=True)
            manifest.write_text('{"batch_id":"existing"}', encoding='utf-8')
            with patch.object(flow, 'read_json', side_effect=PermissionError(13, 'sharing denial')):
                with self.assertRaises(flow.Blocked):
                    flow.batch_folder(cfg, 'other')

    def test_windows_transient_open_denial_recovers_without_default_state(self):
        path = SimpleNamespace(open=Mock(side_effect=[PermissionError(13, 'sharing race'), io.StringIO('{"stage":"running"}')]))
        with patch.object(flow.os, 'name', 'nt'), patch.object(flow.time, 'sleep') as sleep:
            self.assertEqual(flow.read_json(path), {'stage':'running'})
        self.assertEqual(path.open.call_count, 2)
        sleep.assert_called_once()

    def test_persistent_denial_is_bounded_and_propagates(self):
        denied = PermissionError(13, 'real ACL refusal')
        path = SimpleNamespace(open=Mock(side_effect=denied))
        with patch.object(flow.os, 'name', 'nt'), patch.object(flow.time, 'sleep'), self.assertRaises(PermissionError) as caught:
            flow.read_json(path)
        self.assertIs(caught.exception, denied)
        self.assertEqual(path.open.call_count, 10)

    def test_malformed_json_and_nonwindows_denial_are_not_retried(self):
        path = SimpleNamespace(open=Mock(return_value=io.StringIO('not JSON')))
        with patch.object(flow.time, 'sleep') as sleep, self.assertRaises(json.JSONDecodeError):
            flow.read_json(path)
        sleep.assert_not_called()
        path.open=Mock(side_effect=PermissionError(13, 'denied'))
        with patch.object(flow.os, 'name', 'posix'), patch.object(flow.time, 'sleep') as sleep, self.assertRaises(PermissionError):
            flow.read_json(path)
        sleep.assert_not_called()
