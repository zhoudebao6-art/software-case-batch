"""Desktop root omission regression; all mutations use isolated fixture stores.

The metadata shape matches a read-only Desktop 0.160.1 observation. These logs
are test fixtures, not production/session evidence. No live binding is written.
"""
import copy
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import unittest
from unittest.mock import patch
import test_scheduler_adaptive as helpers
import batch_control as batch
import scheduler_policy as scheduler
from common import digest, read_json, write_json


class DesktopControllerTests(unittest.TestCase):
    setUp = helpers.AdaptiveSchedulerTests.setUp
    tearDown = helpers.AdaptiveSchedulerTests.tearDown
    create = helpers.AdaptiveSchedulerTests.create
    call = helpers.AdaptiveSchedulerTests.call
    request = helpers.AdaptiveSchedulerTests.request
    bind = helpers.AdaptiveSchedulerTests.bind
    runtime = helpers.AdaptiveSchedulerTests.runtime
    configure = helpers.AdaptiveSchedulerTests.configure
    queue = helpers.AdaptiveSchedulerTests.queue
    acquire = helpers.AdaptiveSchedulerTests.acquire
    fill = helpers.AdaptiveSchedulerTests.fill

    def desktop_request(self):
        self.create('a')
        request = self.request('a', 'A')
        self.runtime('a', 'A', 4)
        _, log = self.logs['A']
        rows = self.rows(log)
        meta = rows[0]['payload']
        meta.pop('thread_source')
        meta.update(source='vscode', originator='Codex Desktop', cli_version='0.160.1',
                    cwd=str(self.root), history_mode='persisted')
        self.write_rows(log, rows)
        return request, log

    @staticmethod
    def rows(log):
        return [json.loads(line) for line in log.read_text(encoding='utf-8').splitlines()]

    @staticmethod
    def write_rows(log, rows):
        log.write_text(''.join(json.dumps(row) + '\n' for row in rows), encoding='utf-8')

    def assert_rejected(self, request):
        before = digest(self.pool/'scheduler-config.json')
        with self.assertRaises((ValueError, OSError)):
            self.call('a', 'bind-controller', value=request, authorization='fixture scope')
        self.assertEqual(before, digest(self.pool/'scheduler-config.json'))

    def test_observed_desktop_root_binds_and_four_slots_admit_only_three_workers(self):
        request, log = self.desktop_request()
        before = digest(self.pool/'a/manifest.json')
        self.call('a', 'bind-controller', value=request, authorization='fixture desktop root')
        self.configure(capacity_scope=scheduler.RUNTIME_CAPACITY_SCOPE)
        settings = scheduler.config(self.pool)
        binding = scheduler.verified_binding(self.pool, 'a', settings)
        self.assertEqual(binding['proof']['meta_sha256'], hashlib.sha256(log.read_bytes().splitlines(keepends=True)[0]).hexdigest())
        self.assertEqual(binding['owner'], {'pid':101, 'created_ticks':1101})
        self.assertEqual(binding['runtime_capacity']['worker_capacity'], 3)
        self.fill('a', range(3))
        self.assertFalse(self.acquire(self.queue('a', 3))['acquired'])
        self.assertEqual(before, digest(self.pool/'a/manifest.json'))

    def test_explicit_thread_source_never_uses_omission_compatibility(self):
        request, log = self.desktop_request(); original = self.rows(log)
        for value in (None, 'unknown', 'subagent', '', {}, []):
            with self.subTest(value=value):
                rows = copy.deepcopy(original); rows[0]['payload']['thread_source'] = value
                self.write_rows(log, rows); self.assert_rejected(request)

    def test_missing_or_forged_desktop_provenance_and_child_markers_are_rejected(self):
        request, log = self.desktop_request(); original = self.rows(log)
        changes = [{'source':v} for v in (None,'cli','exec','app-server','subagent',{}, {'subagent':{'thread_spawn':{}}})]
        changes += [{'originator':v} for v in (None,'codex_cli_rs','Codex Desktop copy')]
        changes += [{'cli_version':v} for v in (None,'0.160.0','0.160.2')]
        changes += [{key:value} for key in ('parent_thread_id','parent_session_id','parent_id','parent','subagent','thread_spawn','agent_path','agent_id') for value in (None,'child',{})]
        changes += [{'session_id':'foreign'}, {'id':'foreign'}]
        for update in changes:
            with self.subTest(update=update):
                rows = copy.deepcopy(original); rows[0]['payload'].update(update)
                self.write_rows(log, rows); self.assert_rejected(request)
        for key in ('source','originator','cli_version'):
            with self.subTest(missing=key):
                rows=copy.deepcopy(original); rows[0]['payload'].pop(key)
                self.write_rows(log,rows); self.assert_rejected(request)

    def test_path_filename_uuid_and_meta_type_remain_bound(self):
        request, log = self.desktop_request(); original=read_json(request)
        for name in ('foreign.jsonl', 'rollout-00000000-0000-0000-0000-000000000000.jsonl'):
            copy_log=self.sessions/name; copy_log.write_bytes(log.read_bytes())
            write_json(request,{**original,'session_log':str(copy_log)}); self.assert_rejected(request)
        outside=self.root/log.name; outside.write_bytes(log.read_bytes())
        write_json(request,{**original,'session_log':str(outside)}); self.assert_rejected(request)
        write_json(request,{**original,'session_id':'not-a-uuid'}); self.assert_rejected(request)
        write_json(request,original); rows=self.rows(log); rows[0]['type']='response_item'
        self.write_rows(log,rows); self.assert_rejected(request)

    def test_missing_failed_foreign_quoted_or_printed_commands_cannot_bind(self):
        request, log = self.desktop_request(); original=self.rows(log)
        for fault in ('missing','batch','root','pid','thread','status','exit','error','empty','quoted','printed'):
            with self.subTest(fault=fault):
                rows=copy.deepcopy(original)
                for index,row in enumerate(rows):
                    if row.get('type')!='event_msg':continue
                    p=row['payload']; item=p['item']; command=item['command'][-1]
                    if fault=='missing': rows[index]={'type':'ignored'}
                    if fault=='batch':item['command'][-1]=command.replace("--batch-id 'a'", "--batch-id 'foreign'")
                    if fault=='root':item['command'][-1]=command.replace(str(self.pool),str(self.root/'foreign'))
                    if fault=='pid':item['command'][-1]=command.replace('--pid 101','--pid 102')
                    if fault=='thread':p['thread_id']='foreign'
                    if fault=='status':item['status']='failed'
                    if fault=='exit':item['exit_code']=1
                    if fault=='error':item['aggregated_output']='ERROR: failed'
                    if fault=='empty':item['aggregated_output']=''
                    if fault=='quoted':rows[index]={'type':'response_item','payload':{'type':'message','role':'user','content':[{'text':json.dumps(row)}]}}
                    if fault=='printed':item['command'][-1]='Write-Output "'+command+'"'
                self.write_rows(log,rows); self.assert_rejected(request)

    def test_platform_capacity_is_required_and_cannot_be_supplied_or_quoted(self):
        request,log=self.desktop_request();original=self.rows(log)
        for fault in ('missing','user','unmarked','zero','ambiguous'):
            with self.subTest(fault=fault):
                rows=copy.deepcopy(original)
                for index,row in enumerate(rows):
                    if scheduler.runtime_workers(row) is None:continue
                    p=row['payload']
                    if fault=='missing':rows[index]={'type':'ignored'}
                    if fault=='user':p['role']='user'
                    if fault=='unmarked':p.pop('internal_chat_message_metadata_passthrough')
                    if fault=='zero':p['content'][0]['text']=p['content'][0]['text'].replace('4','1')
                    if fault=='ambiguous':p['content']*=2
                self.write_rows(log,rows); self.assert_rejected(request)
        self.write_rows(log,original); value=read_json(request)
        for key in ('runtime_capacity','host_total_slots','model_pool_capacity','worker_capacity'):
            with self.subTest(override=key):
                write_json(request,{**value,key:99});self.assert_rejected(request)

    def test_real_owner_gate_and_frozen_hashes_remain_enforced(self):
        request,log=self.desktop_request()
        with patch('batch_control.identity',return_value={'pid':101,'created_ticks':9999}):self.assert_rejected(request)
        self.call('a','bind-controller',value=request,authorization='fixture root')
        settings=scheduler.config(self.pool)
        ref=settings['bindings']['a']; binding_path=Path(ref['path'])
        for target in (log,binding_path,self.pool/'a/manifest.json'):
            with self.subTest(target=target.name):
                old=target.read_bytes(); target.write_bytes(b' '+old)
                self.assertIsNone(scheduler.verified_binding(self.pool,'a',settings))
                target.write_bytes(old)
        self.assertIsNotNone(scheduler.verified_binding(self.pool,'a',settings))
        owner_path=self.pool/'a/owner.json'; owner=read_json(owner_path)
        write_json(owner_path,{**owner,'created_ticks':9999})
        self.assertIsNone(scheduler.verified_binding(self.pool,'a',settings))

    def test_command_and_capacity_byte_changes_invalidate_binding_without_rescan(self):
        request,log=self.desktop_request()
        self.call('a','bind-controller',value=request,authorization='fixture root')
        settings=scheduler.config(self.pool); binding=scheduler.verified_binding(self.pool,'a',settings)
        original=log.read_bytes()
        for evidence in (binding['proof'],binding['runtime_capacity']):
            changed=bytearray(original); changed[evidence['event_offset']+1]^=1;log.write_bytes(changed)
            self.assertIsNone(scheduler.verified_binding(self.pool,'a',settings));log.write_bytes(original)
        with patch('scheduler_policy.runtime_capacity',side_effect=AssertionError('no full scan during verification')):
            self.assertIsNotNone(scheduler.verified_binding(self.pool,'a',settings))

    @unittest.skipUnless(os.name=='nt' and shutil.which('pwsh'), 'real PowerShell regression requires Windows pwsh')
    def test_real_powershell_python_claim_command_matches_parser_and_owner(self):
        # Real CLI command in an isolated registered test batch. Only this test's
        # fixture session store is patched; process identity is read from Windows.
        self.create('a')
        self.identity.stop()
        owner_path=self.pool/'a/owner.json'; owner_path.unlink()
        quote=lambda value:"'"+str(value).replace("'","''")+"'"
        source='& '+quote(sys.executable)+' '+quote(Path(batch.__file__))+' claim --root '+quote(self.pool)+" --batch-id 'a' --pid "+str(os.getpid())
        command=[shutil.which('pwsh'),'-NoProfile','-NonInteractive','-Command',source]
        result=subprocess.run(command,capture_output=True,text=True,encoding='utf-8',timeout=30)
        self.assertEqual(result.returncode,0,result.stderr+result.stdout)
        owner=read_json(owner_path);self.assertEqual(owner,batch.identity(os.getpid()))
        self.assertEqual(scheduler.option(scheduler.controller_commands(command)[0],'pid'),str(os.getpid()))
        self.assertIn(str(owner['created_ticks']),result.stdout)


if __name__=='__main__':unittest.main()
