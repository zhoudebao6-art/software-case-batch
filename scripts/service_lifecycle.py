"""Ownership-only Windows service identity helpers.

The batch runner never stops a process by a generic name.  A service must be
bound to its listening port, PID, creation time and command line before any
recording or cleanup action is allowed.
"""
import hashlib
import json
import os
from pathlib import Path
import subprocess
import time


class IdentityError(RuntimeError):
    pass


def _powershell_json(script):
    if os.name != 'nt':
        raise IdentityError('OS listener identity verification requires Windows PowerShell')
    try:
        prefix = "$ErrorActionPreference='Stop'; [Console]::OutputEncoding=[Text.UTF8Encoding]::new($false); "
        result = subprocess.run(
            ['powershell.exe', '-NoProfile', '-NonInteractive', '-Command', prefix + script],
            capture_output=True, text=True, encoding='utf-8', errors='replace', timeout=15,
            creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
    except (OSError, subprocess.SubprocessError) as exc:
        raise IdentityError(f'PowerShell identity probe failed: {exc}') from exc
    if result.returncode:
        raise IdentityError((result.stderr or result.stdout or 'identity probe failed').strip()[-1600:])
    try:
        value = json.loads(result.stdout)
    except ValueError as exc:
        raise IdentityError('PowerShell identity probe returned invalid JSON') from exc
    if not isinstance(value, dict):
        raise IdentityError('PowerShell identity probe returned a non-object')
    return value


def listener_identity(port):
    if type(port) is not int or not 1 <= port <= 65535:
        raise IdentityError('Invalid listener port')
    script = ("$connections=@(Get-NetTCPConnection -State Listen -ErrorAction Stop); "
              "$owners=@($connections | Where-Object { $_.LocalPort -eq %d -and $_.LocalAddress -in @('127.0.0.1','0.0.0.0','::') } | "
              "Select-Object -ExpandProperty OwningProcess -Unique); "
              "if($owners.Count -eq 0){'{\"absent\":true}'; exit 0}; "
              "if($owners.Count -ne 1){throw 'Ambiguous local listener ownership'}; "
              "$p=Get-CimInstance Win32_Process -Filter ('ProcessId = ' + $owners[0]); "
              "if(-not $p){throw 'Listener process disappeared'}; "
              "$creation=$p.CreationDate.ToUniversalTime(); "
              "[pscustomobject]@{pid=[int]$p.ProcessId; created_at=$creation.ToString('o'); "
              "command_line=[string]$p.CommandLine; "
              "listener_ports=@($connections | Where-Object {$_.OwningProcess -eq $p.ProcessId} | Select-Object -ExpandProperty LocalPort -Unique)} | ConvertTo-Json -Compress") % port
    value = _powershell_json(script)
    if value.get('absent') is True:
        return None
    if type(value.get('pid')) is not int or value['pid'] <= 0:
        raise IdentityError('Listener identity has no positive PID')
    if not isinstance(value.get('created_at'), str) or not value['created_at'].strip():
        raise IdentityError('Listener identity has no process creation time')
    if not isinstance(value.get('command_line'), str) or not value['command_line'].strip():
        raise IdentityError('Listener identity has no command line')
    value['port'] = port
    value['command_line_sha256'] = hashlib.sha256(value['command_line'].encode('utf-8')).hexdigest()
    return value


def same_process(left, right):
    return isinstance(left, dict) and isinstance(right, dict) and all(
        left.get(k) == right.get(k) and left.get(k) is not None
        for k in ('pid', 'port', 'created_at', 'command_line_sha256'))


def case_owns_command(case, command):
    """Require a full, bounded case path; relative commands are not proof."""
    import re
    command = command.replace('\\', '/').casefold()
    case_path = str(Path(case).resolve()).replace('\\', '/').rstrip('/').casefold()
    if any(term in command for term in ('patenttitlebot', 'hermes')):
        return False
    return bool(re.search(r'(?:^|[\s\"\'=])' + re.escape(case_path) + r'(?:/|[\s\"\']|$)', command))


def capture_identity(case, ports, plan):
    """Read-only; missing ownership evidence delays cleanup, not the delivery."""
    from urllib.parse import urlsplit
    try:
        live = listener_identity(urlsplit(plan['base_url']).port)
        if live is None:
            raise IdentityError('Listener absent')
        owned = (case_owns_command(case, live['command_line']) and
                 set(live['listener_ports']).issubset(set(ports)))
        return {'status': 'verified' if owned else 'unproven', 'identity': live,
                'case_id': plan['case_id'], 'workspace': str(Path(case).resolve()),
                'version': plan['version'], 'assigned_ports': list(ports)}
    except (IdentityError, KeyError, TypeError, ValueError) as exc:
        return {'status': 'unproven', 'reason': str(exc)}


def terminate_verified(expected):
    """Retain a Windows handle so a recycled PID can never redirect the stop."""
    if os.name != 'nt':
        raise IdentityError('Automatic service cleanup is Windows-only')
    import ctypes
    from ctypes import wintypes
    from datetime import datetime, timedelta, timezone
    kernel = ctypes.WinDLL('kernel32', use_last_error=True)
    kernel.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    kernel.OpenProcess.restype = wintypes.HANDLE
    kernel.GetProcessTimes.argtypes = [wintypes.HANDLE] + [ctypes.POINTER(wintypes.FILETIME)] * 4
    kernel.GetProcessTimes.restype = wintypes.BOOL
    kernel.TerminateProcess.argtypes = [wintypes.HANDLE, wintypes.UINT]
    kernel.TerminateProcess.restype = wintypes.BOOL
    kernel.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
    kernel.WaitForSingleObject.restype = wintypes.DWORD
    kernel.CloseHandle.argtypes = [wintypes.HANDLE]
    handle = kernel.OpenProcess(0x100000 | 0x1000 | 0x0001, False, expected['pid'])
    if not handle:
        raise IdentityError('OpenProcess for exact service failed: ' + str(ctypes.WinError(ctypes.get_last_error())))
    try:
        creation, end, system, user = (wintypes.FILETIME() for _ in range(4))
        if not kernel.GetProcessTimes(handle, ctypes.byref(creation), ctypes.byref(end), ctypes.byref(system), ctypes.byref(user)):
            raise IdentityError('Cannot read retained process creation time')
        ticks = (creation.dwHighDateTime << 32) | creation.dwLowDateTime
        actual = datetime(1601, 1, 1, tzinfo=timezone.utc) + timedelta(microseconds=ticks // 10)
        if actual != datetime.fromisoformat(expected['created_at'].replace('Z', '+00:00')):
            raise IdentityError('Process creation changed before cleanup')
        # Recheck command and all listener ports while this exact handle is held.
        live = listener_identity(expected['port'])
        if not same_process(expected, live) or set(live['listener_ports']) != set(expected['listener_ports']):
            raise IdentityError('Service ownership changed before cleanup')
        if not kernel.TerminateProcess(handle, 0):
            raise IdentityError('Exact service termination failed: ' + str(ctypes.WinError(ctypes.get_last_error())))
        if kernel.WaitForSingleObject(handle, 5000) != 0:
            raise IdentityError('Service did not exit within cleanup deadline')
    finally:
        kernel.CloseHandle(handle)


def cleanup_after_delivery(case, case_id, report, *, in_flight=False):
    """Only the delivered case's verified listener; no launchers/process trees."""
    from runtime_doctor import available_commit_memory_mb, failure_kind
    receipt = {'case_id': case_id, 'workspace': str(Path(case).resolve()),
               'checked_at': time.time(), 'status': 'pending',
               'commit_available_before_mb': available_commit_memory_mb()}
    try:
        if in_flight or (Path(case) / '.runtime/keep-online.json').exists():
            raise IdentityError('Case still in use or explicitly marked keep-online')
        proof = report.get('service_process') or {}
        plan = report.get('service_plan') or {}
        if (proof.get('status') != 'verified' or proof.get('case_id') != case_id or
                proof.get('workspace') != str(Path(case).resolve()) or
                plan.get('version') != proof.get('version') or plan.get('case_id') != case_id):
            raise IdentityError('No current parent-captured exclusive service identity')
        expected = proof['identity']
        receipt['before'] = expected
        live = listener_identity(expected['port'])
        if live is None:
            # No claim about the old PID; it might still be running without a listener.
            raise IdentityError('Port is free; process exit still requires owner verification')
        if (not same_process(expected, live) or not case_owns_command(case, live['command_line']) or
                not set(live['listener_ports']).issubset(set(proof['assigned_ports']))):
            raise IdentityError('Live process/ports no longer match the exclusive case service')
        from capture_runner import service_ready
        service_ready(case, case_id, plan, timeout=3)
        terminate_verified(live)
        remaining = listener_identity(expected['port'])
        receipt['after_listener'] = remaining
        if remaining is not None:
            raise IdentityError('Listener remains or was replaced after cleanup; no further stop attempted')
        receipt['status'] = 'stopped'
    except (IdentityError, ValueError, KeyError, TypeError, OSError) as exc:
        receipt.update(reason=str(exc), failure_kind=failure_kind(str(exc)))
    receipt['commit_available_after_mb'] = available_commit_memory_mb()
    return receipt


if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser(description='Read-only local listener identity; no process is stopped')
    parser.add_argument('--port', type=int, required=True)
    args = parser.parse_args()
    print(json.dumps(listener_identity(args.port), ensure_ascii=False, indent=2))
