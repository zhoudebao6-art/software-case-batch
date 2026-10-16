"""Real Windows dummy-process Job lifetime tests; no browser or FFmpeg."""
import ctypes
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import unittest
import uuid
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
import batch_control as batch
from common import digest,read_json,write_json
from media_job import Job,job_name,job_pids,launch_suspended

@unittest.skipUnless(os.name=='nt','Windows Job behavior')
class WindowsMediaJobTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(prefix='scb-job-tests-');self.root=Path(self.temp.name)
        self.jobs=[];self.processes=[];self.handles=[]
    def tearDown(self):
        for job in self.jobs:job.close()
        for info,k in self.handles:
            k.WaitForSingleObject(info.process,5000);k.CloseHandle(info.thread);k.CloseHandle(info.process)
        for process in self.processes:
            if process.poll() is None:process.terminate()
            process.wait(timeout=5)
        self.temp.cleanup()
    def job(self,name=None):
        result=Job(name or 'Local\\SCBProTest-'+uuid.uuid4().hex);self.jobs.append(result);return result
    def launch(self,job,args):
        result=launch_suspended(job,args,dict(os.environ));self.handles.append((result,job.k));return result
    def node(self):return os.environ['SCB_PRO_NODE']
    def fixed_resource_environment(self):
        """Fix only child Python resource samples; Job/Node APIs remain real."""
        folder=self.root/'resource-samples';folder.mkdir()
        (folder/'sitecustomize.py').write_text('''import ctypes, os
from ctypes import wintypes
os.cpu_count=lambda:32
class Memory(ctypes.Structure):
    _fields_=[('length',ctypes.c_ulong),('load',ctypes.c_ulong)]+[(name,ctypes.c_ulonglong) for name in ('total_phys','avail_phys','total_page','avail_page','total_virtual','avail_virtual','avail_extended')]
def memory_sample(pointer):
    value=ctypes.cast(pointer,ctypes.POINTER(Memory)).contents
    value.avail_phys=value.avail_page=24000*1024*1024
    return 1
ticks=0
def cpu_sample(idle,kernel,user):
    global ticks
    ticks+=10000000
    for pointer,value in ((idle,ticks*9),(kernel,ticks*10),(user,0)):
        result=ctypes.cast(pointer,ctypes.POINTER(wintypes.FILETIME)).contents
        result.dwLowDateTime=value&0xffffffff;result.dwHighDateTime=value>>32
    return 1
ctypes.windll.kernel32.GlobalMemoryStatusEx=memory_sample
ctypes.windll.kernel32.GetSystemTimes=cpu_sample
''',encoding='utf-8')
        return dict(os.environ,PYTHONPATH=str(folder)+(os.pathsep+os.environ['PYTHONPATH'] if os.environ.get('PYTHONPATH') else ''))
    def wait_for(self,condition,seconds=5):
        until=time.monotonic()+seconds
        while not condition():
            if time.monotonic()>=until:self.fail('Bounded process condition did not complete')
            time.sleep(.05)
    def test_kill_on_close_ends_node_and_its_child(self):
        signal=self.root/'children.json';job=self.job()
        script="const fs=require('fs'),{spawn}=require('child_process');const c=spawn(process.execPath,['-e','setInterval(()=>{},1000)'],{stdio:'ignore',windowsHide:true});fs.writeFileSync(process.argv[1],JSON.stringify({root:process.pid,child:c.pid}));setInterval(()=>{},1000);"
        info=self.launch(job,[self.node(),'-e',script,str(signal)])
        self.assertEqual(job.k.ResumeThread(info.thread),1);self.wait_for(signal.exists)
        children=read_json(signal);self.wait_for(lambda:set(children.values()).issubset(set(job.pids())))
        identities=[batch.identity(pid) for pid in children.values()];job.close()
        self.wait_for(lambda:all(batch.identity(item['pid'])!=item for item in identities))
    def test_media_node_natural_exit_does_not_leave_its_child_after_job_closes(self):
        signal=self.root/'child.json';job=self.job()
        # A non-detached child may be killed by libuv's own Job when Node exits.
        # Detached avoids that inner Job; it still inherits our outer SCB Job.
        script="const fs=require('fs'),{spawn}=require('child_process');const c=spawn(process.execPath,['-e','setInterval(()=>{},1000)'],{stdio:'ignore',windowsHide:true,detached:true});c.unref();fs.writeFileSync(process.argv[1],JSON.stringify({child:c.pid}));setTimeout(()=>process.exit(0),500);"
        info=self.launch(job,[self.node(),'-e',script,str(signal)]);job.k.ResumeThread(info.thread)
        self.wait_for(signal.exists);child=batch.identity(read_json(signal)['child'])
        self.assertIsNotNone(child);self.wait_for(lambda:child['pid'] in job.pids())
        self.assertEqual(job.k.WaitForSingleObject(info.process,5000),0)
        self.assertIn(child['pid'],job.pids())
        self.assertEqual(batch.identity(child['pid']),child);job.close()
        self.wait_for(lambda:batch.identity(child['pid'])!=child)
    def test_owner_dies_but_media_stays_reserved_until_job_exit_and_recovery_release(self):
        owner=subprocess.Popen([sys.executable,'-c','import time;time.sleep(30)'],creationflags=subprocess.CREATE_NO_WINDOW)
        self.processes.append(owner);work=self.root/'case';work.mkdir();source=work/'source.docx';source.write_bytes(b'fixture')
        cases=self.root/'cases.json';write_json(cases,{'cases':[{'case_id':'c','workspace':str(work),'source_docx':str(source),'source_sha256':digest(source)}]})
        pool=self.root/'pool';batch.register(pool,'batch',cases,'Windows dummy fixture authorization',4,2);batch.claim(pool,'batch',owner.pid)
        ticket=batch.mutate(pool,'batch',owner.pid,'queue','c',stage='record')
        with patch('batch_control.recording_resources',return_value={'acquired':True,'available_mb':24000,'required_mb':4096}):batch.mutate(pool,'batch',owner.pid,'acquire',token=ticket['token'])
        job=self.job(job_name(pool,'batch',ticket['token']));info=self.launch(job,[self.node(),'-e','setInterval(()=>{},1000)'])
        runtime={'workspace':str(work),'pid':info.pid,'identity':batch.identity(info.pid),'job_name':job_name(pool,'batch',ticket['token'])}
        proof=self.root/'runtime.json';write_json(proof,runtime)
        with patch('media_job.verify_runtime_command',return_value={'fixture':'dedicated dummy Node, not recording'}):
            bound=batch.mutate(pool,'batch',owner.pid,'bind-media-runtime','c',proof,ticket['token'],'record')
        runtime=bound['media_runtime'];job.k.ResumeThread(info.thread)
        owner.terminate();owner.wait(timeout=5);batch.claim(pool,'batch',os.getpid(),True)
        active=read_json(pool/'queue.json')[0];self.assertEqual(active['status'],'active');self.assertEqual(active['media_runtime'],runtime)
        self.assertEqual(batch.identity(info.pid),runtime['identity'])
        with self.assertRaisesRegex(ValueError,'still alive'):batch.mutate(pool,'batch',os.getpid(),'release-slot',token=ticket['token'])
        # Another real batch's evidence remains excluded by this reservation.
        other=self.root/'other';other.mkdir();other_source=other/'source.docx';other_source.write_bytes(b'fixture')
        other_cases=self.root/'other-cases.json';write_json(other_cases,{'cases':[{'case_id':'c','workspace':str(other),'source_docx':str(other_source),'source_sha256':digest(other_source)}]})
        batch.register(pool,'other',other_cases,'Windows fixture second authorization',4,2);batch.claim(pool,'other',os.getpid())
        evidence=batch.mutate(pool,'other',os.getpid(),'queue','c',stage='evidence')
        self.assertFalse(batch.mutate(pool,'other',os.getpid(),'acquire',token=evidence['token'])['acquired'])
        job.close();self.wait_for(lambda:batch.identity(info.pid)!=runtime['identity'])
        self.assertEqual(batch.mutate(pool,'batch',os.getpid(),'release-slot',token=ticket['token'])['status'],'released')
        self.assertEqual(batch.mutate(pool,'other',os.getpid(),'acquire',token=evidence['token'])['status'],'active')
    def test_assignment_failure_rolls_back_only_never_resumed_child(self):
        signal=self.root/'should-not-exist';job=self.job();real_assign=job.k.AssignProcessToJobObject
        with patch.object(job.k,'AssignProcessToJobObject',side_effect=lambda *_:(ctypes.set_last_error(5) or False)):
            with self.assertRaises(OSError):launch_suspended(job,[self.node(),'-e',"require('fs').writeFileSync(process.argv[1],'ran')",str(signal)],dict(os.environ))
        self.assertFalse(signal.exists());self.assertEqual(job.pids(),[])
    def test_existing_live_job_is_not_replaced_or_closed_by_retry(self):
        name='Local\\SCBProTest-'+uuid.uuid4().hex;job=self.job(name)
        info=self.launch(job,[self.node(),'-e','setInterval(()=>{},1000)']);job.k.ResumeThread(info.thread)
        with self.assertRaisesRegex(ValueError,'already exists'):Job(name)
        self.assertIn(info.pid,job_pids(name));self.assertEqual(batch.identity(info.pid)['pid'],info.pid)
    def test_supervisor_death_closes_job_and_ends_all_registered_descendants(self):
        signal=self.root/'supervisor-pids.json';helper=self.root/'supervisor.py'
        helper.write_text("import sys,os,time,json\nsys.path.insert(0,"+repr(str(Path(__file__).resolve().parents[1]/'scripts'))+")\nfrom media_job import Job,launch_suspended\njob=Job('Local\\\\SCBProTest-"+uuid.uuid4().hex+"')\nscript=\"const fs=require('fs'),{spawn}=require('child_process');const c=spawn(process.execPath,['-e','setInterval(()=>{},1000)'],{stdio:'ignore',windowsHide:true});fs.writeFileSync(process.argv[1],JSON.stringify({root:process.pid,child:c.pid}));setInterval(()=>{},1000);\"\ninfo=launch_suspended(job,[os.environ['SCB_PRO_NODE'],'-e',script,sys.argv[1]],dict(os.environ))\njob.k.ResumeThread(info.thread)\ntime.sleep(30)\n",encoding='utf-8')
        supervisor=subprocess.Popen([sys.executable,str(helper),str(signal)],creationflags=subprocess.CREATE_NO_WINDOW);self.processes.append(supervisor)
        self.wait_for(signal.exists);identities=[batch.identity(pid) for pid in read_json(signal).values()]
        self.assertTrue(all(identities));supervisor.terminate();supervisor.wait(timeout=5)
        self.wait_for(lambda:all(batch.identity(item['pid'])!=item for item in identities))
    def test_real_node_cli_binds_exact_runtime_and_failed_capture_can_release(self):
        work=self.root/'cli-case';work.mkdir();source=work/'source.docx';source.write_bytes(b'fixture');pool=self.root/'cli-pool'
        cases=self.root/'cli-cases.json';write_json(cases,{'cases':[{'case_id':'c','workspace':str(work),'source_docx':str(source),'source_sha256':digest(source)}]})
        batch.register(pool,'cli',cases,'Windows CLI fixture authorization',4,2);batch.claim(pool,'cli',os.getpid())
        write_json(work/'.product-v2/run.json',{'workspace':str(work),'run_id':'fixture','video':str(work/'output/video.mp4')})
        plan=self.root/'invalid-plan.json';write_json(plan,{'url':'https://example.com'})
        ticket=batch.mutate(pool,'cli',os.getpid(),'queue','c',stage='record')
        with patch('batch_control.recording_resources',return_value={'acquired':True,'available_mb':24000,'required_mb':4096}):batch.mutate(pool,'cli',os.getpid(),'acquire',token=ticket['token'])
        result=subprocess.run([self.node(),str(Path(__file__).resolve().parents[1]/'scripts/record.cjs'),'--workspace',str(work),'--phase','capture','--plan',str(plan),'--batch-root',str(pool),'--batch-id','cli','--case-id','c','--record-token',ticket['token'],'--owner-pid',str(os.getpid())],env=self.fixed_resource_environment(),capture_output=True,text=True,timeout=30,creationflags=subprocess.CREATE_NO_WINDOW)
        self.assertEqual(result.returncode,2,result.stdout+result.stderr);self.assertIn('Recording URL must be local',result.stderr)
        bound=read_json(pool/'queue.json')[0];self.assertIn('command_proof',bound['media_runtime'])
        self.assertTrue(bound['launch_checks'])
        for check in bound['launch_checks']:
            self.assertEqual((check['available_mb'],check['logical_processors'],check['cpu_load_percent']),(24000,32,10))
        self.assertEqual(job_pids(job_name(pool,'cli',ticket['token'])),[])
        self.assertFalse((work/'.product-v2/recording-stage.lock').exists())
        self.assertEqual(batch.mutate(pool,'cli',os.getpid(),'release-slot',token=ticket['token'])['status'],'released')

if __name__=='__main__':unittest.main()
