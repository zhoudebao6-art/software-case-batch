"""Synthetic gate/publication behavior only; no production case or model call."""
import copy
import hashlib
import json
import os
from pathlib import Path
import unittest
from unittest.mock import patch
import zipfile

import test_contracts as fixtures
import batch_control
from common import digest,file_map,read_json,write_json
import simplified_closure as closure
import proflow


class SimplifiedClosureTests(unittest.TestCase):
    def setUp(self):
        self.f=fixtures.ContractTests();self.f.setUp();self.addCleanup(self.f.tearDown)
        f=self.f
        initial=f.runtime_records(f.work,f.out);f.make_media_fixture(f.work,f.out)
        for check in initial:check['artifact_hashes']={'模拟系统/数据/记录.csv':f.files['模拟系统/数据/记录.csv']}
        initial[-1]['artifact_hashes']={'模拟系统/项目源码.zip':f.files['模拟系统/项目源码.zip']}
        f.proof.update(run_id=f.run['run_id'],decision='revise',checks=initial,reviewed_files=f.files,
                       visual_notes=['Actually opened both fixture charts and document'],limitations=['Synthetic fixtures'],
                       video_timeline_sha256=read_json(f.work/'.product-v2/controlled-video.json')['sha256'],
                       source_zip_sha256=digest(f.system/'项目源码.zip'),
                       source_package=read_json(f.work/'.product-v2/source-package.json'),
                       issues=[{'id':'search-clear','severity':'minor','required_checks':['browser','package_startup']}])
        f.save_proof()
        self.first_bytes=f.proof_path.read_bytes()
        first_dispatch=f.work/'.product-v2/first-dispatch.json';write_json(first_dispatch,f.dispatch)
        (f.work/'app.py').write_text('print(2)',encoding='utf8')
        with zipfile.ZipFile(f.system/'项目源码.zip','w') as z:z.writestr('app.py','print(2)')
        write_json(f.work/'.product-v2/source-package.json',{'sha256':digest(f.system/'项目源码.zip'),'files':{'app.py':digest(f.work/'app.py')}})
        self.current=file_map(f.out);checks=copy.deepcopy(initial)
        for kind in ('browser','package_startup'):
            item=next(c for c in checks if c['kind']==kind)
            log=f.work/f'.product-v2/repair-{kind}.log';log.write_text('Actual isolated fixture affected check completed')
            item.update(log=log.relative_to(f.work).as_posix(),sha256=digest(log),artifact_hashes={'模拟系统/项目源码.zip':self.current['模拟系统/项目源码.zip']})
        repair='/root/repair-original';self.repair_log=f.sessions/'repair.jsonl'
        args={'task_name':'repair-original','fork_turns':'none','model':'gpt-6.1-sol','reasoning_effort':'ultra'}
        f.events.extend([{'type':'response_item','payload':{'type':'function_call','name':'collaboration.spawn_agent','call_id':'repair-original','arguments':json.dumps(args)}},
                         {'type':'response_item','payload':{'type':'function_call_output','call_id':'repair-original','output':json.dumps({'task_name':repair})}}])
        f.save_dispatch()
        user='以后所有小问题定向修补并自检后直接打包，不再安排整案复验或审核。'
        with f.parent_log.open('a',encoding='utf8') as stream:stream.write(json.dumps({'type':'event_msg','payload':{'type':'user_message','message':user}},ensure_ascii=False)+'\n')
        self.proof_path=f.work/'.product-v2/repair-handoff.json'
        self.proof={'contract':closure.CONTRACT,'run_id':f.run['run_id'],'workspace':str(f.work),'case_id':'case_01',
                    'authorization':{'session_log':str(f.parent_log),'user_message_sha256':hashlib.sha256(user.encode()).hexdigest()},
                    'first_review':closure.reference(f.proof_path),'first_dispatch':closure.reference(first_dispatch),
                    'repair_dispatch':{'session_log':str(f.parent_log),'call_id':'repair-original','agent_id':repair,'repair_session_log':str(self.repair_log)},
                    'files':self.current,'changed_files':['模拟系统/项目源码.zip'],'chart_snapshot':f.charts,
                    'source_zip_sha256':self.current['模拟系统/项目源码.zip'],'video_timeline_sha256':f.proof['video_timeline_sha256'],
                    'checks':checks,'resolutions':[{'id':'search-clear','status':'resolved','result':'Search cleared through real input contract fixture',
                                                   'affected_files':['模拟系统/项目源码.zip'],'checks':['browser','package_startup']}]}
        self.save()
        self.destination=f.root/'published';self.archive=f.root/'packages'/'case.zip'
        self.patches=[patch('contracts.SESSION_ROOT',f.sessions),patch('proflow.cleanup_ready')]
        for item in self.patches:item.start();self.addCleanup(item.stop)

    def save(self,style='new'):
        write_json(self.proof_path,self.proof)
        if style=='existing':final={'repairer_agent_id':'/root/repair-original','actual_call_id':'repair-original','handoff':str(self.proof_path),'handoff_sha256':digest(self.proof_path),'current_files':self.proof['files']}
        else:final={'repairer_agent_id':'/root/repair-original','repair_evidence_sha256':digest(self.proof_path)}
        events=[{'type':'session_meta','payload':{'source':{'subagent':{'thread_spawn':{'agent_path':'/root/repair-original','parent_thread_id':'parent-fixture'}}}}},
                {'type':'turn_context','payload':{'model':'gpt-6.1-sol','effort':'ultra'}},
                {'type':'response_item','payload':{'type':'message','role':'assistant','channel':'final','content':[{'type':'output_text','text':json.dumps(final)}]}}]
        self.repair_log.write_text(''.join(json.dumps(item)+'\n' for item in events),encoding='utf8')

    def close(self):return closure.close(self.f.work,self.proof_path,self.destination,self.archive,os.getpid())

    def refresh_first(self):
        self.f.save_proof();self.proof['first_review']=closure.reference(self.f.proof_path);self.save()

    def package_only(self,content='print(1)'):
        f=self.f;(f.work/'app.py').write_text(content,encoding='utf8')
        with zipfile.ZipFile(f.system/'项目源码.zip','w',compression=zipfile.ZIP_DEFLATED) as archive:
            archive.writestr('app.py',content)
        write_json(f.work/'.product-v2/source-package.json',{'sha256':digest(f.system/'项目源码.zip'),'files':{'app.py':digest(f.work/'app.py')}})
        f.proof['issues'][0].update(required_checks=['package_startup'],title='Correct ZIP compression only')
        f.save_proof();self.proof['first_review']=closure.reference(f.proof_path)
        self.proof['files']=file_map(f.out);self.proof['source_zip_sha256']=digest(f.system/'项目源码.zip')
        self.proof['checks']=copy.deepcopy(f.proof['checks'])
        package=next(item for item in self.proof['checks'] if item['kind']=='package_startup')
        log=f.work/'.product-v2/repack-startup.log';log.write_text('Actual fixture unpack/startup/core chain for the current ZIP')
        package.update(log=log.relative_to(f.work).as_posix(),sha256=digest(log),artifact_hashes={'模拟系统/项目源码.zip':digest(f.system/'项目源码.zip')})
        self.proof['resolutions'][0].update(checks=['package_startup'],result='Repacked with current isolated startup/core chain check')
        self.save()

    def corrected_chart(self,key='layout'):
        f=self.f;first=f.proof['chart_reviews'][0]
        if key.startswith('no_'):first.update({key:False,key+'_evidence':'Actually inspected the first chart and found the prohibited text'})
        else:first[key]={'passed':False,'evidence':'Actually inspected the first chart: required axis labels overlap'}
        f.proof['issues'].append({'id':'chart-'+key,'severity':'minor','required_checks':['word_visual']})
        f.save_proof();self.proof['first_review']=closure.reference(f.proof_path)
        png=f.work/f.figures[0]['png'];png.write_bytes(png.read_bytes()+b'corrected-layout')
        f.figures[0]['sha256']=digest(png);write_json(f.work/'.product-v2/chart-manifest.json',{'figures':f.figures});f.make_word()
        from contracts import chart_snapshot
        self.proof.update(files=file_map(f.out),changed_files=sorted(['模拟系统/项目源码.zip',f.run['word_name']]),
                          chart_snapshot=chart_snapshot(f.work,f.word,f.run))
        review={'figure_id':1,'png_sha256':digest(png)}
        if key.startswith('no_'):review.update({key:True,key+'_evidence':'Opened the corrected current PNG and Word: prohibited text removed'})
        else:review[key]={'passed':True,'evidence':'Opened the corrected current PNG in Word: required axis labels readable'}
        log=f.work/'.product-v2/word-visual.log';log.write_text('Actual affected current chart and Word visual inspection fixture')
        self.proof['affected_checks']=[{'kind':'word_visual','exit_code':0,'command':'affected chart and Word inspection fixture',
            'log':log.relative_to(f.work).as_posix(),'sha256':digest(log),'artifact_hashes':{f.run['word_name']:digest(f.word)},
            'visual_notes':['Opened the current affected chart and Word page'],'chart_reviews':[review]}]
        self.proof['resolutions'].append({'id':'chart-'+key,'status':'resolved','result':'Corrected the originally failed chart judgment',
                                        'affected_files':[f.run['word_name']],'checks':['word_visual']})
        self.save()

    def word_caption_fix(self,change='keep-next'):
        f=self.f;word_name=f.run['word_name']
        f.proof['chart_reviews'][0]['layout']={'passed':False,'evidence':'The PNG is clear; in Word the drawing and caption split across pages.'}
        f.proof['issues'].append({'id':'word-caption-split','severity':'minor','required_checks':['word_visual'],'affected_artifacts':[word_name]})
        f.save_proof();self.proof['first_review']=closure.reference(f.proof_path)
        with zipfile.ZipFile(f.word) as archive:parts={name:archive.read(name) for name in archive.namelist()}
        if change=='keep-next':
            parts['word/document.xml']=parts['word/document.xml'].replace(b'<w:p><w:r><w:drawing>',b'<w:p><w:pPr><w:keepNext/></w:pPr><w:r><w:drawing>',1)
        elif change=='unrelated':
            parts['word/document.xml']=parts['word/document.xml'].replace(b'<w:sectPr/>',fixtures.p('Unrelated checked explanation').encode()+b'<w:sectPr/>')
        elif change=='disabled':
            parts['word/document.xml']=parts['word/document.xml'].replace(b'<w:p><w:r><w:drawing>',b'<w:p><w:pPr><w:keepNext w:val="0"/></w:pPr><w:r><w:drawing>',1)
        if change!='unchanged':
            with zipfile.ZipFile(f.word,'w') as archive:
                for name,data in parts.items():archive.writestr(name,data)
        from contracts import chart_snapshot
        current=file_map(f.out)
        log=f.work/'.product-v2/word-caption-layout.log';log.write_text('Affected current Word drawing/caption pagination inspection fixture')
        visual={'kind':'word_visual','command':'affected Word paragraph/layout inspection fixture','exit_code':0,
            'log':log.relative_to(f.work).as_posix(),'sha256':digest(log),'artifact_hashes':{word_name:current[word_name]},
            'visual_notes':['Inspected affected Word chart-caption pagination with its unchanged clear PNG'],
            'chart_reviews':[{'figure_id':1,'png_sha256':f.charts['figures']['1'],
                              'layout':{'passed':True,'evidence':'Current Word keep-next binds the existing drawing and caption on one page; unchanged PNG remains clear.'}}]}
        self.proof.update(files=current,changed_files=sorted(key for key in current if current[key]!=f.proof['reviewed_files'].get(key)),
                          chart_snapshot=chart_snapshot(f.work,f.word,f.run),affected_checks=[visual])
        self.proof['resolutions'].append({'id':'word-caption-split','status':'resolved','result':'Corrected the added Word drawing paragraph keep-next layout',
                                         'affected_files':[word_name],'checks':['word_visual']})
        self.save()

    def register(self,ticket_status='waiting',other_owner=False):
        f=self.f;root=f.root/'shared';target=root/'batch';target.mkdir(parents=True)
        manifest={'batch_id':'batch','media_lease_contract':'windows-job-v1','cases':[{'case_id':'case_01','workspace':str(f.work),'source_sha256':f.run['source_docx_sha256']}]}
        write_json(target/'manifest.json',manifest)
        write_json(f.work/'.product-v2/batch-binding.json',{'contract':'windows-job-v1','root':str(root),'batch_id':'batch','case_id':'case_01','manifest_sha256':digest(target/'manifest.json')})
        owner=batch_control.identity(os.getpid());write_json(target/'owner.json',owner)
        write_json(target/'state.json',{'cases':{'case_01':{'phase':'waiting_review','calls':[{'status':'completed_revise'}],'pending':['review']}}})
        tickets=[{'batch_id':'batch','case_id':'case_01','token':'own-wait','status':ticket_status,'stage':'review','owner':dict(owner,created_ticks=0) if other_owner else owner},
                 {'batch_id':'other','case_id':'case_99','token':'other-active','status':'active','stage':'build','owner':owner}]
        write_json(root/'queue.json',tickets)
        return root,target,tickets

    def test_success_atomic_zip_state_reuse_and_idempotence(self):
        root,target,tickets=self.register()
        with patch('media_evidence.validate',side_effect=AssertionError('Unchanged video frames must not be rechecked')):
            result=self.close();again=self.close()
        self.assertEqual(result,again);self.assertFalse(result['independent_pass_claimed'])
        self.assertEqual(result['files'],file_map(self.destination));self.assertFalse(self.f.out.exists())
        self.assertEqual(self.f.proof_path.read_bytes(),self.first_bytes)
        self.assertFalse((self.f.work/'.product-v2/final-receipt.json').exists())
        with zipfile.ZipFile(self.archive) as z:self.assertIsNone(z.testzip());self.assertEqual(len(z.namelist()),len(self.current))
        self.assertEqual(read_json(target/'state.json')['cases']['case_01']['phase'],'delivered')
        self.assertEqual(read_json(root/'queue.json')[0]['status'],'released')
        self.assertEqual(read_json(root/'queue.json')[1],tickets[1])
        run=read_json(self.f.work/'.product-v2/run.json');status=proflow.workflow_status(self.f.work,self.destination,run)
        self.assertEqual(status['state'],'published');self.assertFalse(status['independent_pass_claimed'])

    def test_existing_original_repair_final_handoff_hash_format_is_accepted(self):
        self.save('existing');self.assertEqual(self.close()['status'],'delivered')

    def test_actual_general_user_instructions_authorize_without_literal_selfcheck_or_case_name(self):
        for message in ('剩下的案件也按这个要求继续做，小问题定向修一下就打包，不要再反复审核返修，协调好几个批次。',
                        '把当下能导出的都做导出吧，不需要再修了，然后这几件就算完成了，以后这种小问题修一下给个压缩包就算过了，不要老是大费周章'):
            with self.subTest(message=message):
                with self.f.parent_log.open('a',encoding='utf8') as stream:
                    stream.write(json.dumps({'type':'event_msg','payload':{'type':'user_message','message':message}},ensure_ascii=False)+'\n')
                value={'session_log':str(self.f.parent_log),'user_message_sha256':hashlib.sha256(message.encode()).hexdigest()}
                self.assertEqual(closure.authorization(value,self.f.work,'case_01',self.f.parent_log),value)
                if '剩下的案件' in message:
                    with self.assertRaises(ValueError):closure.authorization(value,self.f.work,'unrelated_case')

    def test_negative_question_quote_and_assistant_policy_do_not_authorize(self):
        for message in ('以后小问题修一下就打包，不再审核，可以吗？',
                        '以后小问题修一下就打包，但不要跳过审核。',
                        '不允许以后小问题修一下就打包，不再审核。',
                        '这几件小问题修一下就打包，不再审核。',
                        '本案小问题修一下就打包，不再审核。',
                        '文档引用：以后小问题修一下就打包，不再审核。',
                        '> 以后小问题修一下就打包，不再审核。',
                        '```\n以后小问题修一下就打包，不再审核。\n```'):
            self.assertFalse(closure.authorized_instruction(message,self.f.work,'case_01'),message)
        text='以后小问题定向修补并自检后直接打包，不再审核。'
        with self.f.parent_log.open('a',encoding='utf8') as stream:
            stream.write(json.dumps({'type':'response_item','payload':{'type':'message','role':'assistant','channel':'final','content':[{'text':text}]}},ensure_ascii=False)+'\n')
        with self.assertRaisesRegex(ValueError,'actual human'):
            closure.authorization({'session_log':str(self.f.parent_log),'user_message_sha256':hashlib.sha256(text.encode()).hexdigest()},self.f.work,'case_01')

    def test_specific_authorization_has_exact_case_and_path_scope(self):
        for scope in ('case_010','case_01_extra','case_01x',str(self.f.work)+'-other',str(self.f.work/'other')):
            for prefix in ('','以后 '):
                with self.subTest(scope=scope,prefix=prefix):
                    self.assertFalse(closure.authorized_instruction(prefix+scope+' 小问题修一下就打包，不再反复审核。',self.f.work,'case_01',True))
        for scope in ('case_01',str(self.f.work),str(self.f.work).replace('\\','/')):
            self.assertTrue(closure.authorized_instruction(scope+' 小问题修一下就打包，不再反复审核。',self.f.work,'case_01',True))
        self.assertFalse(closure.authorized_instruction('case_01 小问题修一下就打包，不再反复审核。',self.f.work,'case_01'))
        self.assertTrue(closure.authorized_instruction('以后所有案件的小问题修一下就打包，不再反复审核。',self.f.work,'case_01'))

    def test_general_policy_keeps_output_location_and_unrelated_denials_separate(self):
        messages=('以后所有案件的小问题修一下就打包，不再反复审核，成品放到 D:\\研发图表。',
                  '以后所有案件的小问题修一下就打包，不再反复审核。本请求不授权改或安装技能、上传GitHub、改其他案件或停止其他项目。',
                  '不授权改或安装技能、上传GitHub，但以后所有案件的小问题修一下就打包，不再反复审核。')
        for message in messages:self.assertTrue(closure.authorized_instruction(message,self.f.work,'case_01'),message)
        message=messages[0]
        with self.f.parent_log.open('a',encoding='utf8') as stream:
            stream.write(json.dumps({'type':'event_msg','payload':{'type':'user_message','message':message}},ensure_ascii=False)+'\n')
        self.proof['authorization']['user_message_sha256']=hashlib.sha256(message.encode()).hexdigest();self.save()
        self.assertEqual(self.close()['status'],'delivered')

    def test_whole_actual_readme_new_chat_command_authorizes_general_small_fix_policy(self):
        readme=Path(__file__).resolve().parents[1]/'README.md'
        command=next(line for line in readme.read_text(encoding='utf8').splitlines() if line.startswith('使用 $software-case-batch-pro，批次材料目录：'))
        self.assertTrue(closure.authorized_instruction(command,self.f.work,'case_01'))

    def test_output_path_does_not_override_other_case_scope_or_review_denial(self):
        for message in ('以后 case_010 的小问题修一下就打包，不再反复审核，成品放到 D:\\研发图表。',
                        '以后 '+str(self.f.work)+'-other 小问题修一下就打包，不再反复审核，成品放到 D:\\研发图表。',
                        '以后所有案件的小问题修一下就打包，不再反复审核，但本请求不授权简化收尾。',
                        '以后所有案件的小问题修一下就打包，但不要跳过审核。',
                        '不授权跳过审核。以后所有案件的小问题修一下就打包，不再反复审核。'):
            self.assertFalse(closure.authorized_instruction(message,self.f.work,'case_01',True),message)

    def test_mechanical_draft_preserves_facts_and_does_not_authenticate_itself(self):
        manifest=self.f.work/'.product-v2/closure-input.json';draft_path=self.f.work/'.product-v2/closure-draft.json'
        value={key:copy.deepcopy(self.proof[key]) for key in ('authorization','case_id','repair_dispatch','checks','resolutions')}
        value.update(first_review=str(self.f.proof_path),first_dispatch=self.proof['first_dispatch']['path'])
        write_json(manifest,value);result=closure.draft(self.f.work,manifest,draft_path)
        self.assertEqual(result['status'],'unsigned-draft')
        drafted=read_json(draft_path)
        for key in ('files','changed_files','chart_snapshot','source_zip_sha256','video_timeline_sha256'):
            self.assertEqual(drafted[key],self.proof[key])
        with self.assertRaisesRegex(ValueError,'attest'):
            closure.close(self.f.work,draft_path,self.destination,self.archive)
        with self.assertRaises(ValueError):closure.draft(self.f.work,manifest,draft_path)

    def test_changed_word_uses_only_supplementary_affected_visual_check(self):
        f=self.f;f.make_word(body=None)
        # Add a permitted explanation paragraph without modifying original text or figures.
        with zipfile.ZipFile(f.word) as source:parts={item:source.read(item) for item in source.namelist()}
        parts['word/document.xml']=parts['word/document.xml'].replace(b'<w:sectPr/>',fixtures.p('Extra checked explanation').encode()+b'<w:sectPr/>')
        with zipfile.ZipFile(f.word,'w') as target:
            for name,data in parts.items():target.writestr(name,data)
        self.proof['files']=file_map(f.out);self.proof['changed_files']=sorted(['模拟系统/项目源码.zip',f.run['word_name']])
        from contracts import chart_snapshot
        self.proof['chart_snapshot']=chart_snapshot(f.work,f.word,f.run)
        log=f.work/'.product-v2/word-visual.log';log.write_text('Actual affected page and chart inspection fixture')
        self.proof['affected_checks']=[{'kind':'word_visual','exit_code':0,'command':'actual affected render inspection fixture',
            'log':log.relative_to(f.work).as_posix(),'sha256':digest(log),'artifact_hashes':{f.run['word_name']:digest(f.word)},'visual_notes':['Opened affected page and inspected text/figure boundary']}]
        self.proof['resolutions'][0]['affected_files'].append(f.run['word_name']);self.proof['resolutions'][0]['checks'].append('word_visual');self.save()
        self.assertEqual(self.close()['status'],'delivered')

    def test_missing_first_review_rejected_before_publication(self):
        self.f.proof_path.unlink()
        with self.assertRaises(ValueError):self.close()
        self.assertFalse(self.destination.exists())

    def test_unread_first_visual_and_missing_core_execution_are_rejected(self):
        f=self.f
        for mutate in (lambda p:p.update(unread_evidence=['word render']),lambda p:p.update(unread_required_visual_scope=['page 2']),lambda p:p['checks'].pop(),
                       lambda p:p['chart_reviews'][0]['layout'].update(evidence='not inspected')):
            f.proof=json.loads(self.first_bytes);mutate(f.proof);f.save_proof()
            self.proof['first_review']=closure.reference(f.proof_path);self.save()
            with self.assertRaises(ValueError):self.close()
        self.assertFalse(self.destination.exists())

    def test_standard_first_notes_cannot_claim_unread_word_or_video_as_reusable(self):
        for field,note in (('visual_notes','Word pages not read; video not inspected.'),
                           ('limitations','Word and video were not viewed in this first review.'),
                           ('visual_notes','首次Word全部页未查看，视频未观看。')):
            with self.subTest(field=field):
                self.f.proof=json.loads(self.first_bytes);self.f.proof[field]=[note];self.refresh_first()
                with self.assertRaisesRegex(ValueError,'unread'):self.close()
        self.assertFalse(self.destination.exists())

    def test_completed_required_visuals_allow_truthful_external_deployment_limitations(self):
        self.f.proof['visual_notes']=['All required Word pages, both chart PNGs and the complete video evidence were inspected.']
        self.f.proof['limitations']=['Production deployment was not inspected because deployment acceptance is outside this case.',
                                    '生产部署未查看，本案范围外。',
                                    'Production deployment was not inspected because it is outside this case. All required Word pages and video were inspected.']
        self.refresh_first();self.assertEqual(self.close()['status'],'delivered')

    def test_external_limit_cannot_hide_required_unread_evidence(self):
        from contracts import unread_visual_evidence
        for note in ('Production deployment was not inspected because it is outside this case. Word pages not read.',
                     'Word pages not read; production deployment acceptance is outside this case.',
                     '视频未观看，生产部署不属于本案范围。','not inspected'):
            self.assertTrue(unread_visual_evidence(note),note)

    def test_failed_first_chart_judgments_cannot_be_inherited_unchanged(self):
        for key in ('layout','legibility','no_title_header','no_schematic'):
            with self.subTest(key=key):
                self.f.proof=json.loads(self.first_bytes);review=self.f.proof['chart_reviews'][0]
                if key.startswith('no_'):review.update({key:False,key+'_evidence':'Actually opened chart; prohibited text remains'})
                else:review[key]={'passed':False,'evidence':'Actually opened chart; required axis labels overlap'}
                self.refresh_first()
                with self.assertRaisesRegex(ValueError,'Failed first chart'):self.close()
        self.assertFalse(self.destination.exists())

    def test_missing_first_no_header_or_schematic_evidence_is_unread_not_success(self):
        for key in ('no_title_header_evidence','no_schematic_evidence'):
            self.f.proof=json.loads(self.first_bytes);self.f.proof['chart_reviews'][0].pop(key);self.refresh_first()
            with self.assertRaisesRegex(ValueError,'quality evidence missing'):self.close()

    def test_actual_corrected_chart_passes_only_affected_visual_selfcheck(self):
        self.corrected_chart()
        with patch('media_evidence.validate',side_effect=AssertionError('Unchanged qualified video must be reused')):
            result=self.close()
        self.assertEqual(result['status'],'delivered');self.assertFalse(result['independent_pass_claimed'])
        receipt=read_json(self.f.work/'.product-v2/simplified-final-receipt.json')
        self.assertIn('模拟系统/演示视频.mp4',receipt['reused_files']);self.assertIn('模拟系统/数据/记录.csv',receipt['reused_files'])
        self.assertFalse(read_json(self.f.proof_path)['chart_reviews'][0]['layout']['passed'])

    def test_actual_removed_header_passes_affected_visual_selfcheck(self):
        self.corrected_chart('no_title_header');self.assertEqual(self.close()['status'],'delivered')

    def test_word_caption_keep_next_fix_reuses_the_already_correct_png(self):
        self.word_caption_fix()
        with patch('media_evidence.validate',side_effect=AssertionError('Unchanged video must be reused')):
            self.assertEqual(self.close()['status'],'delivered')
        first=read_json(self.f.proof_path);receipt=read_json(self.f.work/'.product-v2/simplified-final-receipt.json')
        self.assertEqual(first['chart_snapshot']['figures'],receipt['chart_snapshot']['figures'])
        self.assertFalse(first['chart_reviews'][0]['layout']['passed'])

    def test_word_caption_split_not_fixed_by_unchanged_word_or_unrelated_body_change(self):
        self.word_caption_fix('unrelated')
        with self.assertRaisesRegex(ValueError,'actual corrected chart'):self.close()

    def test_unchanged_word_and_disabled_keep_next_do_not_clear_caption_split(self):
        self.word_caption_fix('unchanged')
        with self.assertRaisesRegex(ValueError,'cannot be reused unchanged'):self.close()
        self.proof['affected_checks'][0]['chart_reviews'][0]['layout']['passed']=True
        with zipfile.ZipFile(self.f.word) as archive:parts={name:archive.read(name) for name in archive.namelist()}
        parts['word/document.xml']=parts['word/document.xml'].replace(b'<w:p><w:r><w:drawing>',b'<w:p><w:pPr><w:keepNext w:val="0"/></w:pPr><w:r><w:drawing>',1)
        with zipfile.ZipFile(self.f.word,'w') as archive:
            for name,data in parts.items():archive.writestr(name,data)
        from contracts import chart_snapshot
        self.proof.update(files=file_map(self.f.out),changed_files=sorted(['模拟系统/项目源码.zip',self.f.run['word_name']]),chart_snapshot=chart_snapshot(self.f.work,self.f.word,self.f.run))
        self.proof['affected_checks'][0]['artifact_hashes']={self.f.run['word_name']:digest(self.f.word)};self.save()
        with self.assertRaisesRegex(ValueError,'actual corrected chart'):self.close()

    def test_corrected_chart_requires_current_specific_visual_judgment(self):
        self.corrected_chart();self.proof['affected_checks'][0].pop('chart_reviews');self.save()
        with self.assertRaisesRegex(ValueError,'corresponding affected'):self.close()

    def test_unrelated_word_change_cannot_clear_unchanged_failed_chart(self):
        self.corrected_chart()
        original=read_json(self.f.proof_path)['chart_snapshot']['figures']['1']
        self.f.figures[0]['sha256']=original
        png=self.f.work/self.f.figures[0]['png'];png.write_bytes(png.read_bytes().removesuffix(b'corrected-layout'))
        write_json(self.f.work/'.product-v2/chart-manifest.json',{'figures':self.f.figures});self.f.make_word()
        with zipfile.ZipFile(self.f.word) as archive:parts={item:archive.read(item) for item in archive.namelist()}
        parts['word/document.xml']=parts['word/document.xml'].replace(b'<w:sectPr/>',fixtures.p('Unrelated explanation change').encode()+b'<w:sectPr/>')
        with zipfile.ZipFile(self.f.word,'w') as archive:
            for name,data in parts.items():archive.writestr(name,data)
        from contracts import chart_snapshot
        self.proof.update(files=file_map(self.f.out),chart_snapshot=chart_snapshot(self.f.work,self.f.word,self.f.run))
        self.proof['affected_checks'][0]['artifact_hashes']={self.f.run['word_name']:digest(self.f.word)};self.save()
        with self.assertRaisesRegex(ValueError,'actual corrected chart'):self.close()

    def test_member_identical_repack_reuses_business_video_and_data(self):
        self.package_only()
        old_checks=read_json(self.f.proof_path)['checks']
        for item in self.proof['checks']:
            if item['kind']!='package_startup':self.assertIn(item,old_checks)
        with patch('media_evidence.validate',side_effect=AssertionError('Unchanged video must not be reread')):
            self.assertEqual(self.close()['status'],'delivered')

    def test_changed_executable_is_not_packaging_only_even_if_declared_minor(self):
        self.package_only('print(3)')
        with self.assertRaisesRegex(ValueError,'Core defect'):self.close()

    def test_unbound_or_missing_old_members_do_not_prove_packaging_only(self):
        self.package_only()
        prior=copy.deepcopy(self.f.proof['source_package'])
        for value in (None,dict(prior,sha256='0'*64)):
            if value is None:self.f.proof.pop('source_package',None)
            else:self.f.proof['source_package']=value
            self.refresh_first()
            with self.assertRaises(ValueError):self.close()
        self.proof['source_package']=prior;self.save()
        with self.assertRaises(ValueError):self.close()  # A repairer's new assertion cannot replace first-review evidence.

    def test_identical_members_do_not_override_explicit_core_issue(self):
        self.package_only();self.f.proof['issues'][0]['core']=True;self.refresh_first()
        with self.assertRaisesRegex(ValueError,'Core defect'):self.close()

    def test_bad_or_missing_artifact_never_delivered(self):
        for path,data in ((self.f.system/'项目源码.zip',b'broken'),(self.f.word,b'broken')):
            original=path.read_bytes();path.write_bytes(data)
            self.proof['files']=file_map(self.f.out);self.proof['source_zip_sha256']=digest(self.f.system/'项目源码.zip');self.save()
            with self.assertRaises((ValueError,zipfile.BadZipFile)):self.close()
            path.write_bytes(original)
        (self.f.system/'演示视频.mp4').unlink()
        with self.assertRaises(ValueError):self.close()
        self.assertFalse(self.destination.exists())

    def test_wrong_run_changed_evidence_and_fake_role_json_are_rejected(self):
        original=copy.deepcopy(self.proof)
        for mutate in (lambda p:p.update(run_id='wrong-case'),
                       lambda p:p['repair_dispatch'].update(agent_id='/root/build'),
                       lambda p:p['first_dispatch'].update(sha256='0'*64)):
            self.proof=copy.deepcopy(original);mutate(self.proof);self.save()
            with self.assertRaises(ValueError):self.close()
        self.proof=original;self.save();self.proof_path.write_text(self.proof_path.read_text()+' ')
        with self.assertRaises(ValueError):self.close()

    def test_core_issue_unresolved_and_missing_affected_coverage_rejected(self):
        self.proof['resolutions'][0]['status']='pending';self.save()
        with self.assertRaisesRegex(ValueError,'Unresolved'):self.close()
        self.proof['resolutions'][0]['status']='resolved';self.proof['resolutions'][0]['checks']=['package_startup'];self.save()
        with self.assertRaisesRegex(ValueError,'required affected'):self.close()
        f=self.f;f.proof['issues'][0].update(severity='core',required_checks=['package_startup']);f.save_proof()
        self.proof['first_review']=closure.reference(f.proof_path);self.save()
        with self.assertRaisesRegex(ValueError,'Core defect'):self.close()

    def test_active_work_and_other_owner_wait_preserved(self):
        for status,other in (('active',False),('waiting',True)):
            # Build a fresh isolated registry for each safety branch.
            binding=self.f.work/'.product-v2/batch-binding.json'
            if binding.exists():binding.unlink()
            if (self.f.root/'shared').exists():
                import shutil
                shutil.rmtree(self.f.root/'shared')
            root,target,tickets=self.register(status,other)
            before=(root/'queue.json').read_bytes()
            with self.assertRaisesRegex(ValueError,'preserved'):self.close()
            self.assertEqual((root/'queue.json').read_bytes(),before);self.assertFalse(self.destination.exists())

    def test_recover_after_directory_rename_before_publish_receipt(self):
        original=proflow.write_json;failed=[False]
        def interrupt(path,value):
            if Path(path).name=='publish-receipt.json' and not failed[0]:failed[0]=True;raise OSError('synthetic interruption')
            return original(path,value)
        with patch('proflow.write_json',side_effect=interrupt),self.assertRaises(OSError):self.close()
        self.assertTrue(self.destination.is_dir());self.assertFalse(self.archive.exists())
        self.assertEqual(self.close()['status'],'delivered')

    def test_recover_missing_zip_then_after_zip_rename_and_state_write(self):
        root,target,_=self.register()
        with patch('simplified_closure.whole_case',side_effect=OSError('synthetic before ZIP')),self.assertRaises(OSError):self.close()
        self.assertTrue(self.destination.exists());self.assertFalse(self.archive.exists())
        original=closure.write_json
        def interrupt(path,value):
            if Path(path).name=='whole-case-package.json':raise OSError('synthetic after ZIP rename')
            return original(path,value)
        with patch('simplified_closure.write_json',side_effect=interrupt),self.assertRaises(OSError):self.close()
        self.assertTrue(self.archive.exists())
        original_batch=batch_control.write_json
        def fail_state(path,value):
            if Path(path)==target/'state.json':raise OSError('synthetic state-write interruption')
            return original_batch(path,value)
        with patch('batch_control.write_json',side_effect=fail_state),self.assertRaises(OSError):self.close()
        self.assertEqual(read_json(root/'queue.json')[0]['status'],'released')
        self.assertEqual(self.close()['status'],'delivered')
        self.assertEqual(read_json(target/'state.json')['cases']['case_01']['phase'],'delivered')

    def test_changed_dependency_cannot_reuse_original_success_log(self):
        first=self.f.proof['checks'][-1]
        self.proof['checks'][-1].update(log=first['log'],sha256=first['sha256']);self.save()
        with self.assertRaisesRegex(ValueError,'Reused successful'):self.close()

    def test_saved_closure_or_archive_changed_is_rejected_on_resume(self):
        self.close();self.archive.write_bytes(b'broken')
        with self.assertRaises((ValueError,zipfile.BadZipFile)):self.close()
        run=read_json(self.f.work/'.product-v2/run.json')
        self.assertEqual(proflow.workflow_status(self.f.work,self.destination,run)['state'],'unknown')

    def test_ordinary_finalize_still_rejects_original_revise(self):
        # This route never manufactures a pass/final receipt for ordinary finalize.
        with self.assertRaises(ValueError):proflow.finalize(self.f.work,self.f.out,self.f.proof_path)
        self.assertFalse((self.f.work/'.product-v2/final-receipt.json').exists())


if __name__=='__main__':unittest.main()
