"""Bound a new-batch media invocation and its descendants to one Windows Job.

The supervisor lives only for this invocation. Closing its non-inheritable Job
handle kills remaining descendants, including when the supervisor crashes.
"""
import argparse
import ctypes
from ctypes import wintypes
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
from common import no_links,read_json,write_json

def job_name(root,batch_id,token):
    key=str(no_links(root)).casefold()+'\n'+batch_id+'\n'+token
    return 'Local\\SCBProMedia-'+hashlib.sha256(key.encode()).hexdigest()

def kernel():
    if os.name!='nt':raise ValueError('Bound media requires a Windows Job')
    k=ctypes.WinDLL('kernel32',use_last_error=True)
    for name,args,result in (
        ('CreateJobObjectW',[ctypes.c_void_p,wintypes.LPCWSTR],wintypes.HANDLE),
        ('OpenJobObjectW',[wintypes.DWORD,wintypes.BOOL,wintypes.LPCWSTR],wintypes.HANDLE),
        ('SetInformationJobObject',[wintypes.HANDLE,ctypes.c_int,ctypes.c_void_p,wintypes.DWORD],wintypes.BOOL),
        ('QueryInformationJobObject',[wintypes.HANDLE,ctypes.c_int,ctypes.c_void_p,wintypes.DWORD,ctypes.c_void_p],wintypes.BOOL),
        ('AssignProcessToJobObject',[wintypes.HANDLE,wintypes.HANDLE],wintypes.BOOL),
        ('CloseHandle',[wintypes.HANDLE],wintypes.BOOL),
        ('ResumeThread',[wintypes.HANDLE],wintypes.DWORD),
        ('TerminateProcess',[wintypes.HANDLE,wintypes.UINT],wintypes.BOOL),
        ('WaitForSingleObject',[wintypes.HANDLE,wintypes.DWORD],wintypes.DWORD),
        ('GetExitCodeProcess',[wintypes.HANDLE,ctypes.POINTER(wintypes.DWORD)],wintypes.BOOL)):
        fn=getattr(k,name);fn.argtypes=args;fn.restype=result
    return k

def _pids(k,handle):
    size=4096
    while size<=1024*1024:
        buf=ctypes.create_string_buffer(size)
        if k.QueryInformationJobObject(handle,3,buf,size,None):
            count=ctypes.c_uint32.from_buffer(buf,4).value
            return list((ctypes.c_size_t*count).from_buffer(buf,8))
        if ctypes.get_last_error()!=234:raise ctypes.WinError(ctypes.get_last_error())
        size*=2
    raise ValueError('Media Job membership exceeds its bounded query')

def job_pids(name):
    k=kernel();handle=k.OpenJobObjectW(4,False,name)
    if not handle:
        if ctypes.get_last_error()==2:return []
        raise ctypes.WinError(ctypes.get_last_error())
    try:return _pids(k,handle)
    finally:k.CloseHandle(handle)

def runtime_command(pid):
    """Read this one suspended process, without a host-wide process census."""
    if not isinstance(pid,int) or pid<1:raise ValueError('Invalid media runtime PID')
    script=f"$p=Get-CimInstance Win32_Process -Filter 'ProcessId = {pid}'; if($p){{[Console]::OutputEncoding=[Text.UTF8Encoding]::new($false);[string]$p.CommandLine}}"
    result=subprocess.run(['powershell.exe','-NoProfile','-NonInteractive','-Command',script],
        capture_output=True,text=True,encoding='utf-8',timeout=15,creationflags=subprocess.CREATE_NO_WINDOW)
    if result.returncode or not result.stdout.strip():raise ValueError('Current media runtime command unavailable')
    shell=ctypes.WinDLL('shell32',use_last_error=True);shell.CommandLineToArgvW.argtypes=[wintypes.LPCWSTR,ctypes.POINTER(ctypes.c_int)];shell.CommandLineToArgvW.restype=ctypes.POINTER(wintypes.LPWSTR)
    count=ctypes.c_int();argv=shell.CommandLineToArgvW(result.stdout.strip(),ctypes.byref(count))
    if not argv:raise ctypes.WinError(ctypes.get_last_error())
    try:return [argv[i] for i in range(count.value)]
    finally:
        k=kernel();k.LocalFree.argtypes=[ctypes.c_void_p];k.LocalFree(argv)

