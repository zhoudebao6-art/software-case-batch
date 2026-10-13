"""Register and close only verified, dedicated Windows case processes."""
import argparse
import ctypes
from ctypes import wintypes
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
from common import no_links, read_json, write_json

def inventory():
    if os.name!='nt': raise ValueError('Process ownership guard requires Windows')
    script=r'''$ErrorActionPreference='Stop'
[Console]::OutputEncoding=[Text.UTF8Encoding]::new($false)
$ports=@(Get-CimInstance -Namespace root/StandardCimv2 -ClassName MSFT_NetTCPConnection -Filter 'State = 2')
$rows=@(Get-CimInstance Win32_Process | ForEach-Object {
  $p=$_
  [pscustomobject]@{pid=[int]$p.ProcessId;parent_pid=[int]$p.ParentProcessId;name=[string]$p.Name;command=[string]$p.CommandLine;created_ticks=if($p.CreationDate){$p.CreationDate.ToUniversalTime().ToFileTimeUtc()}else{0};ports=@($ports | Where-Object {$_.OwningProcess -eq $p.ProcessId} | Select-Object -ExpandProperty LocalPort -Unique)}
})
ConvertTo-Json -Depth 4 -Compress -InputObject $rows
'''
    p=subprocess.run(['powershell.exe','-NoProfile','-NonInteractive','-Command',script],
        capture_output=True,text=True,encoding='utf-8',timeout=45,
        creationflags=subprocess.CREATE_NO_WINDOW)
    if p.returncode: raise ValueError('OS identity query failed: '+p.stderr[-800:])
    rows=json.loads(p.stdout.lstrip('\ufeff'))
    for r in rows:
        r['command_sha256']=hashlib.sha256(r['command'].encode('utf-8')).hexdigest()
    return rows

def command_owned(workspace,command):
    path=str(Path(workspace).resolve()).replace('\\','/').rstrip('/').casefold()
    value=command.replace('\\','/').casefold()
    return bool(re.search(r'(?:^|[\s\"\'=])'+re.escape(path)+r'(?:/|[\s\"\']|$)',value))

def ancestor_ids(rows):
    lookup={r['pid']:r for r in rows}; result=set(); current=os.getpid()
    while current and current not in result:
        result.add(current);current=lookup.get(current,{}).get('parent_pid',0)
    return result

def protected(row,ancestors):
    name=row['name'].casefold(); command=row['command'].casefold()
    return (row['pid'] in ancestors or name in {'codex.exe','chatgpt.exe','chrome.exe','msedge.exe'} or
            any(x in command for x in ('launch_codex_app_tools_mcp','mcp-server','mcp_server','patenttitlebot','hermes')))

def same(left,right):
    return bool(left and right and all(left[k]==right[k] for k in ('pid','created_ticks','command_sha256')))

def owned_processes(workspace,rows):
    ancestors=ancestor_ids(rows)
    return [r for r in rows if background_entry_owned(workspace,r) and not protected(r,ancestors)]

def background_entry_owned(workspace,row):
    """A path in a read/search command is not a service ownership proof."""
    if not command_owned(workspace,row.get('command','')):return False
    name=row.get('name','').casefold();command=row.get('command','').replace('\\','/')
    root=re.escape(str(Path(workspace).resolve()).replace('\\','/').rstrip('/'))
    # Require an invoked script under this case, rather than text embedded in
    # Get-Content, rg, reviewer probes, -c strings or a generic process title.
    script=r'["\']?'+root+r'/[^"\'\r\n;]*?'
    if name in {'python.exe','pythonw.exe','uv.exe'}:
        return bool(re.search(r'(?:^|\s)'+script+r'\.py(?:["\']|\s|$)',command,re.I)) and not re.search(r'(?:^|\s)-c(?:\s|$)',command)
    if name in {'node.exe','bun.exe','deno.exe'}:
        return bool(re.search(r'(?:^|\s)'+script+r'\.(?:cjs|mjs|js|ts)(?:["\']|\s|$)',command,re.I)) and not re.search(r'(?:^|\s)(?:-e|--eval)(?:\s|$)',command)
    if name in {'powershell.exe','pwsh.exe'}:
        return bool(re.search(r'(?:-File\s+|&\s+)'+script+r'\.ps1(?:["\']|\s|$)',command,re.I))
    if name=='cmd.exe':return bool(re.search(r'/[ck]\s+'+script+r'\.(?:cmd|bat)(?:["\']|\s|$)',command,re.I))
    # Unknown executables need explicit registration/tree/health evidence; keep
    # them outside automatic ownership and never kill by a mere path match.
    return False

def register(workspace,pid):
    workspace=no_links(workspace)
    record=workspace/'.product-v2/processes.json'
    if not (workspace/'.product-v2/run.json').is_file(): raise ValueError('Prepare the case first')
    rows=inventory();lookup={r['pid']:r for r in rows};current=lookup.get(pid)
    ancestors=ancestor_ids(rows)
    if not current or protected(current,ancestors) or not current['command'] or not current['created_ticks']:
        raise ValueError('Missing or protected process; registration refused')
    value=read_json(record) if record.exists() else {'workspace':str(workspace),'processes':[]}
    if value['workspace']!=str(workspace): raise ValueError('Registry workspace mismatch')
    direct=command_owned(workspace,current['command'])
    root=None
    if not direct:
        parent=current['parent_pid']; visited=set()
        while parent and parent not in visited:
            visited.add(parent);row=lookup.get(parent)
            if not row: break
            if any(same(saved,row) for saved in value['processes']) and command_owned(workspace,row['command']):
                root={k:row[k] for k in ('pid','created_ticks','command_sha256')};break
            parent=row['parent_pid']
        if root is None: raise ValueError('No bounded case path or live registered case ancestor')
    current['ownership_root']=root
    if not any(same(saved,current) for saved in value['processes']):
        value['processes'].append(current)
    write_json(record,value)
    return {'registered':pid,'name':current['name'],'ports':current['ports']}

