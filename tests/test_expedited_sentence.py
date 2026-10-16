"""Isolated authorization boundaries; no paid models, case builds or acceptance."""
import hashlib
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
import batch_control as batch
import contracts
from common import digest,read_json,write_json


class ExpeditedSentenceTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name)
        self.pool=self.root/'batches';self.sessions=self.root/'sessions';self.sessions.mkdir()
        self.session_patch=patch('contracts.SESSION_ROOT',self.sessions);self.session_patch.start()
        self.input=self.root/'当前输入材料';self.input.mkdir()
        self.title='设备闭环控制方法';self.name='技术项目说明书'+self.title
        self.cases=[]
        for case_id,title,name in (('first',self.title,self.name),('second','其他设备方法','其他设备说明书')):
            work=self.root/case_id;work.mkdir();source=self.input/(name+'.docx');source.write_bytes(case_id.encode())
            write_json(work/'.product-v2/run.json',{'run_id':'run-'+case_id,'workspace':str(work),'title':title,
                       'source_docx':str(source),'source_docx_sha256':digest(source)})
            self.cases.append({'case_id':case_id,'title':title,'workspace':str(work),'source_docx':str(source),
                               'source_sha256':digest(source),'authorization_scope_names':[name]})
        cases=self.root/'cases.json';write_json(cases,{'cases':self.cases})
        self.manifest=batch.register(self.pool,'registered-batch',cases,'fixture real user registration',4,2)
        self.work=Path(self.cases[0]['workspace']);self.source=Path(self.cases[0]['source_docx'])

    def tearDown(self):self.session_patch.stop();self.temp.cleanup()

    def sentence(self,name=None,label=None,action='做',deadline='，并且最好17：00之前要可以做好'):
        return (name or self.name)+'，这件是我新加到'+(label or self.input.name)+'批次的，这件需要加急'+action+deadline

    def authorization(self,statement=None,scope=None,actual=None,role='user',meta=None,prior=None,kind='response_item'):
        statement=self.sentence() if statement is None else statement;actual=statement if actual is None else actual
        meta=meta or {'id':'fixture-parent','thread_source':'user','source':'vscode'}
        events=[{'type':'session_meta','payload':meta}]
        if prior:events.extend(prior)
        events.append({'type':kind,'payload':{'type':'message','role':role,'content':[{'type':'input_text','text':actual}]}})
        path=self.sessions/'parent.jsonl';path.write_text(''.join(json.dumps(e,ensure_ascii=False)+'\n' for e in events),encoding='utf-8')
        return {'run_id':'run-first','workspace':str(self.work),'scope_name':scope or self.name,'statement':statement,
                'session_log':str(path),'user_message_sha256':hashlib.sha256(actual.encode()).hexdigest()}

    def verify(self,record,work=None,case=None):
        batch.check_authorization_scope(self.manifest,case or self.manifest['cases'][0],record)
        return contracts.expedited_authorization(work or self.work,record)

    def test_whole_sentence_and_raw_trailing_newline_hash(self):
        statement=self.sentence();record=self.authorization(actual=statement+'\n')
        result=self.verify(record)
        self.assertEqual(result['user_message_sha256'],hashlib.sha256((statement+'\n').encode()).hexdigest())
        self.assertEqual(result['batch_binding']['case_id'],'first')
        self.assertNotIn('scope_context_user_message_sha256',result)

    def test_frozen_title_alias_and_complete_deadline_or_no_deadline(self):
        for name in (self.name,self.title):
            for action in ('做','处理'):
                for deadline in ('','，00:00之前完成','，最好23：59之前做好','，并且最好今天9:05之前要可以完成'):
                    with self.subTest(name=name,action=action,deadline=deadline):
                        self.verify(self.authorization(self.sentence(name=name,action=action,deadline=deadline),scope=name))

    def test_invalid_clock_or_partial_deadline_rejects(self):
        for deadline in ('，24:00之前完成','，23:60之前完成','，-1:00之前完成','，17:0之前完成',
                         '，17:00之前','，最好17:00','，17:00之后完成','，١:00之前完成','，17:00之前完成，视情况而定'):
            with self.subTest(deadline=deadline),self.assertRaises(ValueError):
                self.verify(self.authorization(self.sentence(deadline=deadline)))

    def test_wrong_batch_alias_case_and_record_metadata_cannot_supply_batch(self):
        for text,scope in ((self.sentence(label='其他输入材料'),self.name),
                           (self.sentence(name='未冻结案件名'),'未冻结案件名'),
                           (self.sentence(name='其他设备说明书'),'其他设备说明书'),
                           (self.sentence(name='first'),'first')):
            with self.subTest(text=text),self.assertRaises(ValueError):self.verify(self.authorization(text,scope))
        record=self.authorization(self.sentence(label='伪造批目录'));record['input_batch']='伪造批目录'
        with self.assertRaises(ValueError):self.verify(record)

    def test_negation_conditions_material_quotation_and_extra_lines_reject(self):
        text=self.sentence()
        for actual in ('如果老板批准，'+text,'材料：'+text,'引用：'+text,'> '+text,'“'+text+'”','"'+text+'"',
                       text+'，但不要加急',text+'，前提是批准','其他要求\n'+text,'```text\n'+text+'\n```',
                       '转发：'+text,'assistant: '+text):
            with self.subTest(actual=actual):
                with self.assertRaises(ValueError):self.verify(self.authorization(actual))
                with self.assertRaises(ValueError):self.verify(self.authorization(text,actual=actual))

    def test_only_direct_actual_parent_user_message_accepts_new_sentence(self):
        for role in ('assistant','developer','system','tool'):
            with self.subTest(role=role),self.assertRaises(ValueError):self.verify(self.authorization(role=role))
        for meta in ({'id':'child','thread_source':'user','source':{'subagent':{'parent_thread_id':'p'}}},
                     {'id':'fixture-child','thread_source':'user','source':'vscode','parent_thread_id':'actual-parent'},
                     {'id':'child','thread_source':'subagent','source':'vscode'},
                     {'id':'fake','source':'vscode'},
                     {'id':'fake','thread_source':'user','source':'assistant'},
                     {'id':'fake','thread_source':'user','source':'forwarded'},
                     {'id':'fake','thread_source':'user','source':'subagent'}):
            with self.subTest(meta=meta),self.assertRaises(ValueError):self.verify(self.authorization(meta=meta))
        with self.assertRaises(ValueError):self.verify(self.authorization(kind='event_msg'))

    def test_wrong_run_workspace_hash_and_registered_source_reject(self):
        for key,value in (('run_id','other-run'),('workspace',str(self.root/'second')),('user_message_sha256','0'*64)):
            with self.subTest(key=key):
                record=self.authorization();record[key]=value
                with self.assertRaises(ValueError):self.verify(record)
        record=self.authorization();record.update(workspace=str(self.root/'second'),run_id='run-second')
        with self.assertRaises(ValueError):contracts.expedited_authorization(self.root/'second',record)
        self.source.write_bytes(b'changed source')
        with self.assertRaises(ValueError):self.verify(self.authorization())

    def test_changed_run_source_path_or_hash_reject(self):
        path=self.work/'.product-v2/run.json';original=read_json(path)
        for key,value in (('workspace',self.cases[1]['workspace']),('source_docx',self.cases[1]['source_docx']),('source_docx_sha256','0'*64)):
            with self.subTest(key=key):
                write_json(path,{**original,key:value})
                with self.assertRaises(ValueError):self.verify(self.authorization())
        write_json(path,original)

    def test_new_explicit_batch_sentence_overrides_unrelated_old_batch_context(self):
        for context in ('当前批次：无关批','当前批次other；某批不处理'):
            prior=[{'type':'response_item','payload':{'type':'message','role':'user','content':[{'text':context}]}}]
            result=self.verify(self.authorization(prior=prior));self.assertNotIn('scope_context_user_message_sha256',result)
        prior=[{'type':'response_item','payload':{'type':'message','role':'user','content':[{'text':'当前批次：无关批'}]}}]
        with self.assertRaisesRegex(ValueError,'matching current-batch context'):
            self.verify(self.authorization('first加急','first',prior=prior))
        self.verify(self.authorization('registered-batch/first加急','registered-batch/first',prior=prior))

    def test_same_input_batch_and_name_in_another_registered_batch_is_ambiguous(self):
        work=self.root/'duplicate';work.mkdir();write_json(work/'.product-v2/run.json',
            {'workspace':str(work),'run_id':'duplicate-run','title':self.title})
        cases=self.root/'duplicate.json';write_json(cases,{'cases':[{**self.cases[0],'workspace':str(work),'case_id':'duplicate'}]})
        batch.register(self.pool,'other-batch',cases,'fixture duplicate scope',4,2)
        with self.assertRaisesRegex(ValueError,'ambiguous across registered batches'):self.verify(self.authorization())

    def test_same_alias_with_other_input_batch_remains_explicitly_disambiguated(self):
        work=self.root/'other-case';work.mkdir();inputs=self.root/'other-inputs';inputs.mkdir()
        source=inputs/self.source.name;source.write_bytes(b'other source')
        write_json(work/'.product-v2/run.json',{'workspace':str(work),'run_id':'other-run','title':self.title,
                   'source_docx':str(source),'source_docx_sha256':digest(source)})
        cases=self.root/'other.json';write_json(cases,{'cases':[{**self.cases[0],'workspace':str(work),
                   'source_docx':str(source),'source_sha256':digest(source)}]})
        batch.register(self.pool,'other-batch',cases,'fixture other input batch',4,2)
        record=self.authorization();self.verify(record);record.update(workspace=str(work),run_id='other-run')
        with self.assertRaises(ValueError):contracts.expedited_authorization(work,record)

    def test_old_short_commands_implicit_context_and_question_card_stay_supported(self):
        for text,scope in (('first加急','first'),('加急first','first'),('registered-batch 这批加急','registered-batch')):
            with self.subTest(text=text):self.verify(self.authorization(text,scope))
        context='当前批次：registered-batch'
        prior=[{'type':'response_item','payload':{'type':'message','role':'user','content':[{'text':context}]}}]
        record=self.authorization('这批加急','registered-batch',prior=prior)
        record['scope_context']={'root':str(self.pool),'batch_id':'registered-batch',
            'manifest_sha256':digest(self.pool/'registered-batch/manifest.json'),'statement':context,
            'user_message_sha256':hashlib.sha256(context.encode()).hexdigest()}
        self.verify(record)
        with self.assertRaises(ValueError):self.verify(self.authorization('这批加急','registered-batch'))
        question='请选择当前案件审核方式'
        request={'type':'response_item','payload':{'type':'function_call','name':'request_user_input_async','call_id':'question',
                  'arguments':json.dumps({'questions':[{'title':question}]})}}
        answer='registered-batch/first加急'
        def card(text):return '<send_user_message_question_reply>'+json.dumps([{'questionItemId':'["request_user_input_async","question",0]',
                 'question':question,'answer':text}],ensure_ascii=False)+'</send_user_message_question_reply>'
        self.verify(self.authorization(answer,'registered-batch/first',actual=card(answer),prior=[request]))
        with self.assertRaises(ValueError):self.verify(self.authorization(actual=card(self.sentence()),prior=[request]))


if __name__=='__main__':unittest.main()
