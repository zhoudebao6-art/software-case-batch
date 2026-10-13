"""Deterministic media-policy tests and an opt-in small encoded fixture."""
import copy
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch
from PIL import Image,ImageChops

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
import _video_evidence_core as core
from common import digest,read_json,write_json
from media_evidence import generate,validate,validate_recording_duration

def flow_proof(seconds=84):
    actions=['fill','click','select','press','download','click']
    starts=[1,12,23,35,48,seconds-9]
    return {'recording_policy_version':'flow-complete-v1','duration':seconds,'estimated_duration_seconds':82,
        'timeout_seconds':180,'planned_step_count':6,'completed_step_count':6,
        'events':[{'action':action,'started':start,'completed':start+1} for action,start in zip(actions,starts)],
        'final_result_completion':{'selector':'#result','reading_seconds':7,'reading_reason':'阅读本次处理结果',
            'observed_at':seconds-7,'completed_at':seconds,'completed':True}}

class DurationPolicyTests(unittest.TestCase):
    def test_new_flow_has_different_actual_durations_and_no75_or120_cap(self):
        for seconds in (68,84,96,127):
            proof=flow_proof(seconds)
            self.assertEqual(validate_recording_duration(proof,'flow-complete-v1')['duration'],seconds)
    def test_legacy_receipts_keep_frozen_range_and_cannot_satisfy_new_policy(self):
        self.assertEqual(validate_recording_duration({'duration':60})['recording_policy_version'],'legacy-fixed-v1')
        for seconds in (54,76):
            with self.assertRaises(ValueError):validate_recording_duration({'duration':seconds})
        with self.assertRaisesRegex(ValueError,'frozen run'):validate_recording_duration({'duration':60},'flow-complete-v1')
        with self.assertRaisesRegex(ValueError,'Unknown'):validate_recording_duration({'duration':84,'recording_policy_version':'future'})
    def test_configured_estimate_cannot_replace_media_measurement_or_completion(self):
        proof=flow_proof()
        with self.assertRaises(ValueError):validate_recording_duration(proof,duration=60)
        with self.assertRaisesRegex(ValueError,'differs'):validate_recording_duration(proof,duration=84.5)
        for mutation in ('not-complete','partial-flow','dwell-short','outside-video','final-before-action','timeout-target','uniform-clicks','nan-event'):
            value=copy.deepcopy(proof)
            if mutation=='not-complete':value['final_result_completion']['completed']=False
            if mutation=='partial-flow':value['completed_step_count']=5
            if mutation=='dwell-short':value['final_result_completion']['observed_at']=83
            if mutation=='outside-video':value['events'][-1]['completed']=90
            if mutation=='final-before-action':value['final_result_completion']['observed_at']=70
            if mutation=='timeout-target':value['timeout_seconds']=82
            if mutation=='uniform-clicks':
                for event in value['events']:event['action']='click'
            if mutation=='nan-event':value['events'][0]['started']=float('nan')
            with self.subTest(mutation=mutation),self.assertRaises(ValueError):validate_recording_duration(value)
    def test_operation_reading_is_bound_to_actual_result_and_following_action(self):
        proof=flow_proof();first=proof['events'][0]
        first.update(reading_seconds=3,reading_reason='检查查询结果',reading_started=2,reading_completed=5)
        validate_recording_duration(proof)
        first['reading_completed']=1
        with self.assertRaisesRegex(ValueError,'reading'):validate_recording_duration(proof)

