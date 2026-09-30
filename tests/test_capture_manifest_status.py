import unittest

from test_caseflow import flow
import capture_runner


class CaptureManifestStatusTests(unittest.TestCase):
    def test_decoded_real_capture_clears_pending_without_claiming_acceptance(self):
        manifest = {'recording_pending': True, 'status': 'ready_for_parent_recording'}
        report = {'decode_ok': True, 'video': 'recording/current/final.mp4',
                  'video_sha256': 'a' * 64}
        capture_runner.mark_recording_completed(manifest, report)
        self.assertIs(manifest['recording_pending'], False)
        self.assertEqual(manifest['status'], 'recorded_pending_independent_review')
        self.assertNotIn('pass', manifest['status'])

    def test_failed_decode_keeps_existing_pending_state(self):
        manifest = {'recording_pending': True, 'status': 'ready_for_parent_recording'}
        with self.assertRaises(capture_runner.CaptureError):
            capture_runner.mark_recording_completed(manifest, {'decode_ok': False})
        self.assertTrue(manifest['recording_pending'])
        self.assertEqual(manifest['status'], 'ready_for_parent_recording')

    def test_current_capture_replaces_stale_hash_and_application_flags_preserving_history(self):
        history = {'video': 'recording/old/final.mp4', 'sha256': 'b' * 64,
                   'status': 'retained_advisory_rejected_version'}
        manifest = {'recording_pending': True, 'video_sha256': 'b' * 64,
                    'recording_status': 'rerecord_required_after_owner_repair',
                    'video_current_for_application': False, 'previous_recording': history}
        report = {'decode_ok': True, 'video': 'recording/current/final.mp4',
                  'video_sha256': 'a' * 64}
        capture_runner.mark_recording_completed(manifest, report)
        self.assertEqual(manifest['video_sha256'], 'a' * 64)
        self.assertEqual(manifest['recording_status'], 'recorded_pending_independent_review')
        self.assertTrue(manifest['video_current_for_application'])
        self.assertEqual(manifest['previous_recording'], history)


if __name__ == '__main__':
    unittest.main()
