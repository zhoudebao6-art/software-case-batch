import json, tempfile, unittest
from pathlib import Path
from unittest.mock import patch
import test_caseflow
from controlled_evidence import sync_trusted_capture_metadata
from caseflow import sha256

class CurrentCaptureBindingTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory(); self.case=Path(self.tmp.name).resolve()
        (self.case/'evidence').mkdir(); (self.case/'video.mp4').write_bytes(b'current fixture video')
        self.health={'case_id':'case','workspace':str(self.case),'version':'v2'}
        self.report={'mode':'record','video':'video.mp4','video_sha256':sha256(self.case/'video.mp4'),'decode_ok':True,'health':self.health}
        self.manifest={'video':'video.mp4','capture_report':'evidence/report.json','capture_plan':'evidence/plan.json','video_sha256':'old','recording_pending':True,'recording_status':'rerecord_required','previous_recording':{'video':'old.mp4'}}
        (self.case/'evidence/plan.json').write_text(json.dumps({'base_url':'http://127.0.0.1:18177'}))
        self.save()
    def tearDown(self):self.tmp.cleanup()
    def save(self):(self.case/'evidence/report.json').write_text(json.dumps(self.report))
    def run_sync(self,current=None):
        with patch('capture_runner.validate_plan'),patch('capture_runner.service_ready',return_value=current or self.health):
            sync_trusted_capture_metadata(self.case,self.manifest)
    def test_current_decoded_capture_updates_stale_metadata_and_preserves_history(self):
        self.run_sync()
        self.assertEqual(self.manifest['video_sha256'],self.report['video_sha256'])
        self.assertFalse(self.manifest['recording_pending'])
        self.assertEqual(self.manifest['recording_status'],'recorded_pending_independent_review')
        self.assertEqual(self.manifest['previous_recording'],{'video':'old.mp4'})
    def test_probe_or_changed_video_cannot_clear_pending(self):
        for key,value in [('mode','probe'),('video_sha256','old')]:
            before=dict(self.report); self.report[key]=value; self.save()
            with self.assertRaises(ValueError):self.run_sync()
            self.assertTrue(self.manifest['recording_pending'])
            self.report=before
    def test_changed_service_cannot_mark_video_current(self):
        with self.assertRaises(ValueError):self.run_sync({**self.health,'version':'v3'})
        self.assertTrue(self.manifest['recording_pending'])
    def test_no_trusted_capture_preserves_legacy_metadata(self):
        self.manifest.pop('capture_report'); before=dict(self.manifest)
        sync_trusted_capture_metadata(self.case,self.manifest)
        self.assertEqual(self.manifest,before)
    def test_pending_owner_repair_cannot_bind_a_completed_recording(self):
        (self.case/'evidence/repair-status.json').write_text(json.dumps({'status':'pending_owner_repair','required_action':'Fix exact threshold form'}))
        with self.assertRaisesRegex(ValueError,'Fix exact threshold form'):self.run_sync()
        self.assertTrue(self.manifest['recording_pending'])
        (self.case/'evidence/repair-status.json').write_text(json.dumps({'status':'ready_for_review','required_action':'Historical instruction'}))
        self.run_sync()
        self.assertFalse(self.manifest['recording_pending'])
    def test_declared_current_audit_hash_tracks_actual_recorder_updated_file(self):
        audit=self.case/'evidence/audit.json'; audit.write_text('{"pages":[]}')
        self.manifest.update(ui_text_audit='evidence/audit.json',ui_text_audit_sha256='old-audit')
        self.run_sync()
        self.assertEqual(self.manifest['ui_text_audit_sha256'],sha256(audit))

    def test_frozen_legacy_capture_reference_does_not_certify_or_block_new_legacy_video(self):
        self.report['video_sha256']='historical-video'; self.save()
        before=dict(self.manifest)
        sync_trusted_capture_metadata(self.case,self.manifest,pipeline_profile='legacy')
        self.assertEqual(self.manifest,before)

    def test_worker_legacy_label_cannot_downgrade_frozen_efficient_binding(self):
        self.manifest['pipeline_profile']='legacy'
        self.report['video_sha256']='historical-video'; self.save()
        with self.assertRaisesRegex(ValueError,'does not bind current video'):
            sync_trusted_capture_metadata(self.case,self.manifest,pipeline_profile='efficient-v1')

    def test_profile_comes_from_registered_case_workspace_and_source_identity(self):
        from controlled_evidence import registered_pipeline_profile
        from caseflow import atomic_json
        workspace=self.case/'cases'; case=workspace/'2026-09'/'registered';case.mkdir(parents=True)
        batch=workspace/'.batches'/'batch';batch.mkdir(parents=True)
        entry={'case_id':'registered','workspace_name':'registered','workspace_relative':'2026-09/registered','source_sha256':'source'}
        manifest={'case_id':'registered','source_sha256':'source','pipeline_profile':'efficient-v1'}
        cfg={'runner':{'workspace_root':str(workspace)}}
        atomic_json(batch/'manifest.json',{'cases':[entry]})
        self.assertEqual(registered_pipeline_profile(case,manifest,cfg),'legacy')
        atomic_json(batch/'manifest.json',{'pipeline_profile':'efficient-v1','cases':[entry]})
        manifest['pipeline_profile']='legacy'
        self.assertEqual(registered_pipeline_profile(case,manifest,cfg),'efficient-v1')
        manifest.pop('case_id')
        self.assertEqual(registered_pipeline_profile(case,manifest,cfg),'efficient-v1')
        manifest['source_sha256']='other'
        self.assertIsNone(registered_pipeline_profile(case,manifest,cfg))