class DecodePipelineTests(unittest.TestCase):
    def test_one_full_decode_covers_sampling_signals_and_duplicate_event_targets(self):
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary);video=root/'fixture.mp4';video.write_bytes(b'encoded-fixture-placeholder')
            calls=[];duration=8.4;fps=25
            def run(args,tools=None):
                calls.append(args)
                if args[0]=='ffprobe':
                    return subprocess.CompletedProcess(args,0,json.dumps({'format':{'duration':str(duration)},'streams':[
                        {'codec_type':'video','avg_frame_rate':'25/1','width':160,'height':90,'codec_name':'h264','pix_fmt':'yuv420p'}]}),'')
                if '-filter_complex' in args:
                    target=root/'evidence';frames=target/'frames';selected=target/'interaction-selected'
                    for i in range(42):Image.new('RGB',(16,9),(i,20,40)).save(frames/f'frame-{i+1:05d}.jpg')
                    import re
                    expression=args[args.index('-filter_complex')+1]
                    numbers=sorted({int(n) for n in re.findall(r'eq\(n\\,(\d+)\)',expression)})
                    for i,n in enumerate(numbers):Image.new('RGB',(16,9),(n%256,30,50)).save(selected/f'frame-{i+1:06d}.jpg')
                    return subprocess.CompletedProcess(args,0,'frame=210\nprogress=end\n','[blackdetect] black_start:0 black_end:0.1\n')
                Image.new('RGB',(16,9),(90,20,30)).save(root/'evidence/frames/last.jpg')
                return subprocess.CompletedProcess(args,0,'','')
            events=[{'action':'click','started':1,'completed':2},{'action':'select','started':1,'completed':2}]
            with patch.object(core,'command',side_effect=run):
                report=core.generate(video,root/'evidence',tool_paths={'ffmpeg':'fixture','ffprobe':'fixture'},interaction_events=events)
            self.assertEqual(report['source_frame_count'],210);self.assertEqual(report['full_decode_passes'],1)
            self.assertEqual(len(report['frames']),44);self.assertEqual(len(report['interaction_frames']),4)
            self.assertEqual(report['interaction_frames'][0]['sha256'],report['interaction_frames'][2]['sha256'])
            self.assertNotEqual(report['interaction_frames'][0]['file'],report['interaction_frames'][2]['file'])
            self.assertTrue(report['automatic_signals']);self.assertTrue(report['decode_ok'])
            self.assertEqual(sum('-filter_complex' in c for c in calls),1)
            self.assertEqual(len(calls),3);self.assertNotIn('-count_frames',calls[0])
            self.assertIn('-sseof',calls[-1]);self.assertEqual(calls[-1][calls[-1].index('-sseof')+1],'-0.5')
            self.assertEqual([p for c in report['contact_sheets'] for p in c['frame_files']],[f['file'] for f in report['frames']])
    def test_decode_failure_never_produces_a_successful_timeline(self):
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary);video=root/'bad.mp4';video.write_bytes(b'bad')
            meta={'format':{'duration':'8.4'},'streams':[{'codec_type':'video','avg_frame_rate':'25/1'}]}
            with patch.object(core,'command',side_effect=[subprocess.CompletedProcess([],0,json.dumps(meta),''),subprocess.CalledProcessError(1,['ffmpeg'],stderr='decode failure')]):
                with self.assertRaises(subprocess.CalledProcessError):core.generate(video,root/'evidence')
            self.assertFalse((root/'evidence/timeline.json').exists())

@unittest.skipUnless(os.environ.get('SCB_PRO_MEDIA_FIXTURE')=='1','Opt-in low-resolution encoded media fixture; never runs a browser')
class EncodedFixtureTests(unittest.TestCase):
    def test_actual80second_fixture_complete_timeline_real_last_and_receipt_binding(self):
        ffmpeg=os.environ['SCB_PRO_FFMPEG'];ffprobe=os.environ['SCB_PRO_FFPROBE']
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary);video=root/'fixture.mp4';receipt=root/'recording.json'
            subprocess.run([ffmpeg,'-hide_banner','-loglevel','error','-threads','2','-filter_threads','2','-f','lavfi','-i',
                'testsrc2=size=128x72:rate=10','-t','80.1','-an','-c:v','libx264','-threads','2','-preset','ultrafast','-pix_fmt','yuv420p',str(video)],
                check=True,capture_output=True,timeout=30)
            proof=flow_proof(80.1);proof.update(passed=True,sha256=digest(video));write_json(receipt,proof)
            with patch('batch_control.media_binding',return_value=None):result=generate(root,video,receipt,root/'evidence')
            report=read_json(result['timeline']);self.assertEqual(report['source_frame_count'],801)
            self.assertAlmostEqual(report['duration'],80.1,places=2);self.assertEqual(len(report['frames']),403)
            self.assertEqual(len(report['interaction_frames']),12);self.assertEqual(report['full_decode_passes'],1)
            self.assertEqual(validate(root,result['timeline'],video,receipt)['frames'],403)
            expected=root/'expected-last.jpg'
            core.command(['ffmpeg','-v','error','-i',str(video),'-vf','select=eq(n\\,800)','-frames:v','1','-fps_mode','vfr',
                '-threads','2','-pix_fmt','yuvj420p','-q:v','2',str(expected)],{'ffmpeg':ffmpeg,'ffprobe':ffprobe})
            actual=Image.open(root/'evidence/frames/last.jpg').convert('RGB');wanted=Image.open(expected).convert('RGB')
            self.assertIsNone(ImageChops.difference(actual,wanted).getbbox(),'Short-tail extraction must be the true original final frame')
            report['recording_policy_version']='legacy-fixed-v1';write_json(result['timeline'],report)
            with self.assertRaisesRegex(ValueError,'frozen run'):validate(root,result['timeline'],video,receipt)

if __name__=='__main__':unittest.main()
