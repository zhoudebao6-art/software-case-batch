"""Fixture-only tests for the new bounded media pool and legacy compatibility."""
from pathlib import Path
import sys
import tempfile
import unittest
import threading
import time
import os
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
import batch_control as batch
from common import digest,read_json,write_json

class RecordingConcurrencyTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name);self.pool=self.root/'pool'
        self.identity=patch('batch_control.identity',side_effect=lambda pid:{'pid':pid,'created_ticks':pid+1000});self.identity.start()
        self.memory=patch('batch_control.memory_available_mb',return_value=24000);self.memory.start()
        self.cpu=patch('batch_control.cpu_snapshot',return_value={'logical_processors':32,'cpu_load_percent':20,'sample_seconds':.2});self.cpu.start()
    def tearDown(self):
        self.cpu.stop();self.memory.stop();self.identity.stop();self.temp.cleanup()
    def create(self,name,limit='auto',host_slots=4):
        cases=[]
        for i in range(6):
            work=self.root/f'{name}-{i}';work.mkdir();source=work/'source.docx';source.write_bytes(b'fixture')
            if limit is not None:write_json(work/'.product-v2/run.json',{'workspace':str(work),'run_id':f'fixture-{name}-{i}'})
            cases.append({'case_id':str(i),'workspace':str(work),'source_docx':str(source),'source_sha256':digest(source)})
        case_list=self.root/(name+'.json');write_json(case_list,{'cases':cases})
        manifest=batch.register(self.pool,name,case_list,'fixture user authorization',host_slots,limit)
        batch.claim(self.pool,name,101)
        return manifest,lambda action,case_id=None,**kw:batch.mutate(self.pool,name,101,action,case_id,**kw)
    def capture(self,mutate,case_id):
        ticket=mutate('queue',case_id,stage='record');return ticket,mutate('acquire',token=ticket['token'])
    def test_four_recordings_share_parent_but_do_not_consume_three_model_workers(self):
        manifest,mutate=self.create('four')
        self.assertEqual(manifest['execution_profile']['worker_capacity'],3)
        self.assertEqual(manifest['execution_profile']['capacities']['record'],4)
        for i in range(4):self.assertEqual(self.capture(mutate,str(i))[1]['status'],'active')
        self.assertFalse(self.capture(mutate,'4')[1]['acquired'])
        evidence=mutate('queue','5',stage='evidence');self.assertFalse(mutate('acquire',token=evidence['token'])['acquired'])
    def test_global_four_cap_applies_across_new_batches(self):
        _,first=self.create('first');_,second=self.create('second')
        for i in range(3):self.assertEqual(self.capture(first,str(i))[1]['status'],'active')
        self.assertEqual(self.capture(second,'0')[1]['status'],'active')
        self.assertFalse(self.capture(second,'1')[1]['acquired'])
    def test_explicit_three_limit_and_legacy_two_global_limit_remain_frozen(self):
        _,old=self.create('old',None);_,new=self.create('new',4)
        oldhash=digest(self.pool/'old/manifest.json')
        self.assertEqual(self.capture(old,'0')[1]['status'],'active')
        old('drain',authorization='fixture pause')
        self.assertEqual(self.capture(new,'0')[1]['status'],'active')
        ticket,result=self.capture(new,'1');self.assertFalse(result['acquired'])
        active=next(q for q in read_json(self.pool/'queue.json') if q['batch_id']=='old' and q['status']=='active')
        old('release-slot',token=active['token']);self.assertEqual(new('acquire',token=ticket['token'])['status'],'active')
        self.assertEqual(digest(self.pool/'old/manifest.json'),oldhash)
        _,three=self.create('three',3)
        self.assertEqual(self.capture(three,'0')[1]['status'],'active')
        self.assertFalse(self.capture(three,'1')[1]['acquired'])
    def test_auto_registration_memory_and_cpu_choose_bounded_frozen_cap(self):
        with patch('batch_control.memory_available_mb',return_value=8200):manifest,mutate=self.create('auto-three')
        self.assertEqual(manifest['execution_profile']['capacities']['record'],3)
        before=digest(self.pool/'auto-three/manifest.json')
        with patch('batch_control.memory_available_mb',return_value=3000):
            ticket,result=self.capture(mutate,'0');self.assertEqual(result['reason'],'memory_exhausted')
        self.assertEqual(mutate('acquire',token=ticket['token'])['status'],'active')
        self.assertEqual(digest(self.pool/'auto-three/manifest.json'),before)
        with patch('batch_control.cpu_snapshot',return_value={'logical_processors':10,'cpu_load_percent':20}):
            manifest,_=self.create('small-cpu')
        self.assertEqual(manifest['execution_profile']['capacities']['record'],2)
    def test_admission_memory_uses_global_record_count_and_cpu_load_waits(self):
        _,mutate=self.create('resource',4)
        for i in range(3):self.capture(mutate,str(i))
        ticket=mutate('queue','3',stage='record')
        with patch('batch_control.memory_available_mb',return_value=10239):
            result=mutate('acquire',token=ticket['token']);self.assertEqual(result['required_mb'],10240);self.assertEqual(result['reason'],'memory_exhausted')
        with patch('batch_control.cpu_snapshot',return_value={'logical_processors':16,'cpu_load_percent':20}):
            self.assertEqual(mutate('acquire',token=ticket['token'])['reason'],'cpu_capacity')
        with patch('batch_control.cpu_snapshot',return_value={'logical_processors':32,'cpu_load_percent':86}):
            self.assertEqual(mutate('acquire',token=ticket['token'])['reason'],'cpu_busy')
        self.assertEqual(mutate('acquire',token=ticket['token'])['status'],'active')
    def test_launch_recheck_retains_active_lease_until_parent_finally_releases(self):
        manifest,mutate=self.create('launch')
        ticket,_=self.capture(mutate,'0');work=manifest['cases'][0]['workspace']
        with patch('batch_control.memory_available_mb',return_value=4095):
            result=mutate('verify-record','0',token=ticket['token'],value=work);self.assertFalse(result['acquired'])
        self.assertEqual(next(q for q in read_json(self.pool/'queue.json') if q['token']==ticket['token'])['status'],'active')
        self.assertTrue(mutate('verify-record','0',token=ticket['token'],value=work)['acquired'])
        with self.assertRaisesRegex(ValueError,'different'):mutate('verify-record','1',token=ticket['token'],value=work)
        mutate('release-slot',token=ticket['token'])
        with self.assertRaisesRegex(ValueError,'active record lease'):mutate('verify-record','0',token=ticket['token'],value=work)
    def test_invalid_limits_are_rejected_without_registering(self):
        for limit in (0,1,5,'unlimited'):
            with self.assertRaisesRegex(ValueError,'recording limit'):
                batch.register(self.pool,'invalid',self.root/'missing.json','fixture authorization',4,limit)
    def test_models_still_use_three_workers_while_media_uses_separate_pool(self):
        manifest,mutate=self.create('models')
        checks=[]
        for kind in ('workspace_write','read_only','browser','word_render'):
            log=self.root/(kind+'.log');log.write_text('fixture command output')
            checks.append({'kind':kind,'command':'fixture','exit_code':0,'log':str(log),'sha256':digest(log)})
        proof=self.root/'preflight.json';write_json(proof,{'status':'ready','zero_model_calls':0,'checks':checks});mutate('preflight',value=proof)
        for i,stage in enumerate(('build','review','build')):
            ticket=mutate('queue',str(i),stage=stage);self.assertEqual(mutate('acquire',token=ticket['token'])['status'],'active')
        model=mutate('queue','3',stage='build');self.assertFalse(mutate('acquire',token=model['token'])['acquired'])
        self.assertEqual(self.capture(mutate,'4')[1]['status'],'active')
        self.assertEqual(manifest['models']['build'],['gpt-6.1-sol','high'])
    def test_launch_lock_contention_waits_without_deleting_holder_lock(self):
        manifest,mutate=self.create('contended');ticket,_=self.capture(mutate,'0');held=threading.Event()
        def hold():
            with batch.transaction(self.pool):held.set();time.sleep(.15)
        thread=threading.Thread(target=hold);thread.start();self.assertTrue(held.wait(1))
        result=mutate('verify-record','0',token=ticket['token'],value=manifest['cases'][0]['workspace']);thread.join()
        self.assertTrue(result['acquired']);self.assertFalse((self.pool/'mutation.lock').exists())
    def test_duplicate_live_workspace_in_new_media_pool_is_refused(self):
        manifest,first=self.create('original')
        self.capture(first,'0')
        cases=self.root/'same.json';write_json(cases,{'cases':manifest['cases']})
        with self.assertRaisesRegex(ValueError,'frozen media batch binding'):
            batch.register(self.pool,'same',cases,'fixture authorization',4,4)
        self.assertFalse((self.pool/'same').exists())
    def test_recovered_live_media_reservation_still_excludes_opposite_stage(self):
        for stage,other_stage in (('record','evidence'),('evidence','record')):
            manifest,first=self.create('recovery-'+stage);_,second=self.create('other-'+stage)
            ticket=first('queue','0',stage=stage);first('acquire',token=ticket['token'])
            with patch('batch_control.identity',side_effect=lambda pid:None if pid==101 else {'pid':pid,'created_ticks':pid+1000}):
                batch.claim(self.pool,'recovery-'+stage,202,True)
            active=next(q for q in read_json(self.pool/'queue.json') if q['token']==ticket['token'])
            self.assertEqual(active['status'],'active');self.assertEqual(active['owner']['pid'],202)
            waiting=second('queue','0',stage=other_stage)
            self.assertFalse(second('acquire',token=waiting['token'])['acquired'])
            with patch('media_job.job_pids',return_value=[]):batch.mutate(self.pool,'recovery-'+stage,202,'release-slot',token=ticket['token'])
            self.assertEqual(second('acquire',token=waiting['token'])['status'],'active')
            second('release-slot',token=waiting['token'])
    def test_evidence_launch_rechecks_active_token_case_owner_and_global_exclusion(self):
        manifest,mutate=self.create('evidence-launch');ticket=mutate('queue','0',stage='evidence')
        work=manifest['cases'][0]['workspace']
        with self.assertRaisesRegex(ValueError,'active evidence'):mutate('verify-evidence','0',token=ticket['token'],value=work)
        mutate('acquire',token=ticket['token'])
        self.assertTrue(mutate('verify-evidence','0',token=ticket['token'],value=work)['acquired'])
        with self.assertRaisesRegex(ValueError,'different'):mutate('verify-evidence','1',token=ticket['token'],value=work)
        pool=read_json(self.pool/'queue.json');pool.append({**pool[0],'token':'fixture-capture','stage':'record','case_id':'1'});write_json(self.pool/'queue.json',pool)
        with self.assertRaisesRegex(ValueError,'global media exclusion'):mutate('verify-evidence','0',token=ticket['token'],value=work)
    def test_binding_cannot_be_switched_to_another_root_or_manifest(self):
        manifest,_=self.create('binding');work=manifest['cases'][0]['workspace'];path=Path(work)/'.product-v2/batch-binding.json'
        self.assertEqual(batch.media_binding(work)['batch_id'],'binding')
        value=read_json(path);value['case_id']='1';write_json(path,value)
        with self.assertRaisesRegex(ValueError,'binding changed'):batch.media_binding(work)
    def test_registration_failure_removes_only_its_own_manifest_and_bindings(self):
        original_open=Path.open;count=0
        def failing_open(path,*args,**kwargs):
            nonlocal count
            if path.name=='batch-binding.json' and args and args[0]=='x':
                count+=1
                if count==2:raise OSError('fixture disk write failure')
            return original_open(path,*args,**kwargs)
        with patch.object(Path,'open',failing_open):
            with self.assertRaisesRegex(OSError,'fixture disk'):self.create('rollback')
        self.assertFalse((self.pool/'rollback').exists())
        self.assertFalse((self.root/'rollback-0/.product-v2/batch-binding.json').exists())
        self.assertTrue((self.root/'rollback-0/source.docx').exists())
    def test_legacy_recovered_media_requires_fresh_token_and_registry_bound_cleanup(self):
        manifest,mutate=self.create('legacy-recovery',None);ticket,_=self.capture(mutate,'0');work=Path(manifest['cases'][0]['workspace'])
        with patch('batch_control.identity',side_effect=lambda pid:None if pid==101 else {'pid':pid,'created_ticks':pid+1000}):batch.claim(self.pool,'legacy-recovery',202,True)
        control=work/'.product-v2';control.mkdir()
        runtime={'pid':303,'parent_pid':101,'created_ticks':1303,'name':'node.exe','command':f'node.exe "tool/record.cjs" --workspace "{work}"','command_sha256':'fixture-runtime-hash','ports':[]}
        child={'pid':304,'parent_pid':303,'created_ticks':1304,'name':'ffmpeg.exe','command':'ffmpeg.exe fixture','command_sha256':'fixture-child-hash','ports':[]}
        registry=control/'processes.json';cleanup=control/'cleanup.json';binding=control/'legacy-release.json'
        write_json(registry,{'workspace':str(work),'processes':[runtime,child]})
        write_json(cleanup,{'workspace':str(work),'status':'stopped','remaining':[],'ports_still_listening':[],'processes':[{'pid':303,'status':'original_exited'},{'pid':304,'status':'original_exited'}]})
        bound={'workspace':str(work),'batch_id':'legacy-recovery','token':ticket['token'],'cleanup':{'path':str(cleanup),'sha256':digest(cleanup)},'registry':{'path':str(registry),'sha256':digest(registry)}};write_json(binding,bound)
        def release(value=None):return batch.mutate(self.pool,'legacy-recovery',202,'release-slot',token=ticket['token'],value=value)
        with self.assertRaisesRegex(ValueError,'binding'):release()
        with patch('process_guard.inventory',return_value=[child]):
            with self.assertRaisesRegex(ValueError,'still alive'):release(binding)
        unregistered_child={**child,'pid':305,'command_sha256':'new-child'}
        with patch('process_guard.inventory',return_value=[unregistered_child]):
            with self.assertRaisesRegex(ValueError,'descendant'):release(binding)
        write_json(binding,{**bound,'token':'another-token'})
        with self.assertRaisesRegex(ValueError,'exact workspace/token'):release(binding)
        write_json(binding,bound);acquired=read_json(self.pool/'queue.json')[0]['acquired_ns'];os.utime(cleanup,ns=(acquired-1000,acquired-1000))
        with self.assertRaisesRegex(ValueError,'predates'):release(binding)
        write_json(cleanup,read_json(cleanup))
        with patch('process_guard.inventory',return_value=[]):result=release(binding)
        self.assertEqual(result['status'],'released');self.assertEqual(result['legacy_media_exit_proof']['token'],ticket['token'])
    def test_legacy_cleanup_qualifies_reused_parent_pid_by_process_creation(self):
        original={'pid':303,'parent_pid':101,'created_ticks':1303,'name':'node.exe','command_sha256':'original-runtime','ports':[]}
        replacement={**original,'created_ticks':2303,'command':'node.exe unrelated.js','command_sha256':'replacement-runtime'}
        replacement_child={'pid':305,'parent_pid':303,'created_ticks':2304,'name':'node.exe','command':'node.exe unrelated-child.js','command_sha256':'replacement-child','ports':[]}
        grandchild={**replacement_child,'pid':306,'parent_pid':305,'created_ticks':2305}
        scenarios=[('replacement-family',[replacement,replacement_child,grandchild],True),
                   ('old-orphan-before-replacement',[replacement,{**replacement_child,'created_ticks':1304},grandchild],False),
                   ('child-predates-original',[{**replacement_child,'created_ticks':1302}],True),
                   ('original-root-missing',[{**replacement_child,'created_ticks':1304}],False),
                   ('replacement-identity-unknown',[{**replacement,'created_ticks':0},replacement_child],False),
                   ('replacement-time-inconsistent',[{**replacement,'created_ticks':1203},replacement_child],False),
                   ('child-identity-unknown',[replacement,{**replacement_child,'created_ticks':0}],False),
                   ('original-root-live',[{**original,'command':'record.cjs'},replacement_child],False)]
        for name,rows,releasable in scenarios:
            with self.subTest(name=name):
                self.pool=self.root/('pool-'+name)
                manifest,mutate=self.create(name,None);ticket,_=self.capture(mutate,'0');work=Path(manifest['cases'][0]['workspace'])
                with patch('batch_control.identity',side_effect=lambda pid:None if pid==101 else {'pid':pid,'created_ticks':pid+1000}):batch.claim(self.pool,name,202,True)
                control=work/'.product-v2';control.mkdir();registry=control/'processes.json';cleanup=control/'cleanup.json';binding=control/'legacy-release.json'
                saved={**original,'command':f'node.exe "tool/record.cjs" --workspace "{work}"'}
                write_json(registry,{'workspace':str(work),'processes':[saved]})
                write_json(cleanup,{'workspace':str(work),'status':'stopped','remaining':[],'ports_still_listening':[],'processes':[{'pid':303,'status':'original_exited'}]})
                write_json(binding,{'workspace':str(work),'batch_id':name,'token':ticket['token'],'cleanup':{'path':str(cleanup),'sha256':digest(cleanup)},'registry':{'path':str(registry),'sha256':digest(registry)}})
                with patch('process_guard.inventory',return_value=rows):
                    if releasable:
                        result=batch.mutate(self.pool,name,202,'release-slot',token=ticket['token'],value=binding)
                        self.assertEqual(result['status'],'released')
                    else:
                        with self.assertRaisesRegex(ValueError,'descendant|still alive'):batch.mutate(self.pool,name,202,'release-slot',token=ticket['token'],value=binding)
                        current=next(row for row in read_json(self.pool/'queue.json') if row['token']==ticket['token']);self.assertEqual(current['status'],'active')

if __name__=='__main__':unittest.main()
