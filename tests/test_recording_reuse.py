"""Completed video reuse; fixtures do not claim live decoding/visual review."""
from pathlib import Path
import sys
import unittest
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
from common import digest,read_json,write_json,file_map
from proflow import completed_recording,finalize,inherited_execution
from test_construction_progress import DependencyFixture
import test_contracts as contract_fixtures

class CompletedRecordingTests(DependencyFixture):
    def test_later_software_data_copy_and_plan_edits_do_not_stale_completed_video(self):
        self.recorded();record_hash=digest(self.control/'recording.json')
        self.file('app.py','changed boundary calculation')
        self.file('web/app.js','changed minor business copy')
        self.file('data/input.csv','编号,值\n001,200\n')
        write_json(self.plan,{'input_files':['app.py'],'version':'later-data-version'})
        before=file_map(self.work);status=self.status()
        self.assertEqual(status['steps']['recording']['state'],'technical_ready')
        self.assertTrue(status['steps']['recording']['video_completed'])
        self.assertEqual(status['independent_visual_review'],'pending')
        self.assertNotIn('check-build then capture',status['next_actions'])
        self.assertEqual(digest(self.control/'recording.json'),record_hash)
        self.assertEqual(file_map(self.work),before)
    def test_completed_old_run_needs_no_new_record_or_confirmation(self):
        self.recorded();self.run.pop('construction_check_policy_version')
        self.file('app.py','changed current code')
        self.assertEqual(self.status()['steps']['recording']['state'],'technical_ready')
        self.assertFalse((self.control/'recording-reuse.json').exists())
    def test_capture_only_keeps_strict_original_input_recovery(self):
        self.recorded();(self.control/'recording.json').unlink()
        self.file('app.py','changed before complete video')
        self.assertEqual(self.status()['steps']['recording']['state'],'stale')
    def test_real_failed_receipt_never_becomes_completed(self):
        self.recorded();record=read_json(self.control/'recording.json');record['passed']=False
        write_json(self.control/'recording.json',record)
        self.assertEqual(self.status()['steps']['recording']['state'],'failed')
        with self.assertRaises(ValueError):completed_recording(self.work,record,Path(self.run['video']))
    def test_bad_video_and_missing_technical_evidence_do_not_pass(self):
        self.recorded();record=read_json(self.control/'recording.json')
        Path(self.run['video']).write_bytes(b'damaged MP4')
        with self.assertRaises(ValueError):completed_recording(self.work,record,Path(self.run['video']))
        self.assertNotEqual(self.status()['steps']['recording']['state'],'technical_ready')
        self.recorded();(self.work/'evidence/timeline.json').unlink()
        self.assertEqual(self.status()['steps']['recording']['state'],'captured')
        self.assertEqual(self.status()['next_actions'],['evidence'])
    def test_changed_original_technical_receipt_cannot_reuse(self):
        self.recorded();record=read_json(self.control/'recording.json')
        timeline=self.work/'evidence/timeline.json';value=read_json(timeline);value['decode_ok']=False
        write_json(timeline,value)
        with self.assertRaises(ValueError):completed_recording(self.work,record,Path(self.run['video']))
    def test_actual_major_system_or_operation_change_requires_video_work(self):
        self.recorded();self.checks['video_material_change']='Primary workflow replaced with a different operation path'
        self.save_checks();record=read_json(self.control/'recording.json')
        with self.assertRaisesRegex(ValueError,'major system/operation change'):
            completed_recording(self.work,record,Path(self.run['video']))
        self.assertNotEqual(self.status()['steps']['recording']['state'],'technical_ready')

class FinalCompletedRecordingTests(unittest.TestCase):
    def setUp(self):
        self.f=contract_fixtures.ContractTests();self.f.setUp();f=self.f
        f.proof.update(checks=f.runtime_records(f.work,f.out),reviewed_files=f.files,visual_notes=['fixture'],
            limitations=['contract fixture, not real review'],source_zip_sha256=digest(f.system/'项目源码.zip'))
        f.make_media_fixture(f.work,f.out)
        self.record_hash=digest(f.work/'.product-v2/recording.json')
        (f.work/'app.py').write_text('print(2) # later data parameter\n',encoding='utf8')
        package=read_json(f.work/'.product-v2/source-package.json');package['files']['app.py']=digest(f.work/'app.py')
        write_json(f.work/'.product-v2/source-package.json',package)
        f.proof['video_timeline_sha256']=read_json(f.work/'.product-v2/controlled-video.json')['sha256'];f.save_proof()
    def tearDown(self):self.f.tearDown()
    def test_finalize_and_inheritance_reuse_media_without_new_review_protocol(self):
        f=self.f
        with patch('proflow.cleanup_ready'),patch('contracts.SESSION_ROOT',f.sessions):
            result=finalize(f.work,f.out,f.proof_path)
        self.assertEqual(result['status'],'complete')
        self.assertEqual(len(inherited_execution({'workspace':f.work,'output':f.out,'proof':f.proof})),6)
        self.assertEqual(digest(f.work/'.product-v2/recording.json'),self.record_hash)
        self.assertNotIn('recording_reuse',f.proof)
    def test_current_source_gate_stays_strict(self):
        f=self.f;(f.work/'app.py').write_text('changed after packing',encoding='utf8')
        with patch('proflow.cleanup_ready'),self.assertRaisesRegex(ValueError,'Source changed after packaging'):
            finalize(f.work,f.out,f.proof_path)
    def test_finalize_and_inherited_execution_do_not_stale_completed_csv_for_raw_input(self):
        f=self.f;(f.work/'input.csv').unlink()
        with patch('proflow.cleanup_ready'),patch('contracts.SESSION_ROOT',f.sessions):
            self.assertEqual(finalize(f.work,f.out,f.proof_path)['status'],'complete')
        self.assertEqual(len(inherited_execution({'workspace':f.work,'output':f.out,'proof':f.proof})),6)
    def test_missing_or_changed_original_frame_still_fails_final_gate(self):
        f=self.f;(f.work/'.product-v2/video-timeline/frame-020.jpg').write_bytes(b'damaged frame')
        with patch('proflow.cleanup_ready'),patch('contracts.SESSION_ROOT',f.sessions):
            with self.assertRaisesRegex(ValueError,'frame hash/path changed'):finalize(f.work,f.out,f.proof_path)

if __name__=='__main__':unittest.main()