def terminate_exact(expected):
    """Keep a kernel handle open across identity verification and termination."""
    kernel=ctypes.WinDLL('kernel32',use_last_error=True)
    kernel.OpenProcess.argtypes=[wintypes.DWORD,wintypes.BOOL,wintypes.DWORD];kernel.OpenProcess.restype=wintypes.HANDLE
    kernel.GetProcessTimes.argtypes=[wintypes.HANDLE]+[ctypes.POINTER(wintypes.FILETIME)]*4
    kernel.GetProcessTimes.restype=wintypes.BOOL
    kernel.TerminateProcess.argtypes=[wintypes.HANDLE,wintypes.UINT];kernel.TerminateProcess.restype=wintypes.BOOL
    kernel.WaitForSingleObject.argtypes=[wintypes.HANDLE,wintypes.DWORD];kernel.WaitForSingleObject.restype=wintypes.DWORD
    kernel.CloseHandle.argtypes=[wintypes.HANDLE]
    handle=kernel.OpenProcess(0x100000|0x1000|1,False,expected['pid'])
    if not handle: raise ValueError('Could not retain exact process handle')
    try:
        times=[wintypes.FILETIME() for _ in range(4)]
        if not kernel.GetProcessTimes(handle,*[ctypes.byref(x) for x in times]): raise ValueError('Creation time query failed')
        ticks=(times[0].dwHighDateTime<<32)|times[0].dwLowDateTime
        if ticks//10 != expected['created_ticks']//10: raise ValueError('PID was reused')
        rows=inventory();current=next((r for r in rows if r['pid']==expected['pid']),None)
        if not same(expected,current) or protected(current,ancestor_ids(rows)):
            raise ValueError('Process identity changed or is protected')
        if not set(current['ports']).issubset(set(expected['ports'])):
            raise ValueError('Process acquired unregistered ports; recheck exclusive ownership')
        if not kernel.TerminateProcess(handle,0): raise ValueError('Exact process termination failed')
        if kernel.WaitForSingleObject(handle,5000)!=0: raise ValueError('Process did not exit')
    finally: kernel.CloseHandle(handle)

def stop(workspace):
    workspace=no_links(workspace)
    if not (workspace/'.product-v2/run.json').is_file(): raise ValueError('Prepare the case first')
    path=workspace/'.product-v2/processes.json'
    record=read_json(path) if path.exists() else {'workspace':str(workspace),'processes':[]}
    if record['workspace']!=str(workspace): raise ValueError('Registry workspace mismatch')
    rows=inventory();lookup={r['pid']:r for r in rows};results=[]
    registered=record['processes']
    def depth(r):
        n=0;seen=set();pid=r['parent_pid']
        while pid in lookup and pid not in seen:
            seen.add(pid);n+=1;pid=lookup[pid]['parent_pid']
        return n
    for saved in sorted(registered,key=depth,reverse=True):
        # Historical exits need no new OS query; replacements are always preserved.
        initial=lookup.get(saved['pid'])
        if not same(saved,initial):
            results.append({'pid':saved['pid'],'status':'original_exited','replacement_preserved':bool(initial)});continue
        current=next((r for r in inventory() if r['pid']==saved['pid']),None)
        if not same(saved,current):
            results.append({'pid':saved['pid'],'status':'original_exited','replacement_preserved':bool(current)});continue
        try:
            if not command_owned(workspace,current['command']) and not saved.get('ownership_root'):
                raise ValueError('No saved ownership proof')
            terminate_exact(saved)
            results.append({'pid':saved['pid'],'status':'stopped'})
        except ValueError as e:
            results.append({'pid':saved['pid'],'status':'pending','reason':str(e)})
    after=inventory()
    remaining=owned_processes(workspace,after)
    for row in after:
        if any(same(row,saved) for saved in registered) and not any(same(row,r) for r in remaining): remaining.append(row)
    ports=sorted({port for saved in registered for port in saved['ports']})
    occupied=[{'port':port,'pid':row['pid']} for row in after for port in row['ports'] if port in ports]
    receipt={'status':'stopped' if not remaining and not occupied and not any(r['status']=='pending' for r in results) else 'cleanup_pending',
             'workspace':str(workspace),'processes':results,'remaining':remaining,'ports_still_listening':occupied}
    write_json(workspace/'.product-v2/cleanup.json',receipt)
    return receipt

def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('action',choices=['register','inspect','stop']);p.add_argument('--workspace',required=True);p.add_argument('--pid',type=int)
    a=p.parse_args()
    try:
        if a.action=='register':
            if not a.pid: raise ValueError('--pid required')
            value=register(a.workspace,a.pid)
        elif a.action=='inspect': value={'owned':owned_processes(a.workspace,inventory())}
        else: value=stop(a.workspace)
        print(json.dumps(value,ensure_ascii=False,indent=2))
        return 2 if value.get('status')=='cleanup_pending' else 0
    except (ValueError,OSError,subprocess.SubprocessError) as e:
        print('ERROR: '+str(e),file=sys.stderr);return 2

if __name__=='__main__':sys.exit(main())
