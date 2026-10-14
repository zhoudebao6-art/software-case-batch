"""Gate fixtures, not an independent model invocation or live media validation."""
import copy
import hashlib
import json
import os
from pathlib import Path
import shutil
import sys
import tempfile
import unittest
from unittest.mock import patch
import zipfile
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
from common import digest, file_map, read_json, write_json
from contracts import delivery_layout, chart_snapshot, model_review
from proflow import (prepare, finalize, finalize_document_revision, finalize_package_revision,
                     scan_delivery, package_only_delta,revision_chain,finalized_snapshot,publish,inherited_execution)

W='http://schemas.openxmlformats.org/wordprocessingml/2006/main'
A='http://schemas.openxmlformats.org/drawingml/2006/main'
R='http://schemas.openxmlformats.org/officeDocument/2006/relationships'
def doc(body): return f'<w:document xmlns:w="{W}" xmlns:a="{A}" xmlns:r="{R}"><w:body>{body}<w:sectPr/></w:body></w:document>'
def p(text): return '<w:p><w:r><w:t>'+text+'</w:t></w:r></w:p>'

class ContractTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name)
        self.work=self.root/'work';self.work.mkdir();self.out=self.root/'out'
        self.source=self.work/'原公式技术说明（1）.docx'
        with zipfile.ZipFile(self.source,'w') as z:z.writestr('word/document.xml',doc(p('原实施例文本')))
        self.run=prepare(self.work,self.out,'设备运行控制',self.source)
        # This suite's two-chart/60-second fixtures represent frozen r9 runs.
        # New r10 construction behavior has separate behavioral coverage.
        self.run['chart_policy']='analytical-v1'
        self.run.pop('recording_policy_version',None)
        self.run.pop('data_policy_version',None)
        self.run.pop('construction_check_policy_version',None)
        write_json(self.work/'.product-v2/run.json',self.run)
        self.system=self.out/'模拟系统';(self.system/'数据').mkdir(parents=True)
        (self.system/'数据/记录.csv').write_text('编号,值\n1,3\n',encoding='utf-8-sig')
        (self.system/'演示视频.mp4').write_bytes(b'video-fixture')
        with zipfile.ZipFile(self.system/'项目源码.zip','w') as z:z.writestr('app.py','print(1)')
        self.figures=[]
        for n in (1,2):
            target=self.work/f'.product-v2/charts/chart{n}.png';target.parent.mkdir(parents=True,exist_ok=True)
            target.write_bytes(b'\x89PNG\r\n\x1a\n'+bytes([n]))
            self.figures.append({'figure_id':n,'png':target.relative_to(self.work).as_posix(),'sha256':digest(target),'caption':f'图{n} 运行变化','title_policy':'none','question':'本图验证运行边界','data_source':'原实施例文本与当前运行计算记录','chart_type':'trajectory','labels':['时间','运行量']})
        write_json(self.work/'.product-v2/chart-manifest.json',{'figures':self.figures})
        self.word=self.out/self.source.name;self.make_word()
        self.charts=chart_snapshot(self.work,self.word,self.run)
        self.files=file_map(self.out)
        self.sessions=self.root/'sessions';self.sessions.mkdir()
        self.parent_log=self.sessions/'parent.jsonl';self.review_log=self.sessions/'review.jsonl'
        self.dispatch={'schema_version':1,'stages':{}}
        events=[]
        for stage,effort in (('build','high'),('review','ultra')):
            identity='/root/'+stage
            args={'task_name':stage,'fork_turns':'none','model':'gpt-6.1-sol','reasoning_effort':effort}
            events.extend([{'type':'response_item','payload':{'type':'function_call','name':'spawn_agent','namespace':'collaboration','call_id':stage,'arguments':json.dumps(args)}},
                           {'type':'response_item','payload':{'type':'function_call_output','call_id':stage,'output':json.dumps({'task_name':identity})}}])
            self.dispatch['stages'][stage]={'session_log':str(self.parent_log),'call_id':stage,'agent_id':identity,'artifact_hashes':self.files,'chart_snapshot':self.charts}
        self.dispatch['stages']['review']['review_session_log']=str(self.review_log)
        self.events=events;self.save_dispatch()
        self.proof={'reviewer_agent_id':'/root/review','decision':'pass','chart_snapshot':self.charts,'chart_reviews':[]}
        for f in self.figures:
            review={'figure_id':f['figure_id'],'png_sha256':f['sha256'],'no_title_header':True,'no_title_header_evidence':'PNG与Word实际顶部没有标题','no_schematic':True,'no_schematic_evidence':'打开PNG及Word图题检查，无示意文字'}
            for key in ('meaning','data','legibility','layout','explanation'):review[key]={'passed':True,'evidence':'isolated contract fixture'}
            self.proof['chart_reviews'].append(review)
        self.proof_path=self.work/'.product-v2/review.json';self.save_proof()
    def tearDown(self): self.temp.cleanup()
    def make_word(self,body=None,alter_png=False):
        if body is None:
            body=p('原实施例文本')+p('请参考图1。工况与原因。')+p('请参考图2。适用条件与结果。')
            for f in self.figures:
                body+=f'<w:p><w:r><w:drawing><a:blip r:embed="rId{f["figure_id"]}"/></w:drawing></w:r></w:p>'+p(f['caption'])
        rels='<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'+''.join(f'<Relationship Id="rId{f["figure_id"]}" Target="media/chart{f["figure_id"]}.png"/>' for f in self.figures)+'</Relationships>'
        with zipfile.ZipFile(self.word,'w') as z:
            z.writestr('word/document.xml',doc(body));z.writestr('word/_rels/document.xml.rels',rels)
            for f in self.figures:z.writestr(f'word/media/chart{f["figure_id"]}.png',(self.work/f['png']).read_bytes()+(b'changed' if alter_png else b''))
    def save_dispatch(self):
        self.parent_log.write_text(json.dumps({'type':'session_meta','payload':{'id':'parent-fixture'}})+'\n'+''.join(json.dumps(e)+'\n' for e in self.events),encoding='utf8')
        write_json(self.work/'.product-v2/model-dispatch.json',self.dispatch)
    def save_proof(self,attest=True):
        write_json(self.proof_path,self.proof)
        events=[{'type':'session_meta','payload':{'source':{'subagent':{'thread_spawn':{'agent_path':'/root/review','parent_thread_id':'parent-fixture'}}}}},
                {'type':'turn_context','payload':{'model':'gpt-6-astra' if self.dispatch.get('review_mode')=='original-expedited' else 'gpt-6.1-sol','effort':'low' if self.dispatch.get('review_mode')=='original-expedited' else 'ultra'}}]
        if attest:events.append({'type':'response_item','payload':{'type':'message','role':'assistant','channel':'final','content':[{'type':'output_text','text':json.dumps({'reviewer_agent_id':'/root/review','review_evidence_sha256':digest(self.proof_path)})}]}})
        self.review_log.write_text(''.join(json.dumps(e)+'\n' for e in events),encoding='utf8')
    def verify_models(self):
        with patch('contracts.SESSION_ROOT',self.sessions):return model_review(self.work,self.proof,self.files,self.charts,self.proof_path)
    def test_exact_original_filename_and_no_extra_files(self):
        self.assertEqual(delivery_layout(self.out,self.run),self.word)
        (self.out/'使用说明.txt').write_text('extra')
        with self.assertRaises(ValueError):delivery_layout(self.out,self.run)
    def test_unexpected_empty_directory_rejected(self):
        (self.out/'图表').mkdir()
        with self.assertRaises(ValueError):delivery_layout(self.out,self.run)
    def test_wrong_word_name_rejected(self):
        self.word.rename(self.out/'修订文档.docx')
        with self.assertRaises(ValueError):delivery_layout(self.out,self.run)
    def test_exact_system_and_csv_set(self):
        (self.system/'说明.txt').write_text('extra')
        with self.assertRaises(ValueError):delivery_layout(self.out,self.run)
        (self.system/'说明.txt').unlink();(self.system/'数据/nested').mkdir()
        with self.assertRaises(ValueError):delivery_layout(self.out,self.run)
    def test_original_name_exception_is_narrow(self):
        self.assertTrue(scan_delivery(self.out,self.run['word_name'])['passed'])
        (self.system/'数据/公式.csv').write_text('编号\n1')
        self.assertFalse(scan_delivery(self.out,self.run['word_name'])['passed'])
    def test_source_snapshot_cannot_change(self):
        self.source.write_bytes(b'changed')
        with self.assertRaises(ValueError):chart_snapshot(self.work,self.word,self.run)
    def test_original_blocks_are_preserved(self):
        self.make_word(body=p('changed'))
        with self.assertRaises(ValueError):chart_snapshot(self.work,self.word,self.run)
    def test_embedded_png_mismatch_rejected(self):
        self.make_word(alter_png=True)
        with self.assertRaises(ValueError):chart_snapshot(self.work,self.word,self.run)
    def test_missing_caption_rejected(self):
        self.figures[0]['caption']='图1 不同图题'
        write_json(self.work/'.product-v2/chart-manifest.json',{'figures':self.figures})
        with self.assertRaises(ValueError):chart_snapshot(self.work,self.word,self.run)
    def test_png_title_policy_rejected(self):
        self.figures[0]['title_policy']='title'
        write_json(self.work/'.product-v2/chart-manifest.json',{'figures':self.figures})
        with self.assertRaises(ValueError):chart_snapshot(self.work,self.word,self.run)
    def test_no_header_actual_review_is_required(self):
        self.proof['chart_reviews'][0]['no_title_header']=False;self.save_proof()
        with self.assertRaises(ValueError):self.verify_models()
    def test_analytical_review_requires_every_current_chart(self):
        self.proof['chart_reviews'].pop();self.save_proof()
        with self.assertRaisesRegex(ValueError,'every current chart'):self.verify_models()
    def test_analytical_review_cannot_duplicate_or_use_stale_png(self):
        original=copy.deepcopy(self.proof['chart_reviews'])
        self.proof['chart_reviews'][1]=copy.deepcopy(original[0]);self.save_proof()
        with self.assertRaisesRegex(ValueError,'every current chart'):self.verify_models()
        self.proof['chart_reviews']=original
        self.proof['chart_reviews'][0]['png_sha256']='stale';self.save_proof()
        with self.assertRaisesRegex(ValueError,'Actual PNG'):self.verify_models()
    def test_analytical_no_schematic_requires_visual_evidence(self):
        review=self.proof['chart_reviews'][0]
        for key,value in [('no_schematic',False),('no_schematic_evidence','   '),('no_schematic_evidence',True)]:
            with self.subTest(key=key,value=value):
                old=review[key];review[key]=value;self.save_proof()
                with self.assertRaisesRegex(ValueError,'no-示意'):self.verify_models()
                review[key]=old
    def test_analytical_five_quality_checks_require_nonempty_text(self):
        for key in ('meaning','data','legibility','layout','explanation'):
            for value in ('   ',True,['declared']):
                with self.subTest(key=key,value=value):
                    item=self.proof['chart_reviews'][0][key];old=item['evidence'];item['evidence']=value;self.save_proof()
                    with self.assertRaisesRegex(ValueError,'actual quality evidence'):self.verify_models()
                    item['evidence']=old
    def test_analytical_no_header_evidence_requires_nonempty_text(self):
        self.proof['chart_reviews'][0]['no_title_header_evidence']='   ';self.save_proof()
        with self.assertRaisesRegex(ValueError,'no-title-header evidence'):self.verify_models()
    def test_analytical_review_snapshot_must_include_policy(self):
        charts=copy.deepcopy(self.charts);charts.pop('chart_policy')
        with patch('contracts.SESSION_ROOT',self.sessions),self.assertRaisesRegex(ValueError,'frozen analytical policy'):
            model_review(self.work,self.proof,self.files,charts,self.proof_path)
    def test_unknown_frozen_review_policy_fails_closed(self):
        self.run['chart_policy']='future';write_json(self.work/'.product-v2/run.json',self.run)
        with self.assertRaisesRegex(ValueError,'Unknown chart policy'):self.verify_models()
    def test_legacy_review_does_not_gain_new_required_fields(self):
        self.run.pop('chart_policy');write_json(self.work/'.product-v2/run.json',self.run)
        self.charts=chart_snapshot(self.work,self.word,self.run)
        self.proof['chart_snapshot']=self.charts
        for record in self.dispatch['stages'].values():record['chart_snapshot']=self.charts
        for review in self.proof['chart_reviews']:
            review.pop('no_schematic');review.pop('no_schematic_evidence')
        self.save_dispatch();self.save_proof();self.assertIn('review',self.verify_models())
    def test_distinct_real_dispatch_records_pass_gate_fixture(self):
        self.assertEqual(self.verify_models()['review']['agent_id'],'/root/review')
    def test_missing_model_record_rejected(self):
        (self.work/'.product-v2/model-dispatch.json').unlink()
        with self.assertRaises(ValueError):self.verify_models()
    def test_missing_independent_review_rejected(self):
        del self.dispatch['stages']['review'];self.save_dispatch()
        with self.assertRaises(ValueError):self.verify_models()
    def test_same_dispatch_id_rejected(self):
        self.dispatch['stages']['review']['call_id']='build';self.save_dispatch()
        with self.assertRaises(ValueError):self.verify_models()
    def test_same_agent_id_rejected(self):
        self.events[3]['payload']['output']=json.dumps({'task_name':'/root/build'})
        self.dispatch['stages']['review']['agent_id']='/root/build';self.save_dispatch()
        with self.assertRaises(ValueError):self.verify_models()
    def test_wrong_effort_in_actual_dispatch_rejected(self):
        args=json.loads(self.events[2]['payload']['arguments']);args['reasoning_effort']='high'
        self.events[2]['payload']['arguments']=json.dumps(args);self.save_dispatch()
        with self.assertRaises(ValueError):self.verify_models()
    def add_repair(self,effort='ultra',agent='/root/repair'):
        args={'task_name':'repair','fork_turns':'none','model':'gpt-6.1-sol','reasoning_effort':effort}
        self.events[2:2]=[{'type':'response_item','payload':{'type':'function_call','name':'spawn_agent','call_id':'repair','arguments':json.dumps(args)}},
                         {'type':'response_item','payload':{'type':'function_call_output','call_id':'repair','output':json.dumps({'task_name':agent})}}]
        self.dispatch['stages']['repair-1']={'session_log':str(self.parent_log),'call_id':'repair','agent_id':agent,'artifact_hashes':self.files,'chart_snapshot':self.charts}
        self.save_dispatch()
    def test_ultra_repair_retains_high_original_completion_snapshot(self):
        self.add_repair();self.dispatch['stages']['build']['artifact_hashes']={'earlier.zip':'old-snapshot'};self.save_dispatch()
        self.assertIn('repair-1',self.verify_models())
    def test_high_repair_is_rejected_even_if_build_high_review_ultra(self):
        self.add_repair('high')
        with self.assertRaisesRegex(ValueError,'repair-1 dispatch'):self.verify_models()
    def test_reviewer_cannot_implement_repair(self):
        self.add_repair(agent='/root/review')
        with self.assertRaisesRegex(ValueError,'Distinct actual'):self.verify_models()
    def test_repair_cannot_hide_original_dispatch_or_skip_sequence(self):
        self.add_repair();self.dispatch['stages']['repair-2']=self.dispatch['stages'].pop('repair-1');self.save_dispatch()
        with self.assertRaisesRegex(ValueError,'contiguous'):self.verify_models()
    def expedited_fixture(self,statement=None):
        statement=statement or self.run['title']+' 使用原加急模式'
        self.events.insert(0,{'type':'response_item','payload':{'type':'message','role':'user','content':[{'type':'input_text','text':statement}]}})
        call=next(e for e in self.events if e['payload'].get('call_id')=='review' and e['payload']['type']=='function_call')
        args=json.loads(call['payload']['arguments']);args.update(model='gpt-6-astra',reasoning_effort='low');call['payload']['arguments']=json.dumps(args)
        self.dispatch['review_mode']='original-expedited';self.dispatch['expedited_authorization']={'run_id':self.run['run_id'],'workspace':str(self.work),'session_log':str(self.parent_log),'user_message_sha256':hashlib.sha256(statement.encode()).hexdigest(),'statement':statement,'scope_name':self.run['title']}
        self.save_dispatch();self.save_proof()
    def test_explicit_scoped_original_expedited_route_accepts_actual_astra_low_fixture(self):
        self.expedited_fixture();self.assertIn('expedited_authorization',self.verify_models())
    def test_speed_or_negative_statement_cannot_change_normal_ultra_model(self):
        for statement in (self.run['title']+' 请提速',self.run['title']+' 不要使用原加急模式',self.run['title']+' 不要再启用原加急模式',self.run['title']+' 不建议使用原加急模式','如果 '+self.run['title']+' 使用原加急模式'):
            with self.subTest(statement=statement):
                self.expedited_fixture(statement)
                with self.assertRaisesRegex(ValueError,'positive'):self.verify_models()
    def test_expedited_authorization_cannot_spill_to_another_run(self):
        self.expedited_fixture();self.dispatch['expedited_authorization']['run_id']='another-run';self.save_dispatch()
        with self.assertRaisesRegex(ValueError,'restricted'):self.verify_models()
    def test_inherited_model_rejected(self):
        args=json.loads(self.events[0]['payload']['arguments']);args.pop('model');args['fork_turns']='all'
        self.events[0]['payload']['arguments']=json.dumps(args);self.save_dispatch()
        with self.assertRaises(ValueError):self.verify_models()
    def test_workspace_handwritten_transcript_rejected(self):
        self.dispatch['stages']['build']['session_log']=str(self.work/'model.jsonl')
        shutil.copyfile(self.parent_log,self.work/'model.jsonl');self.save_dispatch()
        with self.assertRaises(ValueError):self.verify_models()
    def test_stale_artifact_binding_rejected(self):
        self.dispatch['stages']['review']['artifact_hashes']={};self.save_dispatch()
        with self.assertRaises(ValueError):self.verify_models()
    def test_builder_self_signed_pass_without_reviewer_final_rejected(self):
        self.save_proof(attest=False)
        with self.assertRaises(ValueError):self.verify_models()
    def test_review_proof_changed_after_attestation_rejected(self):
        self.proof['limitations']='changed';write_json(self.proof_path,self.proof)
        with self.assertRaises(ValueError):self.verify_models()
    def test_only_latest_actual_reviewer_final_can_attest(self):
        with self.review_log.open('a',encoding='utf8') as stream:
            stream.write(json.dumps({'type':'response_item','payload':{'type':'message','role':'assistant','channel':'final','content':[{'type':'output_text','text':'revise, no current pass'}]}})+'\n')
        with self.assertRaisesRegex(ValueError,'final must attest'):self.verify_models()
    def test_final_memory_citation_accepted_but_prose_is_not(self):
        events=[json.loads(line) for line in self.review_log.read_text(encoding='utf8').splitlines()]
        text=events[-1]['payload']['content'][0]['text']
        events[-1]['payload']['content'][0]['text']=text+'\n<oai-mem-citation>\n<citation_entries>MEMORY.md:1-2|note=[fixture]</citation_entries>\n<rollout_ids></rollout_ids>\n</oai-mem-citation>'
        self.review_log.write_text(''.join(json.dumps(e)+'\n' for e in events),encoding='utf8');self.verify_models()
        events[-1]['payload']['content'][0]['text']='untrusted prose '+text
        self.review_log.write_text(''.join(json.dumps(e)+'\n' for e in events),encoding='utf8')
        with self.assertRaises(ValueError):self.verify_models()
    def test_actual_desktop_final_answer_phase_attestation_with_citation(self):
        events=[json.loads(line) for line in self.review_log.read_text(encoding='utf8').splitlines()]
        payload=events[-1]['payload'];payload.pop('channel');payload['phase']='final_answer'
        payload['id']='desktop-final-fixture';payload['internal_metadata']={'fixture':True}
        payload['content'][0]['text']+='\n<oai-mem-citation>\n<citation_entries>MEMORY.md:1-2|note=[fixture]</citation_entries>\n<rollout_ids></rollout_ids>\n</oai-mem-citation>'
        self.review_log.write_text(''.join(json.dumps(e)+'\n' for e in events),encoding='utf8')
        self.assertEqual(self.verify_models()['review']['agent_id'],'/root/review')
    def test_nonfinal_phase_cannot_attest_even_with_legacy_final_channel(self):
        events=[json.loads(line) for line in self.review_log.read_text(encoding='utf8').splitlines()]
        payload=events[-1]['payload'];payload['phase']='commentary'
        for legacy_channel in (None,'final'):
            with self.subTest(channel=legacy_channel):
                if legacy_channel is None:payload.pop('channel',None)
                else:payload['channel']=legacy_channel
                self.review_log.write_text(''.join(json.dumps(e)+'\n' for e in events),encoding='utf8')
                with self.assertRaises(ValueError):self.verify_models()
    def test_legacy_run_and_receipt_are_not_rewritten(self):
        run_path=self.work/'.product-v2/run.json';legacy={'schema_version':1,'output':str(self.out),'title':'设备运行控制'}
        write_json(run_path,legacy);before=digest(run_path)
        with self.assertRaises(ValueError):prepare(self.work,self.out,'设备运行控制',self.source)
        self.assertEqual(digest(run_path),before)
        receipt=self.work/'.product-v2/final-receipt.json';write_json(receipt,{'status':'complete','old':True});old=digest(receipt)
        with self.assertRaises(ValueError):finalize(self.work,self.out,self.proof_path)
        self.assertEqual(digest(receipt),old)
    def runtime_records(self,work,out):
        app=work/'app.py';app.write_text('print(1)',encoding='utf8')
        src=work/'input.csv';src.write_text('编号,值\n1,3\n',encoding='utf-8-sig')
        write_json(work/'.product-v2/source-package.json',{'sha256':digest(out/'模拟系统/项目源码.zip'),'files':{'app.py':digest(app)}})
        write_json(work/'.product-v2/recording.json',{'passed':True,'sha256':digest(out/'模拟系统/演示视频.mp4'),'duration':60,'input_files':{'app.py':digest(app)},'events':[{'action':'click','started':1,'completed':2}]})
        write_json(work/'.product-v2/data-cleaning.json',{'files':[{'name':'记录.csv','sha256':digest(out/'模拟系统/数据/记录.csv'),'input':str(src),'input_sha256':digest(src)}]})
        write_json(work/'.product-v2/data-provenance.json',{'nature':'contract fixture','sources':['fixture'],'validation':['fixture']})
        checks=[]
        for kind in ('algorithm','api','persistence','browser','build','package_startup'):
            log=work/f'.product-v2/{kind}.log';log.write_text('fixture successful execution',encoding='utf8')
            checks.append({'kind':kind,'exit_code':0,'command':'fixture-command','log':log.relative_to(work).as_posix(),'sha256':digest(log)})
        return checks
    def test_finalize_integrates_all_new_and_existing_checks(self):
        self.proof.update({'checks':self.runtime_records(self.work,self.out),'reviewed_files':self.files,
            'visual_notes':['fixture'],'limitations':['fixture, not live validation'],'source_zip_sha256':digest(self.system/'项目源码.zip')})
        self.make_media_fixture(self.work,self.out)
        self.proof['video_timeline_sha256']=read_json(self.work/'.product-v2/controlled-video.json')['sha256'];self.save_proof()
        with patch('proflow.cleanup_ready'),patch('contracts.SESSION_ROOT',self.sessions):
            result=finalize(self.work,self.out,self.proof_path)
        self.assertEqual(result['status'],'complete');self.assertEqual(len(result['checks']),6)
    def make_media_fixture(self,work,out):
        """Contract fixture only: no real frames, decoding or visual claim."""
        directory=work/'.product-v2/video-timeline';directory.mkdir(parents=True,exist_ok=True)
        frames=[]
        for i in range(300):
            path=directory/f'frame-{i:03}.jpg';path.write_bytes(str(i).encode())
            frames.append({'file':str(path),'seconds':i/5,'sha256':digest(path),'type':'uniform_sample'})
        for name,seconds in [('first',0),('last',59.96)]:
            path=directory/f'{name}.jpg';path.write_bytes(name.encode());frames.append({'file':str(path),'seconds':seconds,'source_frame_index':0 if name=='first' else 1499,'sha256':digest(path),'type':name})
        frames.sort(key=lambda f:f['seconds'])
        sheet=directory/'contact.jpg';sheet.write_bytes(b'fixture')
        interactions=[]
        for kind,target in [('before',.8),('after',2.2)]:
            path=directory/f'event-{kind}.jpg';path.write_bytes(kind.encode());interactions.append({'file':str(path),'seconds':target,'target_seconds':target,'sha256':digest(path),'type':'interaction_'+kind,'event_index':0,'action':'click'})
        recording=work/'.product-v2/recording.json'
        timeline=directory/'timeline.json';write_json(timeline,{'video_sha256':digest(out/'模拟系统/演示视频.mp4'),'sample_fps':5,'decode_ok':True,'duration_in_requested_range':True,'duration':60,'fps':25,'source_frame_count':1500,
            'frames':frames,'contact_sheets':[{'file':str(sheet),'sha256':digest(sheet),'frame_files':[f['file'] for f in frames]}],
            'interaction_frames':interactions,'recording_receipt':{'path':str(recording),'sha256':digest(recording)}})
        write_json(work/'.product-v2/controlled-video.json',{'timeline':str(timeline),'sha256':digest(timeline)})
        return timeline
    def revision_fixture(self):
        base_work=self.root/'base';base_work.mkdir();base_out=self.root/'base-output'
        shutil.copytree(self.out,base_out)
        write_json(base_work/'.product-v2/run.json',{'schema_version':1,'workspace':str(base_work),'output':str(base_out),'title':'历史'})
        checks=self.runtime_records(base_work,base_out)
        old_proof=base_work/'.product-v2/old-review.json';write_json(old_proof,{'checks':checks,'source_zip_sha256':digest(base_out/'模拟系统/项目源码.zip')})
        old_receipt=base_work/'.product-v2/final-receipt.json';write_json(old_receipt,{'status':'complete','files':file_map(base_out),'execution_evidence':str(old_proof),'evidence_sha256':digest(old_proof)})
        self.run['revision_of']={'workspace':str(base_work),'output':str(base_out),'receipt_sha256':digest(old_receipt),'system_files':file_map(base_out/'模拟系统')}
        write_json(self.work/'.product-v2/run.json',self.run)
        self.proof.update({'reviewed_files':self.files,'visual_notes':['fixture'],'limitations':['inherited software; fixture']});self.save_proof()
        return base_work,base_out,old_receipt
    def test_document_revision_reuses_unchanged_runtime_and_keeps_old_receipt(self):
        base_work,base_out,old_receipt=self.revision_fixture();old=digest(old_receipt)
        with patch('proflow.cleanup_ready'),patch('contracts.SESSION_ROOT',self.sessions):
            result=finalize_document_revision(self.work,self.out,self.proof_path)
        self.assertEqual(result['scope'],'document-revision');self.assertEqual(len(result['inherited_checks']),6)
        self.assertEqual(digest(old_receipt),old)
    def test_document_revision_changed_system_requires_normal_flow(self):
        self.revision_fixture();(self.system/'演示视频.mp4').write_bytes(b'changed')
        with patch('proflow.cleanup_ready'),self.assertRaises(ValueError):finalize_document_revision(self.work,self.out,self.proof_path)
    def test_document_revision_stale_prior_log_rejected(self):
        base_work,_,_=self.revision_fixture();(base_work/'.product-v2/api.log').write_text('changed')
        with patch('proflow.cleanup_ready'),self.assertRaises(ValueError):finalize_document_revision(self.work,self.out,self.proof_path)
    def rebind_fixture_evidence_path(self,old_receipt,path):
        receipt=read_json(old_receipt);receipt['execution_evidence']=str(path);write_json(old_receipt,receipt)
        self.run['revision_of']['receipt_sha256']=digest(old_receipt);write_json(self.work/'.product-v2/run.json',self.run)
    def test_document_revision_resolves_legacy_relative_evidence_from_different_cwd(self):
        base_work,_,old_receipt=self.revision_fixture()
        self.rebind_fixture_evidence_path(old_receipt,'.product-v2\\old-review.json');before=digest(old_receipt)
        previous_cwd=Path.cwd()
        try:
            os.chdir(self.root)
            self.assertNotEqual(Path.cwd(),base_work)
            with patch('proflow.cleanup_ready'),patch('contracts.SESSION_ROOT',self.sessions):
                result=finalize_document_revision(self.work,self.out,self.proof_path)
        finally:os.chdir(previous_cwd)
        self.assertEqual(result['scope'],'document-revision');self.assertEqual(digest(old_receipt),before)
    def test_document_revision_rejects_relative_or_absolute_evidence_outside_base(self):
        base_work,_,old_receipt=self.revision_fixture();outside=self.root/'outside-review.json'
        shutil.copyfile(base_work/'.product-v2/old-review.json',outside)
        for path in ('../outside-review.json',str(outside)):
            with self.subTest(path=path):
                self.rebind_fixture_evidence_path(old_receipt,path);before=digest(old_receipt)
                with patch('proflow.cleanup_ready'),self.assertRaisesRegex(ValueError,'Unsafe relative path|inside its original workspace'):
                    finalize_document_revision(self.work,self.out,self.proof_path)
                self.assertEqual(digest(old_receipt),before)
    def test_adopt_draft_is_explicit_and_requires_finalized_system(self):
        base_work,_,_=self.revision_fixture()
        new_work=self.root/'new-work';new_work.mkdir()
        with self.assertRaises(ValueError):prepare(new_work,self.out,'设备运行控制',self.source,base_work)
        result=prepare(new_work,self.out,'设备运行控制',self.source,base_work,True)
        self.assertEqual(result['adopted_draft_files'],self.files)
    def test_revision_prompt_limits_actions_and_uses_revision_gate(self):
        base_work,_,_=self.revision_fixture();new_work=self.root/'revision-prompt';new_work.mkdir()
        prepare(new_work,self.out,'设备运行控制',self.source,base_work,True)
        prompt=(new_work/'.product-v2/深化命令词.txt').read_text(encoding='utf8')
        self.assertIn('scope=document-revision',prompt)
        self.assertIn('本次仅建设和自检Word',prompt)
        self.assertIn('旧软件的建设模型及执行身份保留历史事实',prompt)
        self.assertIn('六类执行日志',prompt)
        self.assertIn('finalize-document-revision --workspace',prompt)
        self.assertIn(str(new_work),prompt);self.assertIn(self.source.name,prompt)
        self.assertNotIn('在原工作区对后端算法做尽可能深入的完善',prompt)
        self.assertNotIn('实际检索同类型开源项目及原始数据',prompt)
        self.assertNotIn('再实际操作最终网页录制约一分钟',prompt)
        self.assertNotIn('再执行finalize；',prompt)
    def test_new_and_document_revision_freeze_analytical_policy(self):
        self.assertEqual(self.run['chart_policy'],'analytical-v1')
        base,_,_=self.revision_fixture();new=self.root/'policy-document';new.mkdir()
        result=prepare(new,self.root/'policy-document-output','设备运行控制',self.source,base)
        self.assertEqual(result['chart_policy'],'analytical-v2')
        prompt=(new/'.product-v2/深化命令词.txt').read_text(encoding='utf8')
        for text in ('chart_policy=analytical-v2','总数无上限','不因数量造数据','no_schematic_evidence'):
            self.assertIn(text,prompt)
    def test_package_revision_inherits_parent_chart_policy_exactly(self):
        base,_,_=self.revision_fixture();path=base/'.product-v2/run.json';original=read_json(path)
        for suffix,policy in [('legacy',None),('analytical','analytical-v1')]:
            prior=dict(original)
            if policy:prior['chart_policy']=policy
            write_json(path,prior);new=self.root/('package-policy-'+suffix);new.mkdir()
            result=prepare(new,self.root/('package-output-'+suffix),'设备运行控制',self.source,base,revision_scope='package')
            self.assertEqual(result.get('chart_policy'),policy)
            if policy is None:self.assertNotIn('chart_policy',result)
    def test_package_policy_preserves_parent_chart_snapshot_shape_and_hashes(self):
        base,base_out,_=self.revision_fixture()
        shutil.copytree(self.work/'.product-v2/charts',base/'.product-v2/charts')
        shutil.copyfile(self.work/'.product-v2/chart-manifest.json',base/'.product-v2/chart-manifest.json')
        for suffix,policy in [('legacy',None),('analytical','analytical-v1')]:
            prior={'schema_version':2,'workspace':str(base),'output':str(base_out),'title':'父案',
                   'source_docx':str(self.source),'source_docx_sha256':digest(self.source),'word_name':self.source.name,
                   'chart_numbering_policy':'source-sequential-v1'}
            if policy:prior['chart_policy']=policy
            write_json(base/'.product-v2/run.json',prior)
            old=chart_snapshot(base,base_out/self.source.name,prior)
            new=self.root/('snapshot-package-'+suffix);new.mkdir();out=self.root/('snapshot-output-'+suffix)
            result=prepare(new,out,'设备运行控制',self.source,base,revision_scope='package')
            shutil.copytree(self.work/'.product-v2/charts',new/'.product-v2/charts')
            shutil.copyfile(self.work/'.product-v2/chart-manifest.json',new/'.product-v2/chart-manifest.json')
            shutil.copyfile(base_out/self.source.name,out/self.source.name)
            self.assertEqual(chart_snapshot(new,out/self.source.name,result),old)
    def test_prepare_preserves_existing_unmarked_run_and_prompt(self):
        self.run.pop('chart_policy');path=self.work/'.product-v2/run.json';write_json(path,self.run)
        prompt=self.work/'.product-v2/深化命令词.txt';before=(digest(path),digest(prompt))
        result=prepare(self.work,self.out,'设备运行控制',self.source)
        self.assertNotIn('chart_policy',result);self.assertEqual((digest(path),digest(prompt)),before)
    def test_unknown_parent_policy_is_not_silently_adopted(self):
        base,_,_=self.revision_fixture();path=base/'.product-v2/run.json';prior=read_json(path)
        prior['chart_policy']='unknown';write_json(path,prior);new=self.root/'unknown-parent';new.mkdir()
        with self.assertRaisesRegex(ValueError,'Unknown chart policy'):
            prepare(new,self.root/'unknown-output','设备运行控制',self.source,base,revision_scope='package')
    def test_new_prompt_has_new_chart_rules_and_internal_only_instructions(self):
        prompt=(self.work/'.product-v2/深化命令词.txt').read_text(encoding='utf8')
        for text in ('chart_policy=analytical-v2','通常4—6张','总数无上限','1—2张黑白结果图','no_schematic_evidence','留内部工作区，排除源码ZIP'):
            self.assertIn(text,prompt)
        for text in ('生成2–6张','使用运行说明放源码ZIP已有运行说明.txt'):
            self.assertNotIn(text,prompt)
    def test_new_case_prompt_keeps_full_construction_contract(self):
        prompt=(self.work/'.product-v2/深化命令词.txt').read_text(encoding='utf8')
        self.assertIn('在原工作区对后端算法做尽可能深入的完善',prompt)
        self.assertIn('再实际操作最终网页录制一分多钟',prompt)
        self.assertIn('再执行finalize；',prompt)
        self.assertNotIn('scope=document-revision',prompt)
    def test_package_revision_document_gate_cannot_be_reused(self):
        self.revision_fixture();self.run['revision_scope']='package';write_json(self.work/'.product-v2/run.json',self.run)
        with self.assertRaisesRegex(ValueError,'dedicated'):finalize_document_revision(self.work,self.out,self.proof_path)
    def test_untracked_base_allowance_is_explicit_and_package_only(self):
        base_work,base_out,_=self.revision_fixture();extra=base_out/'$owner.tmp';extra.write_text('user file')
        new=self.root/'untracked-new';new.mkdir()
        with self.assertRaises(ValueError):prepare(new,self.root/'new-output','设备运行控制',self.source,base_work,revision_scope='package')
        with self.assertRaisesRegex(ValueError,'limited'):prepare(new,self.root/'new-output','设备运行控制',self.source,base_work,allow_untracked_base=True)
        run=prepare(new,self.root/'new-output','设备运行控制',self.source,base_work,revision_scope='package',allow_untracked_base=True)
        self.assertEqual(run['revision_of']['untracked_base_files'],{'$owner.tmp':digest(extra)})
        self.assertTrue(extra.exists());self.assertNotIn('$owner.tmp',run['revision_of']['system_files'])
    def test_untracked_allowance_never_hides_changed_registered_artifact(self):
        base_work,base_out,_=self.revision_fixture();(base_out/'模拟系统/演示视频.mp4').write_bytes(b'changed');(base_out/'user.tmp').write_text('user')
        new=self.root/'changed-new';new.mkdir()
        with self.assertRaises(ValueError):prepare(new,self.root/'changed-out','设备运行控制',self.source,base_work,revision_scope='package',allow_untracked_base=True)
    def test_package_delta_cannot_change_business_code(self):
        old=self.root/'old.zip';new=self.root/'new.zip'
        with zipfile.ZipFile(old,'w') as z:z.writestr('app.py','print(1)');z.writestr('运行说明.txt','old docs')
        with zipfile.ZipFile(new,'w') as z:z.writestr('app.py','print(2)')
        with self.assertRaisesRegex(ValueError,'application bytes'):package_only_delta(old,new)
        with zipfile.ZipFile(new,'w') as z:z.writestr('app.py','print(1)')
        self.assertEqual(package_only_delta(old,new)['removed_documents'][0]['path'],'运行说明.txt')
    def test_package_delta_preserves_required_attribution(self):
        old=self.root/'legal-old.zip';new=self.root/'legal-new.zip'
        header='Title\nAuthors: A\nLicense: CC BY 4.0\nhttps://creativecommons.org/licenses/by/4.0/'
        with zipfile.ZipFile(old,'w') as z:z.writestr('LICENSES/DATA-NOTICE.txt',header+'\n\nold production note')
        with zipfile.ZipFile(new,'w') as z:z.writestr('LICENSES/DATA-NOTICE.txt',header+'\n\nChanges: Material has been modified.')
        self.assertEqual(len(package_only_delta(old,new)['amended_legal_notices']),1)
        with zipfile.ZipFile(new,'w') as z:z.writestr('LICENSES/DATA-NOTICE.txt','Changes: Material modified.')
        with self.assertRaisesRegex(ValueError,'complete original attribution'):package_only_delta(old,new)
    def test_media_requires_all_actual_operations_and_complete_unique_timeline(self):
        from media_evidence import validate
        self.runtime_records(self.work,self.out);timeline=self.make_media_fixture(self.work,self.out);video=self.out/'模拟系统/演示视频.mp4'
        self.assertEqual(validate(self.work,timeline,video)['frames'],302)
        original=read_json(timeline)
        for mutation in ('missing-last-with-extra','missing-uniform-tail','wrong-first-index','wrong-last-index','wrong-last-time','duplicate-uniform','missing-event-pair','wrong-event-time','stale-receipt'):
            with self.subTest(mutation=mutation):
                value=copy.deepcopy(original)
                if mutation=='missing-last-with-extra':
                    value['frames']=[f for f in value['frames'] if f['type']!='last'];value['frames'].append(dict(value['frames'][0],type='extra'))
                if mutation=='duplicate-uniform':value['frames'][3]=dict(value['frames'][2])
                if mutation=='missing-uniform-tail':value['frames']=[f for f in value['frames'] if f['type']!='uniform_sample' or f['seconds']!=59.8]
                if mutation=='wrong-first-index':next(f for f in value['frames'] if f['type']=='first')['source_frame_index']=1
                if mutation=='wrong-last-index':next(f for f in value['frames'] if f['type']=='last')['source_frame_index']=1498
                if mutation=='wrong-last-time':next(f for f in value['frames'] if f['type']=='last')['seconds']=59.8
                if mutation=='missing-event-pair':value['interaction_frames']=value['interaction_frames'][:1]
                if mutation=='wrong-event-time':value['interaction_frames'][0]['target_seconds']=10
                if mutation=='stale-receipt':value['recording_receipt']['sha256']='0'*64
                write_json(timeline,value)
                with self.assertRaises(ValueError):validate(self.work,timeline,video)
        write_json(timeline,original)
    def candidate_fixture(self):
        checks=self.runtime_records(self.work,self.out);self.make_media_fixture(self.work,self.out)
        self.proof.update({'checks':checks,'reviewed_files':self.files,'visual_notes':['fixture'],'limitations':['fixture only'],'source_zip_sha256':digest(self.system/'项目源码.zip'),
                          'video_timeline_sha256':read_json(self.work/'.product-v2/controlled-video.json')['sha256']});self.save_proof()
        with patch('proflow.cleanup_ready'),patch('contracts.SESSION_ROOT',self.sessions):finalize(self.work,self.out,self.proof_path)
    def test_atomic_publication_freezes_intent_then_moves_whole_directory_and_retains_proof(self):
        self.candidate_fixture();receipt=self.work/'.product-v2/final-receipt.json';prior=digest(receipt);review=digest(self.proof_path)
        new=self.root/'formal-output';new_work=self.root/'following-revision';new_work.mkdir()
        with self.assertRaises((ValueError,OSError)):prepare(new_work,self.root/'another-output','设备运行控制',self.source,self.work)
        with patch('proflow.cleanup_ready'):result=publish(self.work,new)
        self.assertEqual(result['status'],'published');self.assertFalse(self.out.exists());self.assertEqual(file_map(new),self.files)
        self.assertEqual(digest(receipt),prior);self.assertEqual(digest(self.proof_path),review)
        self.assertEqual(read_json(self.work/'.product-v2/run.json')['output'],str(new))
        with patch('proflow.cleanup_ready'):self.assertEqual(publish(self.work,new)['status'],'published')
        self.assertEqual(prepare(new_work,self.root/'another-output','设备运行控制',self.source,self.work)['revision_of']['output'],str(new))
    def test_publication_never_overwrites_existing_destination(self):
        self.candidate_fixture();new=self.root/'occupied';new.mkdir();(new/'user.txt').write_text('keep')
        with patch('proflow.cleanup_ready'),self.assertRaisesRegex(ValueError,'new destination'):publish(self.work,new)
        self.assertTrue(self.out.exists());self.assertEqual((new/'user.txt').read_text(),'keep')
    def test_publication_recovers_after_atomic_rename_before_run_path_update(self):
        self.candidate_fixture();new=self.root/'recover-publication'
        real_write=write_json
        def crash_write(path,value):
            if str(path).endswith('run.json'):raise OSError('fixture interruption after rename')
            return real_write(path,value)
        with patch('proflow.cleanup_ready'),patch('proflow.write_json',side_effect=crash_write),self.assertRaises(OSError):publish(self.work,new)
        self.assertFalse(self.out.exists());self.assertTrue(new.exists());self.assertTrue((self.work/'.product-v2/publish-intent.json').exists())
        with patch('proflow.cleanup_ready'):self.assertEqual(publish(self.work,new)['status'],'published')
    def test_publication_recovery_rejects_run_identity_drift(self):
        self.candidate_fixture();new=self.root/'publication-identity-drift';real_write=write_json
        def crash_write(path,value):
            if str(path).endswith('run.json'):raise OSError('fixture interruption')
            return real_write(path,value)
        with patch('proflow.cleanup_ready'),patch('proflow.write_json',side_effect=crash_write),self.assertRaises(OSError):publish(self.work,new)
        run=read_json(self.work/'.product-v2/run.json');run['run_id']='changed-id';write_json(self.work/'.product-v2/run.json',run)
        with patch('proflow.cleanup_ready'),self.assertRaisesRegex(ValueError,'run changed'):publish(self.work,new)
    def test_revision_chain_resolves_recent_document_revision_to_actual_root_checks(self):
        root,_,_=self.revision_fixture()
        with patch('proflow.cleanup_ready'),patch('contracts.SESSION_ROOT',self.sessions):finalize_document_revision(self.work,self.out,self.proof_path)
        formal=self.root/'document-final'
        with patch('proflow.cleanup_ready'):publish(self.work,formal)
        new=self.root/'package-child';new.mkdir();newout=self.root/'package-child-output'
        run=prepare(new,newout,'设备运行控制',self.source,self.work,revision_scope='package')
        chain=revision_chain(new,run['revision_of']);self.assertEqual([e['workspace'] for e in chain],[self.work,root]);self.assertEqual(len(inherited_execution(chain[-1])),6)
        (root/'.product-v2/api.log').write_text('changed')
        with self.assertRaisesRegex(ValueError,'changed'):inherited_execution(chain[-1])

if __name__=='__main__':unittest.main()
