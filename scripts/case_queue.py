"""Fair cross-process admission; retains the original per-slot byte locks."""
from contextlib import contextmanager
import ctypes
import json
import os
from pathlib import Path
import time
import uuid


def process_token(pid):
    if os.name == 'nt':
        from ctypes import wintypes
        kernel=ctypes.WinDLL('kernel32',use_last_error=True)
        kernel.OpenProcess.argtypes=[wintypes.DWORD,wintypes.BOOL,wintypes.DWORD]
        kernel.OpenProcess.restype=wintypes.HANDLE
        kernel.CloseHandle.argtypes=[wintypes.HANDLE]
        kernel.GetExitCodeProcess.argtypes=[wintypes.HANDLE,ctypes.POINTER(wintypes.DWORD)]
        kernel.GetProcessTimes.argtypes=[wintypes.HANDLE,*([ctypes.POINTER(wintypes.FILETIME)]*4)]
        handle=kernel.OpenProcess(0x1000,False,pid)
        if not handle:
            return None if ctypes.get_last_error()==87 else 'unknown'
        try:
            exit_code=wintypes.DWORD()
            if kernel.GetExitCodeProcess(handle,ctypes.byref(exit_code)) and exit_code.value != 259:
                return None
            values=[wintypes.FILETIME() for _ in range(4)]
            if not kernel.GetProcessTimes(handle,*[ctypes.byref(v) for v in values]):
                return 'unknown'
            return str((values[0].dwHighDateTime<<32)|values[0].dwLowDateTime)
        finally:
            kernel.CloseHandle(handle)
    try:
        os.kill(pid,0)
        source=Path(f'/proc/{pid}/stat')
        return source.read_text().rsplit(')',1)[1].split()[19] if source.exists() else 'unknown'
    except ProcessLookupError:
        return None
    except (PermissionError,OSError):
        return 'unknown'


def priority(ticket):
    control=ticket.get('control')
    value=ticket.get('priority',0)
    if control and Path(control).is_file():
        try:
            data=json.loads(Path(control).read_text(encoding='utf-8'))
            value=data.get('case_priorities',{}).get(ticket.get('case_id'),data.get('priority',value))
        except (OSError,ValueError):
            pass
    return value if type(value) is int and -100<=value<=100 else 0


@contextmanager
def fair_slot(root, limit, lock_factory, busy_type, write_json, *, owner=None, checkpoint=None):
    root=Path(root); queue=root/'queue'; queue.mkdir(parents=True,exist_ok=True)
    guard_dir=root/'queue-guard'; guard_dir.mkdir(exist_ok=True)
    token=uuid.uuid4().hex
    ticket={'pid':os.getpid(),'process_token':process_token(os.getpid()),'queued_ns':time.time_ns(),'token':token,**(owner or {})}
    filename=queue/(token+'.json')
    write_json(filename,ticket)
    acquired=None
    try:
        while acquired is None:
            if checkpoint:
                checkpoint()
            guard=lock_factory(guard_dir)
            try:
                guard.__enter__()
            except busy_type:
                time.sleep(.05)
                continue
            try:
                tickets=[]
                for path in queue.glob('*.json'):
                    # atomic_json stages .state-*.json beside the final ticket.
                    # Only published UUID ticket names belong to the queue.
                    if path.name.startswith('.'):
                        continue
                    if path.is_symlink():
                        raise ValueError('Linked queue ticket refused')
                    try:
                        item=json.loads(path.read_text(encoding='utf-8'))
                    except FileNotFoundError:
                        # A waiting owner may withdraw its ticket at a drain checkpoint.
                        continue
                    live=process_token(item['pid'])
                    if live is None or (live!='unknown' and item.get('process_token') not in (live,'unknown')):
                        path.unlink()  # Only dead/reused process tickets, never another live lock.
                        continue
                    tickets.append(item)
                tickets.sort(key=lambda item:(-priority(item),item['queued_ns'],item['token']))
                if token in {item['token'] for item in tickets[:limit]}:
                    for index in range(limit):
                        directory=root/str(index);directory.mkdir(exist_ok=True)
                        candidate=lock_factory(directory)
                        try:
                            candidate.__enter__()
                        except busy_type:
                            continue
                        acquired=candidate
                        filename.unlink()
                        break
            finally:
                guard.__exit__(None,None,None)
            if acquired is None:
                time.sleep(.1)
        if checkpoint:
            checkpoint()
        yield
    finally:
        if acquired is not None:
            acquired.__exit__(None,None,None)
        filename.unlink(missing_ok=True)
