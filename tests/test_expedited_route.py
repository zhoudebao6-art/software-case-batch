"""Isolated route/admission fixtures, never paid model calls or case acceptance."""
import copy
import hashlib
import json
from pathlib import Path
import sys
import unittest
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
import batch_control as batch
from common import digest,read_json,write_json
import test_workflow as workflow_fixtures
import test_contracts as contract_fixtures

class ExpeditedRouteTests(unittest.TestCase):
    def setUp(self):
        self.fixture=workflow_fixtures.WorkflowTests();self.fixture.setUp();self.root=self.fixture.root;self.pool=self.fixture.pool
        self.sessions=self.root/'sessions';self.sessions.mkdir();self.session_patch=patch('contracts.SESSION_ROOT',self.sessions);self.session_patch.start()
        self.fixture.preflight();legacy=read_json(self.pool/'test-batch/state.json')
        self.preflight=self.root/'modern-preflight.json';write_json(self.preflight,read_json(legacy['environment_preflight']['path']))
        cases=read_json(self.fixture.cases)['cases'];fifth=self.root/'work5';fifth.mkdir();source=fifth/'source.docx';source.write_bytes(b'fixture source five')
        cases.append({'case_id':'c5','workspace':str(fifth),'source_docx':str(source),'source_sha256':digest(source)})
        write_json(self.fixture.cases,{'cases':cases})
        for case in cases:
            work=Path(case['workspace']);write_json(work/'.product-v2/run.json',{'workspace':str(work),'run_id':'run-'+case['case_id']})
        batch.register(self.pool,'modern',self.fixture.cases,'modern fixture authorization',4,2);batch.claim(self.pool,'modern',202)
        self.call('preflight',value=self.preflight)
    def tearDown(self):self.session_patch.stop();self.fixture.tearDown()
    def call(self,action,case_id=None,**kw):return batch.mutate(self.pool,'modern',202,action,case_id,**kw)
    def authorization(self,case_id,work=None,run_id=None,parent_log=None):
        work=work or self.root/('work'+case_id[1:]);run_id=run_id or 'run-'+case_id
        statement=case_id+' 使用原加急模式';log=parent_log or self.sessions/(case_id+'.jsonl')
        event={'type':'response_item','payload':{'type':'message','role':'user','content':[{'type':'input_text','text':statement}]}}
        with log.open('a',encoding='utf-8') as stream:stream.write(json.dumps(event)+'\n')
        record={'run_id':run_id,'workspace':str(work),'scope_name':case_id,'statement':statement,'session_log':str(log),'user_message_sha256':hashlib.sha256(statement.encode()).hexdigest()}
        path=self.root/(case_id+'-authorization.json');write_json(path,record);return path
    def grant(self,case_id):
        path=self.authorization(case_id);self.call('expedite',case_id,authorization=path);return path
    def queue(self,case_id,stage='review'):return self.call('queue',case_id,stage=stage)
    def acquire(self,ticket):return self.call('acquire',token=ticket['token'])
    def release(self,ticket):return self.call('release-slot',token=ticket['token'])
    def verify(self,ticket):return self.call('verify-review',ticket['case_id'],token=ticket['token'],value=self.root/('work'+ticket['case_id'][1:]))
    def test_expedite_sets_ten_for_all_waiting_stages(self):
        for case_id,stage in zip(('c1','c2','c3','c4'),('build','record','evidence','review')):
            ticket=self.queue(case_id,stage);before=read_json(self.pool/'queue.json')[-1]
            self.grant(case_id);current=next(q for q in read_json(self.pool/'queue.json') if q['token']==ticket['token'])
            self.assertEqual(current['priority'],10);self.assertEqual(current['submitted_ns'],before['submitted_ns'])
            self.assertEqual(current['stage'],'expedited' if stage=='review' else stage)
        state=read_json(self.pool/'modern/state.json');self.assertTrue(all(state['cases'][c]['priority']==10 for c in ('c1','c2','c3','c4')))
    def test_future_review_selects_scoped_astra_and_unscoped_explicit_route_refuses(self):
        self.grant('c1');ticket=self.queue('c1');self.assertEqual(ticket['stage'],'expedited')
        active=self.acquire(ticket);admission=batch.load_review_admission(self.root/'work1',active['review_admission'])
        self.assertEqual([admission['model'],admission['effort']],['gpt-6-astra','low'])
        with self.assertRaisesRegex(ValueError,'Unscoped'):self.queue('c2','expedited')
    def test_changed_authorization_refuses_queue_and_acquisition_without_downgrade(self):
        path=self.grant('c1');ticket=self.queue('c1');write_json(path,{})
        with self.assertRaisesRegex(ValueError,'authorization changed'):self.acquire(ticket)
        with self.assertRaisesRegex(ValueError,'authorization changed'):self.queue('c1')
        current=next(q for q in read_json(self.pool/'queue.json') if q['token']==ticket['token']);self.assertEqual(current['status'],'waiting');self.assertEqual(current['stage'],'expedited')
    def test_real_user_statement_is_rechecked_at_admission(self):
        path=self.grant('c1');ticket=self.queue('c1');Path(read_json(path)['session_log']).write_text('{}\n',encoding='utf-8')
        with self.assertRaisesRegex(ValueError,'real user message'):self.acquire(ticket)
    def test_expedited_candidate_gets_next_shared_worker_without_preempting_active_builds(self):
        active=[self.acquire(self.queue(c,'build')) for c in ('c1','c2','c3')]
        self.grant('c4');urgent=self.queue('c4');ordinary=self.queue('c5','build')
        original=copy.deepcopy(read_json(self.pool/'queue.json')[:3]);self.release(active[0])
        waiting=self.acquire(ordinary);self.assertFalse(waiting['acquired']);self.assertIn('higher-priority model stage',waiting['reason'])
        self.assertEqual(self.acquire(urgent)['status'],'active')
        current=read_json(self.pool/'queue.json');self.assertEqual(current[1:3],original[1:3])
        self.grant('c1');next_urgent=self.queue('c1');self.release(active[1])
        self.assertEqual(self.acquire(ordinary)['status'],'active') # expedited's own one slot is full.
        self.assertEqual(next_urgent['status'],'waiting')
    def test_nonrunnable_expedited_candidates_never_hold_ordinary_model_capacity(self):
        path=self.grant('c1');urgent=self.queue('c1');baseline=read_json(self.pool/'modern/state.json')
        original_auth=path.read_bytes();source=self.root/'work1/source.docx';original_source=source.read_bytes();original_preflight=self.preflight.read_bytes()
        for fault in ('drain','blocked','delivered','owner_dead','authorization_changed','source_changed','preflight_changed'):
            with self.subTest(fault=fault):
                state=copy.deepcopy(baseline)
                if fault=='drain':state['drain']=True
                if fault in {'blocked','delivered'}:state['cases']['c1']['phase']=fault
                write_json(self.pool/'modern/state.json',state)
                if fault=='authorization_changed':write_json(path,{})
                if fault=='source_changed':source.write_bytes(b'changed source')
                if fault=='preflight_changed':write_json(self.preflight,{})
                ordinary=self.fixture.mutate('queue','c2',stage='build')
                with patch('batch_control.identity',side_effect=lambda pid:None if fault=='owner_dead' and pid==202 else {'pid':pid,'created_ticks':pid+1000}):
                    self.assertEqual(self.fixture.mutate('acquire',token=ordinary['token'])['status'],'active')
                self.fixture.mutate('release-slot',token=ordinary['token'])
                path.write_bytes(original_auth);source.write_bytes(original_source);self.preflight.write_bytes(original_preflight)
        self.assertEqual(next(q for q in read_json(self.pool/'queue.json') if q['token']==urgent['token'])['status'],'waiting')
    def test_invalid_expedited_head_does_not_block_a_valid_later_expedited_ticket(self):
        first_auth=self.grant('c1');first=self.queue('c1');self.grant('c2');second=self.queue('c2');write_json(first_auth,{})
        self.assertEqual(self.acquire(second)['status'],'active');self.assertEqual(first['status'],'waiting')
    def test_active_ordinary_route_admission_is_frozen_and_future_review_becomes_astra(self):
        active=self.acquire(self.queue('c1'));before=copy.deepcopy(active);bytes_before=Path(active['review_admission']['path']).read_bytes()
        update=self.root/'counts.json';write_json(update,{'phase':'reviewing','calls':[{'attempt':'retained-prior-call'}],'usage':[{'tokens':42}]});self.call('update','c1',value=update)
        self.grant('c1');current=next(q for q in read_json(self.pool/'queue.json') if q['token']==active['token'])
        self.assertEqual(current,before);self.assertEqual(Path(active['review_admission']['path']).read_bytes(),bytes_before)
        state=read_json(self.pool/'modern/state.json')['cases']['c1'];self.assertEqual(state['calls'],[{'attempt':'retained-prior-call'}]);self.assertEqual(state['usage'],[{'tokens':42}])
        permit=self.verify(active);self.assertEqual([permit['model'],permit['effort']],['gpt-6.1-sol','ultra'])
        self.release(active);future=self.acquire(self.queue('c1'));self.assertEqual(future['stage'],'expedited')
    def test_paid_before_dispatch_verification_rejects_changed_authorization_and_retains_active_slot(self):
        path=self.grant('c1');active=self.acquire(self.queue('c1'));write_json(path,{})
        with self.assertRaisesRegex(ValueError,'before actual model dispatch'):self.verify(active)
        current=next(q for q in read_json(self.pool/'queue.json') if q['token']==active['token']);self.assertEqual(current['status'],'active');self.assertNotIn('review_dispatch_permit',current)
    def test_dispatch_permit_is_immutable_and_wrong_case_or_owner_refuses(self):
        active=self.acquire(self.queue('c1'));permit=self.verify(active);path=Path(permit['review_dispatch_permit']['path']);before=path.read_bytes()
        self.assertEqual(self.verify(active),permit);self.assertEqual(path.read_bytes(),before)
        with self.assertRaisesRegex(ValueError,'different registered case'):self.call('verify-review','c2',token=active['token'],value=self.root/'work2')
        with self.assertRaisesRegex(ValueError,'current verified parent'):batch.mutate(self.pool,'modern',203,'verify-review','c1',self.root/'work1',active['token'])
    def test_case_authorization_cannot_be_retargeted_by_changing_run_and_workspace(self):
        path=self.authorization('c1');record=read_json(path);record.update(run_id='run-c2',workspace=str(self.root/'work2'));write_json(path,record)
        with self.assertRaisesRegex(ValueError,'registered case/batch'):self.call('expedite','c2',authorization=path)
        self.assertNotIn('expedited_authorization',read_json(self.pool/'modern/state.json')['cases']['c2'])
    def test_authorization_names_another_batch_cannot_authorize_modern_case(self):
        record=read_json(self.authorization('c1'));statement='other-batch 使用原加急模式';event={'type':'response_item','payload':{'type':'message','role':'user','content':[{'type':'input_text','text':statement}]}}
        Path(record['session_log']).write_text(json.dumps(event)+'\n',encoding='utf-8');record.update(scope_name='other-batch',statement=statement,user_message_sha256=hashlib.sha256(statement.encode()).hexdigest())
        path=self.root/'other-batch-authorization.json';write_json(path,record)
        with self.assertRaisesRegex(ValueError,'registered case/batch'):self.call('expedite','c1',authorization=path)
    def test_registered_batch_scope_authorizes_only_its_confirmed_cases(self):
        statement='modern 使用原加急模式';log=self.sessions/'batch.jsonl';log.write_text(json.dumps({'type':'response_item','payload':{'type':'message','role':'user','content':[{'type':'input_text','text':statement}]}})+'\n',encoding='utf-8')
        for case_id in ('c1','c2'):
            path=self.root/(case_id+'-batch-authorization.json');write_json(path,{'run_id':'run-'+case_id,'workspace':str(self.root/('work'+case_id[1:])),'scope_name':'modern','statement':statement,'session_log':str(log),'user_message_sha256':hashlib.sha256(statement.encode()).hexdigest()})
            self.call('expedite',case_id,authorization=path);self.assertEqual(self.queue(case_id)['stage'],'expedited')
        self.assertEqual(self.queue('c3')['stage'],'review')
    def test_duplicate_case_titles_require_registered_ids_and_unique_aliases_are_frozen(self):
        cases=[]
        for index,title in enumerate(('同名业务','同名业务','唯一业务')):
            work=self.root/f'aliases-{index}';work.mkdir();source=work/'source.docx';source.write_bytes(b'alias fixture');write_json(work/'.product-v2/run.json',{'workspace':str(work),'run_id':f'alias-{index}','title':title})
            cases.append({'case_id':f'a{index}','workspace':str(work),'source_docx':str(source),'source_sha256':digest(source)})
        path=self.root/'alias-cases.json';write_json(path,{'cases':cases});manifest=batch.register(self.pool,'aliases',path,'isolated frozen alias fixture',4,2);batch.claim(self.pool,'aliases',203)
        for case in manifest['cases'][:2]:self.assertNotIn('同名业务',case['authorization_scope_names'])
        self.assertIn('唯一业务',manifest['cases'][2]['authorization_scope_names'])
        record=read_json(self.authorization('a0',Path(cases[0]['workspace']),'alias-0'));statement='同名业务 使用原加急模式';Path(record['session_log']).write_text(json.dumps({'type':'response_item','payload':{'type':'message','role':'user','content':[{'type':'input_text','text':statement}]}})+'\n',encoding='utf-8');record.update(scope_name='同名业务',statement=statement,user_message_sha256=hashlib.sha256(statement.encode()).hexdigest());auth=self.root/'ambiguous-title.json';write_json(auth,record)
        with self.assertRaisesRegex(ValueError,'unique frozen case alias'):batch.mutate(self.pool,'aliases',203,'expedite','a0',authorization=auth)
        original=digest(self.pool/'aliases/manifest.json');run_path=Path(cases[2]['workspace'])/'.product-v2/run.json';run=read_json(run_path);run['title']='同名业务';write_json(run_path,run)
        self.assertEqual(digest(self.pool/'aliases/manifest.json'),original);self.assertIn('唯一业务',manifest['cases'][2]['authorization_scope_names'])
    def test_urgent_build_wins_shared_worker_over_ordinary_review_and_stays_high(self):
        active=[self.acquire(self.queue(c,'build')) for c in ('c3','c4')];self.grant('c1');urgent=self.queue('c1','build');ordinary=self.queue('c2')
        waiting=self.acquire(ordinary);self.assertFalse(waiting['acquired']);self.assertEqual(waiting['priority_token'],urgent['token'])
        self.assertEqual(self.acquire(urgent)['stage'],'build');self.assertEqual(read_json(self.pool/'modern/manifest.json')['models']['build'],['gpt-6.1-sol','high'])
        current=read_json(self.pool/'queue.json');self.assertEqual(current[:2],active)
    def test_invalid_urgent_build_authorization_does_not_block_ordinary_review(self):
        path=self.grant('c1');urgent=self.queue('c1','build');write_json(path,{})
        self.assertEqual(self.acquire(self.queue('c2'))['status'],'active')
        with self.assertRaisesRegex(ValueError,'authorization changed'):self.acquire(urgent)
    def test_same_priority_cross_stage_is_left_to_parent_without_new_global_fifo(self):
        for case_id in ('c3','c4'):self.acquire(self.queue(case_id,'build'))
        earlier=self.queue('c1','build');later=self.queue('c2')
        self.assertEqual(self.acquire(later)['status'],'active');self.assertEqual(earlier['status'],'waiting')
    def test_corrupt_prepared_review_run_cannot_block_ordinary_model_capacity(self):
        self.grant('c1');urgent=self.queue('c1');path=self.root/'work1/.product-v2/run.json';run=read_json(path);run['workspace']=str(self.root/'different-workspace');write_json(path,run)
        self.assertEqual(self.acquire(self.queue('c2','build'))['status'],'active')
        with self.assertRaises(ValueError):self.acquire(urgent)
        self.assertEqual(next(q for q in read_json(self.pool/'queue.json') if q['token']==urgent['token'])['status'],'waiting')
    def natural_authorization(self,case_id,statement,scope_name=None,context=None,message_text=None):
        scope_name=scope_name or case_id;log=self.sessions/(case_id+'-natural.jsonl');actual=message_text or statement
        event={'type':'response_item','payload':{'type':'message','role':'user','content':[{'type':'input_text','text':actual}]}}
        with log.open('a',encoding='utf-8') as stream:stream.write(json.dumps(event)+'\n')
        record={'run_id':'run-'+case_id,'workspace':str(self.root/('work'+case_id[1:])),'scope_name':scope_name,'statement':statement,'session_log':str(log),'user_message_sha256':hashlib.sha256(actual.encode()).hexdigest()}
        if context:record['scope_context']=context
        path=self.root/(case_id+'-natural-authorization.json');write_json(path,record);return path
    def question_card_authorization(self,answers=None,actual=None,role='user',request=True,parent=True):
        statement='加急modern/c1';call_id='call_question_card';answers=answers or [statement]
        replies=[{'questionItemId':json.dumps(['request_user_input_async',call_id,index],separators=(',',':')),
                  'question':'请只回复这一行：'+answer,'answer':answer} for index,answer in enumerate(answers)]
        text=actual if actual is not None else '<send_user_message_question_reply>\n'+json.dumps(replies,ensure_ascii=False,separators=(',',':'))+'\n</send_user_message_question_reply>\n'
        meta={'type':'session_meta','payload':{'id':'parent-card-fixture','thread_source':'user' if parent else 'subagent'}}
        ask={'type':'response_item','payload':{'type':'function_call','name':'request_user_input_async','call_id':call_id,
             'arguments':json.dumps({'questions':[{'title':reply['question']} for reply in replies]},ensure_ascii=False)}}
        message={'type':'response_item','payload':{'type':'message','role':role,'content':[{'type':'input_text','text':text}]}}
        events=[meta]+([ask] if request else [])+[message]
        log=self.sessions/'c1-question-card.jsonl';log.write_text(''.join(json.dumps(event,ensure_ascii=False)+'\n' for event in events),encoding='utf-8')
        record={'run_id':'run-c1','workspace':str(self.root/'work1'),'scope_name':'modern/c1','statement':statement,
                'session_log':str(log),'user_message_sha256':hashlib.sha256(text.encode()).hexdigest()}
        path=self.root/'c1-question-card-authorization.json';write_json(path,record);return path,replies,events
    def save_question_card(self,path,replies,events):
        text='<send_user_message_question_reply>\n'+json.dumps(replies,ensure_ascii=False,separators=(',',':'))+'\n</send_user_message_question_reply>\n'
        events[-1]['payload']['content'][0]['text']=text
        record=read_json(path);record['user_message_sha256']=hashlib.sha256(text.encode()).hexdigest();write_json(path,record)
        Path(record['session_log']).write_text(''.join(json.dumps(event,ensure_ascii=False)+'\n' for event in events),encoding='utf-8')
    def test_actual_breaker_question_card_shape_and_entire_message_hash_select_astra_low(self):
        batch_id='1014胡长浩_20261014';case_id='breaker_method';scope=batch_id+'/'+case_id;statement='加急'+scope
        call_id='call_712a98c7cde849e09b2e5c7d959c6fe3';question='请只回复这一行，不加句号或说明：'+statement
        reply={'questionItemId':json.dumps(['request_user_input_async',call_id,0],ensure_ascii=False,separators=(',',':')),'question':question,'answer':statement}
        actual='<send_user_message_question_reply>\n'+json.dumps([reply],ensure_ascii=False,separators=(',',':'))+'\n</send_user_message_question_reply>\n'
        self.assertEqual(hashlib.sha256(actual.encode()).hexdigest(),'51b6bf8211ef39e0b8a772c28216c8c8a081a7f4ebe15076276488a304bde448')
        work=self.root/'breaker-work';work.mkdir();source=work/'source.docx';source.write_bytes(b'isolated real-card shape fixture')
        write_json(work/'.product-v2/run.json',{'workspace':str(work),'run_id':'breaker-run'})
        cases=self.root/'breaker-cases.json';write_json(cases,{'cases':[{'case_id':case_id,'workspace':str(work),'source_docx':str(source),'source_sha256':digest(source)}]})
        batch.register(self.pool,batch_id,cases,'isolated real-card regression',4,2);batch.claim(self.pool,batch_id,203)
        call=lambda action,**kw:batch.mutate(self.pool,batch_id,203,action,case_id,**kw)
        call('preflight',value=self.preflight)
        log=self.sessions/'actual-breaker-card.jsonl';events=[{'type':'session_meta','payload':{'id':'actual-card-parent-fixture','thread_source':'user','source':'vscode'}},
          {'type':'response_item','payload':{'type':'function_call','name':'request_user_input_async','call_id':call_id,'arguments':json.dumps({'questions':[{'title':question}]},ensure_ascii=False)}},
          {'type':'response_item','payload':{'type':'message','role':'user','content':[{'type':'input_text','text':actual}]}}]
        log.write_text(''.join(json.dumps(event,ensure_ascii=False)+'\n' for event in events),encoding='utf-8')
        path=self.root/'breaker-card-authorization.json';write_json(path,{'run_id':'breaker-run','workspace':str(work),'scope_name':scope,'statement':statement,'session_log':str(log),'user_message_sha256':hashlib.sha256(actual.encode()).hexdigest()})
        call('expedite',authorization=path);ticket=call('queue',stage='review');active=call('acquire',token=ticket['token'])
        self.assertEqual(active['stage'],'expedited');permit=call('verify-review',token=active['token'],value=work)
        self.assertEqual([permit['model'],permit['effort']],['gpt-6-astra','low'])
        verified=read_json(self.pool/batch_id/'state.json')['cases'][case_id]['expedited_authorization']['verified']
        self.assertEqual(verified['user_message_sha256'],hashlib.sha256(actual.encode()).hexdigest());self.assertEqual(verified['batch_binding']['case_id'],case_id)
    def test_question_card_selects_unique_answer_in_multiple_questions(self):
        path,_,_=self.question_card_authorization(['资料已核对','加急modern/c1','加急modern/c2'])
        self.call('expedite','c1',authorization=path);self.assertEqual(self.queue('c1')['stage'],'expedited')
    def test_question_prompt_or_other_roles_cannot_authorize(self):
        for answer in ('先按普通独立验收','不要加急modern/c1','如果批准，加急modern/c1','示例：加急modern/c1','加急modern/c1。额外说明','加急modern/c1\n其他要求','',{'answer':'加急modern/c1'}):
            with self.subTest(answer=answer):
                path,replies,events=self.question_card_authorization();replies[0]['answer']=answer;self.save_question_card(path,replies,events)
                with self.assertRaisesRegex(ValueError,'real user message'):self.call('expedite','c1',authorization=path)
        for role in ('assistant','tool'):
            with self.subTest(role=role):
                path,_,_=self.question_card_authorization(role=role)
                with self.assertRaisesRegex(ValueError,'real user message'):self.call('expedite','c1',authorization=path)
        for answer in ('加急\nmodern/c1','加急\r\nmodern/c1','加急\u2028modern/c1'):
            with self.subTest(multiline_statement=answer):
                path,replies,events=self.question_card_authorization();record=read_json(path);record['statement']=answer;write_json(path,record)
                replies[0]['answer']=answer;self.save_question_card(path,replies,events)
                with self.assertRaisesRegex(ValueError,'real user message'):self.call('expedite','c1',authorization=path)
    def test_question_card_requires_actual_prior_parent_request_and_matching_question(self):
        for fault in ('missing_request','child_session','wrong_call','wrong_index','boolean_index','wrong_question','late_request','duplicate_call'):
            with self.subTest(fault=fault):
                path,replies,events=self.question_card_authorization(request=fault!='missing_request',parent=fault!='child_session')
                if fault=='wrong_call':replies[0]['questionItemId']='["request_user_input_async","call_missing",0]'
                if fault=='wrong_index':replies[0]['questionItemId']='["request_user_input_async","call_question_card",1]'
                if fault=='boolean_index':replies[0]['questionItemId']='["request_user_input_async","call_question_card",false]'
                if fault=='wrong_question':replies[0]['question']='伪造提问'
                if fault=='late_request':events.insert(1,events.pop())
                if fault=='duplicate_call':events.insert(2,copy.deepcopy(events[1]))
                if fault=='late_request':
                    record=read_json(path);Path(record['session_log']).write_text(''.join(json.dumps(event,ensure_ascii=False)+'\n' for event in events),encoding='utf-8')
                else:self.save_question_card(path,replies,events)
                with self.assertRaisesRegex(ValueError,'real user message'):self.call('expedite','c1',authorization=path)
    def test_question_card_rejects_duplicate_ambiguous_nested_or_quoted_payloads(self):
        for answers in (['加急modern/c1','加急modern/c1'],['加急modern/c1','modern/c1不要加急']):
            with self.subTest(answers=answers):
                path,_,_=self.question_card_authorization(answers)
                with self.assertRaisesRegex(ValueError,'real user message'):self.call('expedite','c1',authorization=path)
        for fault in ('duplicate_id','duplicate_key','nested_answer','nested_wrapper','material_prefix','code_fence','truncated_json','object_payload'):
            with self.subTest(fault=fault):
                path,replies,events=self.question_card_authorization(['加急modern/c1','资料已核对'])
                if fault=='duplicate_id':replies[1]['questionItemId']=replies[0]['questionItemId']
                if fault=='nested_answer':replies[0]['answer']='<send_user_message_question_reply>加急modern/c1</send_user_message_question_reply>'
                self.save_question_card(path,replies,events);record=read_json(path);actual=events[-1]['payload']['content'][0]['text']
                if fault=='duplicate_key':actual=actual.replace('"answer":"加急modern/c1"','"answer":"不要加急modern/c1","answer":"加急modern/c1"')
                if fault=='nested_wrapper':actual='<send_user_message_question_reply>'+actual+'</send_user_message_question_reply>'
                if fault=='material_prefix':actual='材料引用：\n'+actual
                if fault=='code_fence':actual='```json\n'+actual+'```'
                if fault=='truncated_json':actual=actual.replace('}]','}')
                if fault=='object_payload':actual='<send_user_message_question_reply>'+json.dumps(replies[0],ensure_ascii=False)+'</send_user_message_question_reply>'
                events[-1]['payload']['content'][0]['text']=actual;record['user_message_sha256']=hashlib.sha256(actual.encode()).hexdigest();write_json(path,record)
                Path(record['session_log']).write_text(''.join(json.dumps(event,ensure_ascii=False)+'\n' for event in events),encoding='utf-8')
                with self.assertRaisesRegex(ValueError,'real user message'):self.call('expedite','c1',authorization=path)
    def test_question_card_entire_hash_run_workspace_scope_and_request_remain_bound(self):
        for fault in ('answer_hash','wrong_hash','run','workspace','cross_case','cross_batch'):
            with self.subTest(fault=fault):
                path,_,_=self.question_card_authorization();record=read_json(path)
                if fault=='answer_hash':record['user_message_sha256']=hashlib.sha256(record['statement'].encode()).hexdigest()
                if fault=='wrong_hash':record['user_message_sha256']='0'*64
                if fault=='run':record['run_id']='another-run'
                if fault=='workspace':record['workspace']=str(self.root/'work2')
                if fault=='cross_case':record.update(run_id='run-c2',workspace=str(self.root/'work2'),scope_name='modern/c2',statement='加急modern/c2')
                if fault=='cross_batch':record.update(scope_name='other/c1',statement='加急other/c1')
                write_json(path,record)
                with self.assertRaises(ValueError):self.call('expedite','c2' if fault=='cross_case' else 'c1',authorization=path)
        path,_,events=self.question_card_authorization();self.call('expedite','c1',authorization=path);ticket=self.queue('c1')
        events[1]['payload']['arguments']=json.dumps({'questions':[{'title':'changed request'}]})
        Path(read_json(path)['session_log']).write_text(''.join(json.dumps(event,ensure_ascii=False)+'\n' for event in events),encoding='utf-8')
        with self.assertRaisesRegex(ValueError,'real user message'):self.acquire(ticket)
    def test_plain_case_and_named_batch_expedite_commands_select_astra_low(self):
        for case_id,statement,scope in (('c1','c1加急','c1'),('c2','modern 这批加急','modern'),('c3','加急c3','c3'),('c4','c4请加急','c4')):
            self.call('expedite',case_id,authorization=self.natural_authorization(case_id,statement,scope));active=self.acquire(self.queue(case_id)) if case_id=='c1' else self.queue(case_id)
            self.assertEqual(active['stage'],'expedited')
            if case_id=='c1':self.assertEqual([self.verify(active)['model'],self.verify(active)['effort']],['gpt-6-astra','low']);self.release(active)
    def test_plain_expedite_rejects_speed_questions_negation_conditions_and_quoted_material(self):
        for statement in ('c1 快一点','c1 支持加急吗','c1不要加急','如果c1加急','c1 原文引用加急','c11加急'):
            with self.subTest(statement=statement):
                with self.assertRaises(ValueError):self.call('expedite','c1',authorization=self.natural_authorization('c1',statement))
        for actual in ('```text\nc1加急\n```','材料引用：\nc1加急','> c1加急'):
            with self.subTest(actual=actual):
                with self.assertRaisesRegex(ValueError,'real user message'):self.call('expedite','c1',authorization=self.natural_authorization('c1','c1加急',message_text=actual))
    def test_implicit_batch_expedite_needs_frozen_latest_real_batch_context(self):
        with self.assertRaisesRegex(ValueError,'current-batch context'):self.call('expedite','c1',authorization=self.natural_authorization('c1','这批加急','modern'))
        log=self.sessions/'c2-natural.jsonl';statement='当前批次 modern';event={'type':'response_item','payload':{'type':'message','role':'user','content':[{'type':'input_text','text':statement}]}}
        log.write_text(json.dumps(event)+'\n',encoding='utf-8')
        context={'root':str(self.pool),'batch_id':'modern','manifest_sha256':digest(self.pool/'modern/manifest.json'),'statement':statement,'user_message_sha256':hashlib.sha256(statement.encode()).hexdigest()}
        self.call('expedite','c2',authorization=self.natural_authorization('c2','这批加急','modern',context));self.assertEqual(self.queue('c2')['stage'],'expedited')
        later=self.sessions/'c3-natural.jsonl';other='当前批次 other-batch';other_event={'type':'response_item','payload':{'type':'message','role':'user','content':[{'type':'input_text','text':other}]}}
        later.write_text(json.dumps(event)+'\n'+json.dumps(other_event)+'\n',encoding='utf-8')
        with self.assertRaisesRegex(ValueError,'real user message'):self.call('expedite','c3',authorization=self.natural_authorization('c3','这批加急','modern',context))
        invalid={**context,'manifest_sha256':'wrong'}
        with self.assertRaisesRegex(ValueError,'registered batch context'):self.call('expedite','c4',authorization=self.natural_authorization('c4','这批加急','modern',invalid))
        conflict='当前批次 other；modern 不处理';conflict_event={'type':'response_item','payload':{'type':'message','role':'user','content':[{'type':'input_text','text':conflict}]}}
        (self.sessions/'c5-natural.jsonl').write_text(json.dumps(conflict_event)+'\n',encoding='utf-8');conflict_context={**context,'statement':conflict,'user_message_sha256':hashlib.sha256(conflict.encode()).hexdigest()}
        with self.assertRaisesRegex(ValueError,'real user message'):self.call('expedite','c5',authorization=self.natural_authorization('c5','这批加急','modern',conflict_context))
    def test_whole_conditional_or_material_message_cannot_be_trimmed_to_a_command(self):
        for statement in ('如果老板批准，c1加急','材料：c1加急','c1加急，前提是批准','待老板批准；c1 使用原加急模式'):
            with self.subTest(statement=statement):
                with self.assertRaisesRegex(ValueError,'whole simple positive'):self.call('expedite','c1',authorization=self.natural_authorization('c1',statement))
        for actual in ('如果老板批准，c1加急','材料：c1加急','如果老板批准\nc1加急','其他要求\nc1加急'):
            with self.subTest(actual=actual):
                with self.assertRaisesRegex(ValueError,'real user message'):self.call('expedite','c1',authorization=self.natural_authorization('c1','c1加急',message_text=actual))
    def test_cross_batch_same_case_scope_requires_actual_matching_context_or_qualification(self):
        work=self.root/'other-work';work.mkdir();source=work/'source.docx';source.write_bytes(b'other batch source')
        write_json(work/'.product-v2/run.json',{'workspace':str(work),'run_id':'other-run','title':'其他批唯一业务'})
        cases=self.root/'other-cases.json';write_json(cases,{'cases':[{'case_id':'c1','workspace':str(work),'source_docx':str(source),'source_sha256':digest(source)}]})
        batch.register(self.pool,'other',cases,'isolated second batch authorization',4,2);batch.claim(self.pool,'other',203)
        call=lambda action,**kw:batch.mutate(self.pool,'other',203,action,'c1',**kw)
        with self.assertRaisesRegex(ValueError,'Ambiguous case authorization'):self.call('expedite','c1',authorization=self.natural_authorization('c1','c1加急'))
        context='当前批次 modern';event={'type':'response_item','payload':{'type':'message','role':'user','content':[{'type':'input_text','text':context}]}}
        (self.sessions/'c1-natural.jsonl').write_text(json.dumps(event)+'\n',encoding='utf-8')
        path=self.natural_authorization('c1','c1加急');self.call('expedite','c1',authorization=path)
        self.assertEqual(read_json(self.pool/'modern/state.json')['cases']['c1']['expedited_authorization']['verified']['batch_binding']['batch_id'],'modern')
        record=read_json(path);record.update(workspace=str(work),run_id='other-run');retargeted=self.root/'retargeted-other.json';write_json(retargeted,record)
        with self.assertRaisesRegex(ValueError,'matching current-batch context'):call('expedite',authorization=retargeted)
        self.assertNotIn('expedited_authorization',read_json(self.pool/'other/state.json')['cases']['c1'])
        for scope,statement in (('other/c1','other/c1加急'),('其他批唯一业务','其他批唯一业务 使用原加急模式')):
            log=self.sessions/(scope.replace('/','-')+'.jsonl');message={'type':'response_item','payload':{'type':'message','role':'user','content':[{'type':'input_text','text':statement}]}}
            log.write_text(json.dumps(message)+'\n',encoding='utf-8');record.update(scope_name=scope,statement=statement,session_log=str(log),user_message_sha256=hashlib.sha256(statement.encode()).hexdigest());write_json(retargeted,record)
            call('expedite',authorization=retargeted)
            self.assertEqual(read_json(self.pool/'other/state.json')['cases']['c1']['priority'],10)
    def test_bare_case_command_cannot_ignore_an_existing_different_batch_context(self):
        context='当前批次 other';event={'type':'response_item','payload':{'type':'message','role':'user','content':[{'type':'input_text','text':context}]}}
        (self.sessions/'c1-natural.jsonl').write_text(json.dumps(event)+'\n',encoding='utf-8')
        with self.assertRaisesRegex(ValueError,'matching current-batch context'):self.call('expedite','c1',authorization=self.natural_authorization('c1','c1加急'))
        self.call('expedite','c1',authorization=self.natural_authorization('c1','modern/c1加急','modern/c1'))
        self.assertEqual(self.queue('c1')['stage'],'expedited')