def verify_runtime_command(runtime):
    argv=runtime_command(runtime['pid']);expected=str(no_links(Path(__file__).with_name('record.cjs')))
    if len(argv)<4 or str(no_links(argv[0])).casefold()!=str(no_links(os.environ['SCB_PRO_NODE'])).casefold() or str(no_links(argv[1])).casefold()!=expected.casefold():
        raise ValueError('Media runtime is not the exact approved Node recording entry')
    if '--workspace' not in argv or str(no_links(argv[argv.index('--workspace')+1])).casefold()!=runtime['workspace'].casefold():
        raise ValueError('Media runtime command belongs to a different workspace')
    return {'argv':argv,'command_sha256':hashlib.sha256('\0'.join(argv).encode()).hexdigest()}

class Job:
    def __init__(self,name):
        self.k=kernel();self.handle=self.k.CreateJobObjectW(None,name)
        if not self.handle:raise ctypes.WinError(ctypes.get_last_error())
        if ctypes.get_last_error()==183:
            self.close();raise ValueError('Media Job already exists; preserve the live invocation')
        class Basic(ctypes.Structure):
            _fields_=[('process_time',ctypes.c_int64),('job_time',ctypes.c_int64),('flags',wintypes.DWORD),
                      ('min_working',ctypes.c_size_t),('max_working',ctypes.c_size_t),
                      ('active_limit',wintypes.DWORD),('affinity',ctypes.c_size_t),
                      ('priority',wintypes.DWORD),('scheduling',wintypes.DWORD)]
        class IO(ctypes.Structure):
            _fields_=[(n,ctypes.c_uint64) for n in ('read_ops','write_ops','other_ops','read_bytes','write_bytes','other_bytes')]
        class Extended(ctypes.Structure):
            _fields_=[('basic',Basic),('io',IO),('process_memory',ctypes.c_size_t),
                      ('job_memory',ctypes.c_size_t),('peak_process',ctypes.c_size_t),('peak_job',ctypes.c_size_t)]
        limits=Extended();limits.basic.flags=0x2000 # KILL_ON_JOB_CLOSE; no breakaway.
        if not self.k.SetInformationJobObject(self.handle,9,ctypes.byref(limits),ctypes.sizeof(limits)):
            error=ctypes.get_last_error();self.close();raise ctypes.WinError(error)
    def close(self):
        if self.handle:self.k.CloseHandle(self.handle);self.handle=None
    def pids(self):return _pids(self.k,self.handle)

def launch_suspended(job,args,env):
    """Retain both handles; assign before any child instruction can execute."""
    class Startup(ctypes.Structure):
        _fields_=[('cb',wintypes.DWORD),('reserved',wintypes.LPWSTR),('desktop',wintypes.LPWSTR),
                  ('title',wintypes.LPWSTR)]+[(n,wintypes.DWORD) for n in ('x','y','width','height','chars_x','chars_y','fill','flags')]+[
                  ('show',wintypes.WORD),('reserved2_count',wintypes.WORD),('reserved2',ctypes.c_void_p),
                  ('stdin',wintypes.HANDLE),('stdout',wintypes.HANDLE),('stderr',wintypes.HANDLE)]
    class Info(ctypes.Structure):
        _fields_=[('process',wintypes.HANDLE),('thread',wintypes.HANDLE),('pid',wintypes.DWORD),('tid',wintypes.DWORD)]
    k=job.k;k.GetStdHandle.argtypes=[wintypes.DWORD];k.GetStdHandle.restype=wintypes.HANDLE
    k.SetHandleInformation.argtypes=[wintypes.HANDLE,wintypes.DWORD,wintypes.DWORD]
    startup=Startup();startup.cb=ctypes.sizeof(startup);startup.flags=0x100;startup.show=0
    for name,constant in (('stdin',-10),('stdout',-11),('stderr',-12)):
        handle=k.GetStdHandle(constant & 0xffffffff);setattr(startup,name,handle)
        if handle and handle!=ctypes.c_void_p(-1).value:k.SetHandleInformation(handle,1,1)
    info=Info();cmd=ctypes.create_unicode_buffer(subprocess.list2cmdline([str(a) for a in args]))
    environment=ctypes.create_unicode_buffer('\0'.join(f'{key}={value}' for key,value in sorted(env.items(),key=lambda item:item[0].casefold()))+'\0\0')
    k.CreateProcessW.argtypes=[wintypes.LPCWSTR,wintypes.LPWSTR,ctypes.c_void_p,ctypes.c_void_p,
        wintypes.BOOL,wintypes.DWORD,ctypes.c_void_p,wintypes.LPCWSTR,ctypes.POINTER(Startup),ctypes.POINTER(Info)]
    k.CreateProcessW.restype=wintypes.BOOL
    if not k.CreateProcessW(None,cmd,None,None,True,0x4|0x8000000|0x400,environment,None,ctypes.byref(startup),ctypes.byref(info)):
        raise ctypes.WinError(ctypes.get_last_error())
    try:
        if not k.AssignProcessToJobObject(job.handle,info.process):raise ctypes.WinError(ctypes.get_last_error())
        return info
    except BaseException:
        # Only our retained, never-resumed child is eligible for rollback.
        k.TerminateProcess(info.process,2);k.WaitForSingleObject(info.process,5000)
        k.CloseHandle(info.thread);k.CloseHandle(info.process);raise

