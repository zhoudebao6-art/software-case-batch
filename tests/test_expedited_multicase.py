"""Finite whole-message multi-case authorization fixtures; never case execution."""
import json
import hashlib
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
import batch_control as batch
import contracts
from common import digest,read_json,write_json


class MultiCaseTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name)
        self.pool=self.root/'pool';self.input=self.root/'输入材料批';self.input.mkdir()
        self.sessions=self.root/'sessions';self.sessions.mkdir()
        self.session_patch=patch('contracts.SESSION_ROOT',self.sessions);self.session_patch.start()
        self.titles=['设备转运识别方法','部件磨损分析方法','料流控制方法','未列举的其他方法'];self.cases=[]
        for index,title in enumerate(self.titles):
            work=self.root/str(index);work.mkdir();source=self.input/('说明书'+title+'.docx');source.write_bytes(title.encode())
            write_json(work/'.product-v2/run.json',{'run_id':'run-'+str(index),'workspace':str(work),'title':title,
                'source_docx':str(source),'source_docx_sha256':digest(source)})
            self.cases.append({'case_id':str(index),'title':title,'workspace':str(work),'source_docx':str(source),'source_sha256':digest(source)})
        path=self.root/'cases.json';write_json(path,{'cases':self.cases})
        self.manifest=batch.register(self.pool,'registered-batch',path,'fixture genuine user register',4,2)

    def tearDown(self):self.session_patch.stop();self.temp.cleanup()

    def statement(self,names=None,count='三',clock='五点',label=None):
        names=names or self.titles[:3]
        return '\n'.join(names)+'，这'+count+'件需要加急出一下，同样需要'+clock+'之前，属于'+(label or self.input.name)+'的'

    def authorization(self,statement=None,index=0,actual=None,meta=None,role='user'):
        statement=self.statement() if statement is None else statement;actual=statement if actual is None else actual
        events=[{'type':'session_meta','payload':meta or {'id':'parent','source':'vscode','thread_source':'user'}},
                {'type':'response_item','payload':{'type':'message','role':role,'content':[{'type':'input_text','text':actual}]}}]
        log=self.sessions/'parent.jsonl';log.write_text(''.join(json.dumps(e,ensure_ascii=False)+'\n' for e in events),encoding='utf-8')
        record={'run_id':'run-'+str(index),'workspace':self.cases[index]['workspace'],'scope_name':self.titles[index],
                'statement':statement,'session_log':str(log),'user_message_sha256':hashlib.sha256(actual.encode()).hexdigest()}
        return record

    def verify(self,record):
        return contracts.expedited_authorization(record['workspace'],record)

    def test_complete_message_each_named_case_and_raw_whitespace_hash(self):
        statement=self.statement(names=[self.titles[0],self.titles[1]+' ',self.titles[2]])
        for index in range(3):
            with self.subTest(index=index):
                r=self.authorization(statement,index=index,actual=statement+'\n');v=self.verify(r)
                self.assertEqual(v['batch_binding']['case_id'],str(index));self.assertEqual(v['user_message_sha256'],r['user_message_sha256'])
        with self.assertRaises(ValueError):self.verify(self.authorization(statement,index=3))
        for clock in ('17:00','23：59','十二点','0:00'):
            with self.subTest(clock=clock):self.verify(self.authorization(self.statement(clock=clock)))

    def test_wrong_count_duplicate_unknown_id_and_wrong_input_batch_reject(self):
        for text in (self.statement(count='二'),self.statement(count='四'),self.statement(names=self.titles[:2]+[self.titles[0]]),
                     self.statement(names=self.titles[:2]+['未知方法']),self.statement(names=['0']+self.titles[1:3]),
                     self.statement(label='其他输入材料批'),self.statement(clock='24:00'),self.statement(clock='17:60'),
                     self.statement(clock='十三点'),self.statement(clock='17:0')):
            with self.subTest(text=text),self.assertRaises(ValueError):self.verify(self.authorization(text))

    def test_conditions_negation_material_quotes_extra_lines_and_snippets_reject(self):
        text=self.statement()
        for actual in ('如果领导批准，'+text,text+'，但不要加急','材料：\n'+text,'引用：'+text,
                       '> '+text,'“'+text+'”','```text\n'+text+'\n```','其他条件\n'+text,text+'\n另一个命令',
                       text.replace('需要加急','不要加急'),text.replace('同样需要','如果需要')):
            with self.subTest(actual=actual):
                with self.assertRaises(ValueError):self.verify(self.authorization(actual))
                with self.assertRaises(ValueError):self.verify(self.authorization(text,actual=actual))

    def test_false_parent_roles_hash_and_spliced_message_reject(self):
        for meta in ({'id':'child','thread_source':'user','source':'vscode','parent_thread_id':'parent'},
                     {'id':'child','thread_source':'user','source':{'subagent':{'parent_thread_id':'parent'}}},
                     {'id':'fake','thread_source':'user','source':'forwarded'},
                     {'id':'fake','thread_source':'subagent','source':'vscode'}):
            with self.subTest(meta=meta),self.assertRaises(ValueError):self.verify(self.authorization(meta=meta))
        for role in ('assistant','tool','developer'):
            with self.subTest(role=role),self.assertRaises(ValueError):self.verify(self.authorization(role=role))
        r=self.authorization();r['user_message_sha256']='0'*64
        with self.assertRaises(ValueError):self.verify(r)
        r=self.authorization();log=Path(r['session_log']);events=[json.loads(line) for line in log.read_text(encoding='utf-8').splitlines()]
        parts=r['statement'].split('\n',1);events[1]['payload']['content']=[{'type':'input_text','text':part} for part in parts]
        log.write_text(''.join(json.dumps(e,ensure_ascii=False)+'\n' for e in events),encoding='utf-8')
        with self.assertRaises(ValueError):self.verify(r)
        events[1]['payload']['content']=[{'type':'input_text','text':parts[0]}]
        events.append({'type':'response_item','payload':{'type':'message','role':'user','content':[{'type':'input_text','text':parts[1]}]}})
        log.write_text(''.join(json.dumps(e,ensure_ascii=False)+'\n' for e in events),encoding='utf-8')
        with self.assertRaises(ValueError):self.verify(r)

    def test_every_listed_run_source_is_checked_and_run_workspace_cannot_retarget(self):
        r=self.authorization(index=1);r['scope_name']=self.titles[0]
        with self.assertRaisesRegex(ValueError,'Listed expedited authorization'):self.verify(r)
        for key,value in (('run_id','wrong-run'),('workspace',self.cases[3]['workspace'])):
            with self.subTest(key=key):
                r=self.authorization();r[key]=value
                with self.assertRaises(ValueError):self.verify(r)
        source=Path(self.cases[2]['source_docx']);source.write_bytes(b'changed non-target source')
        with self.assertRaisesRegex(ValueError,'All listed expedited'):self.verify(self.authorization())

    def test_same_source_batch_duplicate_name_across_registered_batches_reject(self):
        work=self.root/'duplicate';work.mkdir();write_json(work/'.product-v2/run.json',{'workspace':str(work),'run_id':'duplicate','title':self.titles[1]})
        path=self.root/'duplicate.json';write_json(path,{'cases':[{**self.cases[1],'workspace':str(work),'case_id':'duplicate'}]})
        batch.register(self.pool,'other-batch',path,'fixture other batch',4,2)
        with self.assertRaisesRegex(ValueError,'ambiguous across registered batches'):self.verify(self.authorization())


if __name__=='__main__':unittest.main()