class AdmittedModelContractTests(unittest.TestCase):
    def setUp(self):
        self.fixture=contract_fixtures.ContractTests();self.fixture.setUp();self.root=self.fixture.root;self.work=self.fixture.work;self.pool=self.root/'pool'
        self.identity_patch=patch('batch_control.identity',side_effect=lambda pid:{'pid':pid,'created_ticks':pid+1000});self.identity_patch.start()
        self.session_patch=patch('contracts.SESSION_ROOT',self.fixture.sessions);self.session_patch.start()
        cases=self.root/'cases.json';write_json(cases,{'cases':[{'case_id':'case','workspace':str(self.work),'source_docx':str(self.fixture.source),'source_sha256':digest(self.fixture.source)}]})
        batch.register(self.pool,'contracts',cases,'isolated model contract authorization',4,2);batch.claim(self.pool,'contracts',202)
        checks=[]
        for kind in ('workspace_write','read_only','browser','word_render'):
            log=self.root/(kind+'.log');log.write_text('isolated preflight fixture');checks.append({'kind':kind,'command':'fixture','exit_code':0,'log':str(log),'sha256':digest(log)})
        preflight=self.root/'preflight.json';write_json(preflight,{'status':'ready','zero_model_calls':0,'checks':checks});self.call('preflight',value=preflight)
    def tearDown(self):self.session_patch.stop();self.identity_patch.stop();self.fixture.tearDown()
    def call(self,action,case_id=None,**kw):return batch.mutate(self.pool,'contracts',202,action,case_id,**kw)
    def grant(self):
        self.fixture.expedited_fixture();path=self.root/'authorization.json';write_json(path,self.fixture.dispatch['expedited_authorization']);self.call('expedite','case',authorization=path);return path
    def admit(self,expedited=False):
        if expedited:self.grant()
        ticket=self.call('queue','case',stage='review');active=self.call('acquire',token=ticket['token']);return active
    def bind(self,active,verify=True):
        ref=active['review_admission'];self.fixture.dispatch['stages']['review']['review_admission']=ref;self.fixture.proof['review_admission']=ref
        permit=self.call('verify-review','case',token=active['token'],value=self.work) if verify else None
        if permit:
            self.fixture.dispatch['stages']['review']['review_dispatch_permit']=permit['review_dispatch_permit'];self.fixture.proof['review_dispatch_permit']=permit['review_dispatch_permit']
        message=active['token']+' '+self.fixture.run['run_id']+' '+str(self.work)+((' '+permit['dispatch_nonce']) if permit else '')
        for event in self.fixture.events:
            payload=event['payload']
            if payload.get('type')=='function_call' and payload.get('call_id')=='review':
                arguments=json.loads(payload['arguments']);arguments['message']=message;payload['arguments']=json.dumps(arguments)
        self.fixture.save_dispatch();self.fixture.save_proof();return permit
    def test_admitted_astra_low_actual_dispatch_and_current_proof_accept(self):
        active=self.admit(True);self.bind(active);verified=self.fixture.verify_models()
        self.assertEqual(verified['review_admission']['model'],'gpt-6-astra');self.assertEqual(verified['review_admission']['effort'],'low')
    def test_new_contract_cannot_omit_admission_or_paid_before_dispatch_permit(self):
        active=self.admit()
        with self.assertRaisesRegex(ValueError,'immutable acquired admission'):self.fixture.verify_models()
        self.bind(active,verify=False)
        with self.assertRaisesRegex(ValueError,'verification permit'):self.fixture.verify_models()
    def test_actual_dispatch_must_contain_the_verified_nonce_and_scope(self):
        active=self.admit();permit=self.bind(active)
        for event in self.fixture.events:
            payload=event['payload']
            if payload.get('type')=='function_call' and payload.get('call_id')=='review':
                arguments=json.loads(payload['arguments']);arguments['message']=active['token']+' '+self.fixture.run['run_id']+' '+str(self.work);payload['arguments']=json.dumps(arguments)
        self.fixture.save_dispatch()
        with self.assertRaisesRegex(ValueError,'verified permit nonce'):self.fixture.verify_models()
    def test_changed_admission_or_dispatch_permit_hash_cannot_sign_pass(self):
        active=self.admit();permit=self.bind(active);path=Path(permit['review_dispatch_permit']['path']);write_json(path,{})
        with self.assertRaisesRegex(ValueError,'dispatch permit changed'):self.fixture.verify_models()
    def test_proof_must_bind_same_permit_and_actual_route(self):
        active=self.admit();self.bind(active);self.fixture.proof['review_dispatch_permit']={'path':'different','sha256':'different'};self.fixture.save_proof()
        with self.assertRaisesRegex(ValueError,'verification permit'):self.fixture.verify_models()
    def test_active_ordinary_review_remains_valid_after_case_is_expedited(self):
        active=self.admit();self.bind(active);record=copy.deepcopy(self.fixture.dispatch['stages']['review']);before=Path(active['review_admission']['path']).read_bytes()
        statement='case 使用原加急模式';event={'type':'response_item','payload':{'type':'message','role':'user','content':[{'type':'input_text','text':statement}]}}
        self.fixture.events.append(event);self.fixture.save_dispatch()
        path=self.root/'later-authorization.json';write_json(path,{'run_id':self.fixture.run['run_id'],'workspace':str(self.work),'scope_name':'case','statement':statement,'session_log':str(self.fixture.parent_log),'user_message_sha256':hashlib.sha256(statement.encode()).hexdigest()})
        self.call('expedite','case',authorization=path)
        self.assertEqual(self.fixture.dispatch['stages']['review'],record);self.assertEqual(Path(active['review_admission']['path']).read_bytes(),before)
        self.assertEqual(self.fixture.verify_models()['review_admission']['model'],'gpt-6.1-sol')

if __name__=='__main__':unittest.main()