def verify_membership(workspace,token,runtime_pid):
    from batch_control import media_binding,batch,identity
    binding=media_binding(workspace)
    if not binding:raise ValueError('Frozen media batch binding required')
    _,manifest=batch(binding['root'],binding['batch_id'])
    pool=read_json(no_links(binding['root'])/'queue.json')
    entry=next((q for q in pool if q['token']==token and q['batch_id']==binding['batch_id']),None)
    runtime=entry.get('media_runtime') if entry else None
    if (not runtime or runtime['pid']!=runtime_pid or identity(runtime_pid)!=runtime['identity'] or
        runtime_pid not in job_pids(job_name(binding['root'],binding['batch_id'],token))):
        raise ValueError('Exact media runtime is outside its reserved Windows Job')
    return runtime

def supervise(workspace,phase,lease,record_args):
    from batch_control import media_binding,mutate,identity
    binding=media_binding(workspace)
    if not binding or phase not in {'capture','evidence'}:raise ValueError('Bound batch media requires capture/evidence phases')
    for key,source in (('root','root'),('batchId','batch_id'),('caseId','case_id')):
        actual=str(no_links(lease[key])) if key=='root' else lease[key]
        if actual!=binding[source]:raise ValueError('Media lease differs from frozen workspace binding')
    stage='record' if phase=='capture' else 'evidence';action='verify-record' if stage=='record' else 'verify-evidence'
    result=mutate(lease['root'],lease['batchId'],lease['ownerPid'],action,lease['caseId'],workspace,lease['token'])
    if not result['acquired']:raise ValueError('Media launch admission failed: '+result['reason'])
    name=job_name(lease['root'],lease['batchId'],lease['token']);job=Job(name);info=None
    try:
        environment=dict(os.environ,SCB_PRO_MEDIA_JOB=name,SCB_PRO_MEDIA_TOKEN=lease['token'])
        args=[os.environ['SCB_PRO_NODE'],str(Path(__file__).with_name('record.cjs')),*record_args]
        info=launch_suspended(job,args,environment)
        runtime={'workspace':str(no_links(workspace)),'pid':info.pid,'identity':identity(info.pid),
                 'job_name':name,'supervisor_identity':identity(os.getpid()),'started_ns':time.time_ns(),
                 'executable':str(no_links(args[0])),'script':str(no_links(args[1]))}
        temp_root=no_links(os.environ['TEMP']);temp_root.mkdir(parents=True,exist_ok=True)
        with tempfile.TemporaryDirectory(prefix='scb-media-runtime-',dir=temp_root) as temporary:
            proof=Path(temporary)/'runtime.json';write_json(proof,runtime)
            mutate(lease['root'],lease['batchId'],lease['ownerPid'],'bind-media-runtime',lease['caseId'],proof,lease['token'],stage)
        if job.k.ResumeThread(info.thread)==0xffffffff:raise ctypes.WinError(ctypes.get_last_error())
        while True:
            waited=job.k.WaitForSingleObject(info.process,500)
            if waited==0:break
            if waited!=258:raise ValueError('Media runtime wait failed; retain reservation')
        code=wintypes.DWORD()
        if not job.k.GetExitCodeProcess(info.process,ctypes.byref(code)):raise ctypes.WinError(ctypes.get_last_error())
        if code.value==259:raise ValueError('Media runtime is still active; retain reservation')
        return int(code.value)
    finally:
        job.close() # Descendants cannot outlive the supervised media invocation.
        if info:
            job.k.WaitForSingleObject(info.process,5000)
            job.k.CloseHandle(info.thread);job.k.CloseHandle(info.process)

def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--workspace',required=True)
    parser.add_argument('--phase',choices=['capture','evidence'],required=True);parser.add_argument('--lease',required=True)
    parser.add_argument('record_args',nargs=argparse.REMAINDER);args=parser.parse_args()
    try:
        values=args.record_args[1:] if args.record_args[:1]==['--'] else args.record_args
        return supervise(args.workspace,args.phase,json.loads(args.lease),values)
    except (ValueError,OSError,KeyError,TypeError) as error:
        print('ERROR: '+str(error),file=sys.stderr);return 2

if __name__=='__main__':raise SystemExit(main())
