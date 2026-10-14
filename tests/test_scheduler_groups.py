"""Behavioral controller/fairness fixtures; no case/model/browser/media execution."""
import copy
import json
from pathlib import Path
import sys
import tempfile
import unittest
import uuid
from unittest.mock import patch
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import batch_control as batch
import scheduler_policy as scheduler
from common import digest, read_json, write_json


class SchedulerGroupsTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.root = Path(self.temp.name); self.pool = self.root / 'pool'
        self.sessions = self.root / 'sessions'; self.sessions.mkdir(); self.logs = {}
        self.identity = patch('batch_control.identity', side_effect=lambda pid: {'pid': pid, 'created_ticks': pid + 1000}); self.identity.start()
        self.session_root = patch('contracts.SESSION_ROOT', self.sessions); self.session_root.start()
        self.memory = patch('batch_control.memory_available_mb', return_value=24000); self.memory.start()
        self.cpu = patch('batch_control.cpu_snapshot', return_value={'logical_processors': 32, 'cpu_load_percent': 20}); self.cpu.start()
        checks = []
        for kind in ('workspace_write', 'read_only', 'browser', 'word_render'):
            log = self.root / (kind + '.log'); log.write_text('actual fixture command output')
            checks.append({'kind': kind, 'command': 'fixture ' + kind, 'exit_code': 0, 'log': str(log), 'sha256': digest(log)})
        self.preflight = self.root / 'preflight.json'; write_json(self.preflight, {'status': 'ready', 'zero_model_calls': 0, 'checks': checks})

    def tearDown(self):
        self.cpu.stop(); self.memory.stop(); self.session_root.stop(); self.identity.stop(); self.temp.cleanup()

    def call(self, name, action, case_id=None, **kwargs):
        return batch.mutate(self.pool, name, 101, action, case_id, **kwargs)

    def create(self, name, group=None, legacy=False):
        cases = []
        for index in range(12):
            work = self.root / (name + '-' + str(index)); work.mkdir(); source = work / 'source.docx'; source.write_bytes(b'source fixture')
            write_json(work / '.product-v2/run.json', {'workspace': str(work), 'run_id': name + '-' + str(index)})
            cases.append({'case_id': str(index), 'workspace': str(work), 'source_docx': str(source), 'source_sha256': digest(source)})
        path = self.root / (name + '.json'); write_json(path, {'cases': cases})
        batch.register(self.pool, name, path, 'fixture explicit user batch authorization', 4, None if legacy else 4)
        batch.claim(self.pool, name, 101); self.call(name, 'preflight', value=self.preflight)
        if group: self.bind(name, group)

    def request(self, name, group):
        if group not in self.logs:
            session_id = str(uuid.uuid4()); log = self.sessions / ('rollout-2026-10-14T11-00-00-' + session_id + '.jsonl')
            meta = {'type': 'session_meta', 'payload': {'id': session_id, 'session_id': session_id, 'thread_source': 'user', 'source': 'vscode'}}
            log.write_text(json.dumps(meta) + '\n', encoding='utf-8'); self.logs[group] = (session_id, log)
        session_id, log = self.logs[group]
        event = {'type': 'event_msg', 'payload': {'type': 'item_completed', 'thread_id': session_id, 'item': {
            'type': 'CommandExecution', 'status': 'completed', 'exit_code': 0,
            'command': ['pwsh.exe', '-Command', "python 'batch_control.py' claim --root '" + str(self.pool) + "' --batch-id '" + name + "' --pid 101"],
            'aggregated_output': json.dumps({'pid': 101, 'created_ticks': 1101})}}}
        with log.open('a', encoding='utf-8') as stream: stream.write(json.dumps(event) + '\n')
        request = self.root / (name + '-binding.json'); write_json(request, {'session_id': session_id, 'session_log': str(log)})
        return request

    def bind(self, name, group):
        return self.call(name, 'bind-controller', value=self.request(name, group), authorization='fixture current user scheduling authorization')

    def test_printed_commented_dead_or_nested_controller_commands_do_not_bind(self):
        self.create('a'); request = self.request('a', 'A'); _, log = self.logs['A']
        original = [json.loads(line) for line in log.read_text(encoding='utf-8').splitlines()]
        command = original[1]['payload']['item']['command'][-1]
        examples = [
            'Write-Output "' + command + '"', 'echo "' + command + '"', '"' + command + '"',
            '# ' + command, '<# ' + command + ' #>', 'if ($false) { ' + command + ' }',
            'function Example { ' + command + ' }', '& { Write-Output "' + command + '" }',
            "@'\n" + command + "\n'@", 'return; ' + command,
            'if ($true) { Write-Output done; return }; ' + command,
            command.replace("python '", "python'", 1),
        ]
        for source in examples:
            with self.subTest(source=source):
                events = copy.deepcopy(original); events[1]['payload']['item']['command'][-1] = source
                log.write_text(''.join(json.dumps(event) + '\n' for event in events), encoding='utf-8')
                with self.assertRaisesRegex(ValueError, 'No actual successful controller command'):
                    self.call('a', 'bind-controller', value=request, authorization='fixture negative direct-call boundary')

    def test_direct_powershell_python_calls_bind_with_literal_argument_scope(self):
        self.create('a'); request = self.request('a', 'A'); _, log = self.logs['A']
        original = [json.loads(line) for line in log.read_text(encoding='utf-8').splitlines()]
        tail = " 'D:\\tools\\batch_control.py' claim --root '" + str(self.pool) + "' --batch-id 'a' --pid 101"
        for source in ("& $env:SCB_PRO_PYTHON" + tail, "& 'D:\\tools\\python.exe'" + tail,
                       'python' + tail, ". 'Enter-Environment.ps1'; if ($LASTEXITCODE -ne 0) { throw 'failed' }; & $env:SCB_PRO_PYTHON" + tail):
            with self.subTest(source=source):
                events = copy.deepcopy(original); events[1]['payload']['item']['command'][-1] = source
                log.write_text(''.join(json.dumps(event) + '\n' for event in events), encoding='utf-8')
                self.assertIn('a', self.call('a', 'bind-controller', value=request, authorization='fixture direct-call boundary')['bindings'])

    def test_printed_first_event_does_not_hide_later_real_direct_call(self):
        self.create('a'); request = self.request('a', 'A'); _, log = self.logs['A']
        events = [json.loads(line) for line in log.read_text(encoding='utf-8').splitlines()]
        printed = copy.deepcopy(events[1]); printed['payload']['item']['command'][-1] = 'Write-Output "' + printed['payload']['item']['command'][-1] + '"'
        log.write_text(''.join(json.dumps(event) + '\n' for event in (events[0], printed, events[1])), encoding='utf-8')
        result = self.call('a', 'bind-controller', value=request, authorization='fixture later direct-call boundary')
        binding = read_json(result['bindings']['a']['path'])
        with log.open('rb') as stream: expected_offset = len(stream.readline()) + len(stream.readline())
        self.assertEqual(binding['proof']['event_offset'], expected_offset)

    def test_direct_python_argv_requires_exact_literal_options(self):
        self.create('a'); request = self.request('a', 'A'); _, log = self.logs['A']
        events = [json.loads(line) for line in log.read_text(encoding='utf-8').splitlines()]
        command = ['python.exe', 'batch_control.py', 'claim', '--root', str(self.pool), '--batch-id', 'a', '--pid', '101']
        events[1]['payload']['item']['command'] = command
        log.write_text(''.join(json.dumps(event) + '\n' for event in events), encoding='utf-8')
        self.assertIn('a', self.call('a', 'bind-controller', value=request, authorization='fixture direct argv')['bindings'])
        for invalid in (['Write-Output'] + command, command + ['--pid', '101'],
                        ['pwsh.exe', '-Command', "& '$env:SCB_PRO_PYTHON' 'batch_control.py' claim --root '" + str(self.pool) + "' --batch-id a --pid 101"]):
            with self.subTest(command=invalid):
                events[1]['payload']['item']['command'] = invalid
                log.write_text(''.join(json.dumps(event) + '\n' for event in events), encoding='utf-8')
                with self.assertRaisesRegex(ValueError, 'No actual successful controller command'):
                    self.call('a', 'bind-controller', value=request, authorization='fixture ambiguous argv')

    def test_backtick_continued_print_does_not_bind_but_later_real_event_does(self):
        self.create('a'); request = self.request('a', 'A'); _, log = self.logs['A']
        original = [json.loads(line) for line in log.read_text(encoding='utf-8').splitlines()]
        command = original[1]['payload']['item']['command'][-1]
        for newline in ('\n', '\r\n'):
            with self.subTest(newline=repr(newline)):
                printed = copy.deepcopy(original[1])
                printed['payload']['item']['command'][-1] = 'Write-Output `' + newline + command
                log.write_text(''.join(json.dumps(event) + '\n' for event in (original[0], printed)), encoding='utf-8')
                with self.assertRaisesRegex(ValueError, 'No actual successful controller command'):
                    self.call('a', 'bind-controller', value=request, authorization='fixture backtick continuation boundary')
                with log.open('rb') as stream: expected_offset = len(stream.readline()) + len(stream.readline())
                with log.open('a', encoding='utf-8') as stream: stream.write(json.dumps(original[1]) + '\n')
                result = self.call('a', 'bind-controller', value=request, authorization='fixture later actual event after backtick')
                self.assertEqual(read_json(result['bindings']['a']['path'])['proof']['event_offset'], expected_offset)

    def configure(self, name='a', mode=scheduler.CONTRACT, capacities=None):
        path = self.root / 'scheduler-request.json'; write_json(path, {'mode': mode, 'capacities': capacities or scheduler.DEFAULT_CAPACITIES})
        return self.call(name, 'configure-scheduler', value=path, authorization='fixture current user scheduling authorization')

    def queue(self, name, case_id, urgent=False, stage='build'):
        if urgent: self.call(name, 'priority', str(case_id), value=10)
        return self.call(name, 'queue', str(case_id), stage=stage)

    def acquire(self, ticket): return self.call(ticket['batch_id'], 'acquire', token=ticket['token'])
    def release(self, ticket): return self.call(ticket['batch_id'], 'release-slot', token=ticket['token'])
    def fill(self, name, indexes=range(3), urgent=False):
        result = []
        for index in indexes:
            ticket = self.queue(name, index, urgent); self.assertEqual(self.acquire(ticket)['status'], 'active'); result.append(ticket)
        return result

    def test_two_real_sessions_with_same_pid_allow_six_and_each_group_stops_at_three(self):
        self.create('a', 'A'); self.create('b', 'B'); self.configure(); self.fill('a'); self.fill('b')
        self.assertEqual(sum(q['status'] == 'active' for q in read_json(self.pool / 'queue.json')), 6)
        self.assertFalse(self.acquire(self.queue('a', 3))['acquired']); self.assertFalse(self.acquire(self.queue('b', 3))['acquired'])

    def test_two_batches_in_one_session_share_three_even_rebinding_same_session(self):
        self.create('a', 'A'); self.create('b', 'A'); self.configure(); self.fill('a', range(2)); self.fill('b', range(1))
        before = read_json(self.pool / 'queue.json'); self.bind('b', 'A'); self.assertEqual(before, read_json(self.pool / 'queue.json'))
        self.assertFalse(self.acquire(self.queue('b', 1))['acquired'])

    def test_global_build_eight_is_not_multiplied_by_group_or_batch_count(self):
        for name in ('a', 'b', 'c'): self.create(name, name)
        self.configure(); self.fill('a'); self.fill('b'); self.fill('c', range(2))
        self.assertFalse(self.acquire(self.queue('c', 2))['acquired'])

    def test_full_group_head_and_higher_priority_cannot_block_empty_group(self):
        self.create('a', 'A'); self.create('b', 'B'); self.configure(); self.fill('a')
        first = self.queue('a', 3, True); ordinary = self.queue('b', 0)
        self.assertEqual(self.acquire(ordinary)['status'], 'active'); self.assertFalse(self.acquire(first)['acquired'])

    def test_invalid_early_source_preflight_and_binding_cannot_block_valid_group(self):
        for fault in ('source', 'preflight', 'drain', 'blocked', 'owner'):
            with self.subTest(fault=fault):
                # Independent roots isolate admission history for each failure.
                self.pool = self.root / ('pool-' + fault); self.create('a' + fault, 'A' + fault); self.create('b' + fault, 'B' + fault)
                self.configure('a' + fault); head = self.queue('a' + fault, 0, True); good = self.queue('b' + fault, 0)
                target = self.pool / ('a' + fault)
                if fault == 'source': Path(read_json(target / 'manifest.json')['cases'][0]['source_docx']).write_bytes(b'changed')
                if fault == 'preflight':
                    state = read_json(target / 'state.json'); state['environment_preflight']['sha256'] = 'invalid'; write_json(target / 'state.json', state)
                if fault in {'drain', 'blocked'}:
                    state = read_json(target / 'state.json')
                    if fault == 'drain': state['drain'] = True
                    else: state['cases']['0']['phase'] = 'blocked'
                    write_json(target / 'state.json', state)
                if fault == 'owner': write_json(target / 'owner.json', {'pid': 101, 'created_ticks': -1})
                self.assertEqual(self.acquire(good)['status'], 'active')
                self.assertEqual(head['status'], 'waiting')

    def test_idle_urgent_share_is_lent_to_ordinary_until_group_full(self):
        self.create('a', 'A'); self.create('b', 'B'); self.configure(); self.fill('a'); self.fill('b')

    def test_idle_ordinary_share_is_lent_to_urgent_build_without_astra_consent(self):
        self.create('a', 'A'); self.create('b', 'B'); self.configure(); self.fill('a', urgent=True); self.fill('b', urgent=True)
        self.assertEqual(read_json(self.pool / 'a/manifest.json')['models']['build'], ['gpt-6.1-sol', 'high'])
        with self.assertRaisesRegex(ValueError, 'Unscoped'): self.queue('a', 4, stage='expedited')

    def test_continuous_urgent_and_ordinary_waiters_alternate_without_starvation(self):
        self.create('a', 'A'); self.configure()
        urgent = [self.queue('a', i, True) for i in range(6)]; ordinary = [self.queue('a', i) for i in range(6, 12)]
        order = []
        for index in range(6):
            for expected in (urgent[index], ordinary[index]):
                active = self.acquire(expected); self.assertEqual(active['status'], 'active'); order.append(active['priority']); self.release(expected)
        self.assertEqual(order, [10, 0] * 6)

    def test_class_alternation_across_stages_and_full_review_stage_lends_to_build(self):
        self.create('a', 'A'); self.create('b', 'B'); self.configure()
        urgent = self.queue('a', 0, True, 'review'); ordinary = self.queue('b', 0)
        self.assertFalse(self.acquire(ordinary)['acquired']); self.assertEqual(self.acquire(urgent)['status'], 'active')
        self.assertEqual(self.acquire(ordinary)['status'], 'active')
        self.fill('a', range(1, 3), True)  # build can borrow remaining slots
        waiting = self.queue('a', 3, True, 'review'); good = self.queue('b', 1)
        self.assertEqual(self.acquire(good)['status'], 'active'); self.assertFalse(self.acquire(waiting)['acquired'])

    def test_groups_and_batches_rotate_with_fifo_preserved_within_batch(self):
        self.create('a', 'A'); self.create('b', 'A'); self.create('c', 'C'); self.configure()
        a0 = self.queue('a', 0); a1 = self.queue('a', 1); b0 = self.queue('b', 0); c0 = self.queue('c', 0)
        self.assertEqual(self.acquire(a0)['status'], 'active'); self.release(a0)
        self.assertFalse(self.acquire(a1)['acquired']); self.assertEqual(self.acquire(c0)['status'], 'active'); self.release(c0)
        self.assertEqual(self.acquire(b0)['status'], 'active'); self.release(b0); self.assertEqual(self.acquire(a1)['status'], 'active')

    def test_ordinary_service_cannot_starve_same_groups_waiting_urgent_class(self):
        self.create('a', 'A'); self.create('b', 'B'); self.configure()
        a_urgent = [self.queue('a', index, True) for index in (0, 1)]
        b_urgent = [self.queue('b', index, True) for index in (0, 1)]
        a_ordinary = [self.queue('a', index) for index in (6, 7, 8)]
        expected = [a_urgent[0], a_ordinary[0], b_urgent[0], a_ordinary[1], a_urgent[1], a_ordinary[2]]
        for ticket in expected:
            self.assertEqual(self.acquire(ticket)['status'], 'active'); self.release(ticket)

    def test_live_binding_enable_and_rollback_preserve_active_and_frozen_permits(self):
        self.create('a'); self.create('b'); active = self.acquire(self.queue('a', 0, stage='review'))
        work = read_json(self.pool / 'a/manifest.json')['cases'][0]['workspace']
        permit = self.call('a', 'verify-review', '0', token=active['token'], value=work)
        protected = [self.pool / 'a/manifest.json', Path(work) / '.product-v2/run.json', Path(active['review_admission']['path']), Path(permit['review_dispatch_permit']['path'])]
        hashes = {str(path): digest(path) for path in protected}; original = copy.deepcopy(read_json(self.pool / 'queue.json')[0])
        self.bind('a', 'A'); self.bind('b', 'B'); self.configure(capacities={'build': 8, 'review': 4, 'expedited': 2})
        self.assertEqual(read_json(self.pool / 'queue.json')[0], original); self.fill('a', range(1, 3)); self.fill('b')
        self.configure(mode='legacy'); self.assertFalse(self.acquire(self.queue('b', 3))['acquired'])
        self.assertEqual(read_json(self.pool / 'queue.json')[0], original); self.assertEqual(hashes, {str(path): digest(path) for path in protected})
        self.assertEqual(self.call('a', 'verify-review', '0', token=active['token'], value=work), permit)

    def test_configurable_review_four_does_not_modify_old_manifest_three(self):
        self.create('a', 'A'); self.create('b', 'B'); old = digest(self.pool / 'a/manifest.json')
        self.configure(capacities={'build': 8, 'review': 4, 'expedited': 2})
        for name, index in (('a', 0), ('a', 1), ('b', 0), ('b', 1)):
            self.assertEqual(self.acquire(self.queue(name, index, stage='review'))['status'], 'active')
        self.assertFalse(self.acquire(self.queue('b', 2, stage='review'))['acquired']); self.assertEqual(digest(self.pool / 'a/manifest.json'), old)

    def test_unbound_and_old_active_work_are_conservatively_counted(self):
        self.create('a'); self.create('b', 'B'); self.configure(); self.fill('a')
        self.assertFalse(self.acquire(self.queue('b', 0))['acquired'])
        self.bind('a', 'A'); self.assertEqual(self.acquire(read_json(self.pool / 'queue.json')[-1])['status'], 'active')

    def test_legacy_manifest_binding_can_use_new_model_group_without_reprepare(self):
        self.create('a', 'A', legacy=True); self.create('b', 'B', legacy=True); self.configure(); self.fill('a'); self.fill('b')

    def test_forged_ids_external_logs_subagents_foreign_batch_failed_commands_refuse(self):
        self.create('a'); request = self.request('a', 'A'); baseline = read_json(request); session_id, log = self.logs['A']; original = log.read_bytes()
        for fault in ('id', 'external', 'subagent', 'foreign_batch', 'failure', 'quoted'):
            with self.subTest(fault=fault):
                value = copy.deepcopy(baseline); lines = [json.loads(line) for line in original.splitlines()]
                if fault == 'id': value['session_id'] = str(uuid.uuid4())
                if fault == 'external':
                    external = self.root / log.name; external.write_bytes(original); value['session_log'] = str(external)
                if fault == 'subagent': lines[0]['payload']['thread_source'] = 'subagent'
                if fault == 'foreign_batch': lines[1]['payload']['item']['command'][-1] = lines[1]['payload']['item']['command'][-1].replace("--batch-id 'a'", "--batch-id 'foreign'")
                if fault == 'failure': lines[1]['payload']['item']['aggregated_output'] = 'ERROR: refusal\nexit=2'
                if fault == 'quoted': lines[1] = {'type': 'response_item', 'payload': {'type': 'message', 'role': 'user', 'content': [{'text': json.dumps(lines[1])}]}}
                log.write_text(''.join(json.dumps(line) + '\n' for line in lines), encoding='utf-8'); write_json(request, value)
                with self.assertRaises(ValueError): self.call('a', 'bind-controller', value=request, authorization='explicit fixture authorization')
                self.assertFalse((self.pool / 'scheduler-config.json').exists())
        log.write_bytes(original)

    def test_binding_log_append_is_safe_but_modified_identity_cannot_expand_capacity(self):
        self.create('a', 'A'); self.create('b', 'B'); self.configure(); settings = scheduler.config(self.pool)
        session_id, log = self.logs['A']
        with log.open('a') as stream: stream.write('{partial')
        self.assertIsNotNone(scheduler.verified_binding(self.pool, 'a', settings))
        original = log.read_bytes(); log.write_bytes(original.replace(session_id.encode(), str(uuid.uuid4()).encode()))
        self.assertIsNone(scheduler.verified_binding(self.pool, 'a', settings)); self.fill('a')
        self.assertFalse(self.acquire(self.queue('b', 0))['acquired'])

    def test_same_identity_copied_log_still_one_group_and_worker_override_refuses(self):
        self.create('a', 'A'); self.create('b'); request = self.request('b', 'A'); value = read_json(request)
        copy_dir = self.sessions / 'copied'; copy_dir.mkdir(); copied = copy_dir / Path(value['session_log']).name; copied.write_bytes(Path(value['session_log']).read_bytes())
        value['session_log'] = str(copied); value['worker_capacity'] = 6; write_json(request, value)
        with self.assertRaisesRegex(ValueError, 'capped at three'): self.call('b', 'bind-controller', value=request, authorization='fixture')
        value.pop('worker_capacity'); write_json(request, value); self.call('b', 'bind-controller', value=request, authorization='fixture'); self.configure(); self.fill('a')
        self.assertFalse(self.acquire(self.queue('b', 0))['acquired'])

    def test_active_group_cannot_be_rebound_to_different_real_session(self):
        self.create('a', 'A'); self.configure(); self.fill('a', range(1)); before = scheduler.config(self.pool)
        with self.assertRaisesRegex(ValueError, 'cannot move'): self.bind('a', 'B')
        self.assertEqual(before, scheduler.config(self.pool))

    def test_limits_and_missing_authorization_fail_without_mutating_queue(self):
        self.create('a', 'A'); before = read_json(self.pool / 'a/manifest.json')
        for capacities in ({'build': 9}, {'review': 9}, {'expedited': 5}, {'build': True}, {'repair': 3}):
            with self.assertRaisesRegex(ValueError, 'Bounded'): self.configure(capacities=capacities)
        path = self.root / 'scheduler-request.json'; write_json(path, {'mode': scheduler.CONTRACT})
        with self.assertRaisesRegex(ValueError, 'authorization'): self.call('a', 'configure-scheduler', value=path)
        self.assertEqual(before, read_json(self.pool / 'a/manifest.json'))

    def test_record_evidence_exclusion_and_windows_job_release_survive_enabled_policy(self):
        self.create('a', 'A'); self.create('b', 'B'); self.configure()
        capture = self.queue('a', 0, stage='record'); self.assertEqual(self.acquire(capture)['status'], 'active')
        evidence = self.queue('b', 0, stage='evidence'); self.assertFalse(self.acquire(evidence)['acquired'])
        next_capture = self.queue('b', 1, stage='record'); self.assertFalse(self.acquire(next_capture)['acquired'])
        with patch('media_job.job_pids', return_value=[303]):
            with self.assertRaisesRegex(ValueError, 'runtime still alive'): self.release(capture)
        with patch('media_job.job_pids', return_value=[]): self.release(capture)
        self.assertEqual(self.acquire(evidence)['status'], 'active'); self.assertFalse(self.acquire(next_capture)['acquired'])

    def test_two_explicit_astra_routes_keep_frozen_scope_and_dispatch_permits(self):
        from test_expedited_route import ExpeditedRouteTests
        fixture = ExpeditedRouteTests(); fixture.setUp()
        try:
            session_id = str(uuid.uuid4()); log = fixture.sessions / ('rollout-2026-10-14T11-00-00-' + session_id + '.jsonl')
            meta = {'type': 'session_meta', 'payload': {'id': session_id, 'thread_source': 'user', 'source': 'vscode'}}
            event = {'type': 'event_msg', 'payload': {'type': 'item_completed', 'thread_id': session_id, 'item': {
                'type': 'CommandExecution', 'status': 'completed', 'exit_code': 0, 'aggregated_output': 'exit=0',
                'command': ["python 'batch_control.py' claim --root '" + str(fixture.pool) + "' --batch-id 'modern' --pid 202"]}}}
            log.write_text(json.dumps(meta) + '\n' + json.dumps(event) + '\n', encoding='utf-8')
            request = fixture.root / 'bind.json'; write_json(request, {'session_id': session_id, 'session_log': str(log)})
            fixture.call('bind-controller', value=request, authorization='fixture explicit scheduling authorization')
            write_json(request, {'mode': scheduler.CONTRACT, 'capacities': {'build': 8, 'review': 4, 'expedited': 2}})
            fixture.call('configure-scheduler', value=request, authorization='fixture explicit scheduling authorization')
            for case_id in ('c1', 'c2'):
                fixture.grant(case_id); active = fixture.acquire(fixture.queue(case_id))
                self.assertEqual(active['status'], 'active'); self.assertEqual(active['stage'], 'expedited')
                permit = fixture.verify(active); self.assertEqual([permit['model'], permit['effort']], ['gpt-6-astra', 'low'])
                self.assertEqual(fixture.verify(active), permit)
            fixture.grant('c3'); waiting = fixture.queue('c3'); self.assertFalse(fixture.acquire(waiting)['acquired'])
            ordinary = fixture.queue('c4', 'build'); self.assertEqual(fixture.acquire(ordinary)['status'], 'active')
        finally: fixture.tearDown()


if __name__ == '__main__': unittest.main()
