"""Run a case's real startup/core-flow probe against its final ZIP in isolation.

The original workspace is prepared; the extracted tree is deliberately not a
prepared case. A fresh Windows Job (POSIX session in portable tests) owns only
this invocation. No process census, shell command or process_guard registry is
needed. The case probe reads SCB_PACKAGE_ROOT / SCB_PACKAGE_RESULT from its
environment, starts the extracted software and writes its actual assertions.
"""
import argparse
import contextlib
import ctypes
from ctypes import wintypes
import json
import math
import os
from pathlib import Path, PurePosixPath
import runpy
import shutil
import signal
import subprocess
import sys
import tempfile
import time
import uuid
import zipfile
import zlib

from common import digest, inside, no_links, read_json, state, write_json, delivery_paths

MAX_MEMBERS = 20000
MAX_BYTES = 1024 * 1024 * 1024


def unpack(archive, root):
    """Validate the entire member list before creating any extracted files."""
    names, total = set(), 0
    with zipfile.ZipFile(archive) as bundle:
        members = bundle.infolist()
        if not members or len(members) > MAX_MEMBERS:
            raise ValueError('Source ZIP member count is empty or exceeds the bounded probe limit')
        for member in members:
            name = member.filename.replace('\\', '/')
            path = PurePosixPath(name)
            parts = name.rstrip('/').split('/')
            special = (member.external_attr >> 16) & 0o170000
            if (not name or path.is_absolute() or ':' in name or '\x00' in name
                    or any(p in {'', '.', '..'} or p.rstrip(' .') != p for p in parts)
                    or any(p.split('.')[0].upper() in {'CON', 'PRN', 'AUX', 'NUL',
                        *('COM' + str(i) for i in range(1, 10)),
                        *('LPT' + str(i) for i in range(1, 10))} for p in parts)
                    or special not in {0, 0o100000, 0o040000} or member.flag_bits & 1):
                raise ValueError('Unsafe, special or encrypted source ZIP member')
            key = '/'.join(parts).casefold()
            if key in names:
                raise ValueError('Duplicate Windows source ZIP path')
            names.add(key)
            total += member.file_size
            if total > MAX_BYTES:
                raise ValueError('Source ZIP exceeds the bounded unpacked-size limit')
        # No extractall: preserve one normalized path policy on every platform.
        for member in members:
            target = inside(root, member.filename.replace('\\', '/').rstrip('/'), must_exist=False)
            if member.is_dir():
                target.mkdir(parents=True, exist_ok=True)
            else:
                target.parent.mkdir(parents=True, exist_ok=True)
                with bundle.open(member) as source, target.open('xb') as output:
                    shutil.copyfileobj(source, output, 1024 * 1024)
    return {'members': len(members), 'unpacked_bytes': total}


def validate_result(value):
    if not isinstance(value, dict) or not isinstance(value.get('core_flow'), str) or not value['core_flow'].strip():
        raise ValueError('Case probe must describe its actual core_flow')
    checks = value.get('checks')
    if (not isinstance(checks, list) or not checks
            or not all(isinstance(c, dict) and isinstance(c.get('name'), str) and c['name'].strip()
                       and c.get('passed') is True for c in checks)
            or not {'startup', 'core_flow'}.issubset({c.get('kind') for c in checks})):
        raise ValueError('Case probe needs successful named startup and core_flow assertions')
    return value


def worker(probe_script, root, result, log):
    """Private entry: started suspended and assigned before case code executes."""
    root, probe_script = no_links(root), no_links(probe_script)
    os.chdir(root)
    sys.path.insert(0, str(root))
    os.environ.update(SCB_PACKAGE_ROOT=str(root), SCB_PACKAGE_RESULT=str(result))
    # A file descriptor redirect also captures descendants of the case probe.
    with open(log, 'a', encoding='utf-8', buffering=1) as stream:
        os.dup2(stream.fileno(), 1); os.dup2(stream.fileno(), 2)
        print('Executing isolated package startup/core-flow probe.', flush=True)
        sys.argv = [str(probe_script)]
        runpy.run_path(str(probe_script), run_name='__main__')


def execute(args, environment, timeout):
    """Return only exit/cleanup facts; never expose inherited command lines."""
    if os.name == 'nt':
        from media_job import Job, launch_suspended, job_pids
        name = 'Local\\SCBProPackage-' + uuid.uuid4().hex
        job, info, code, timed_out = Job(name), None, None, False
        before_close = []
        try:
            info = launch_suspended(job, args, environment)
            if job.k.ResumeThread(info.thread) == 0xffffffff:
                raise ctypes.WinError(ctypes.get_last_error())
            deadline = time.monotonic() + timeout
            while True:
                waited = job.k.WaitForSingleObject(info.process, 100)
                if waited == 0:
                    value = wintypes.DWORD()
                    if not job.k.GetExitCodeProcess(info.process, ctypes.byref(value)):
                        raise ctypes.WinError(ctypes.get_last_error())
                    code = int(value.value); break
                if waited != 258:
                    raise ValueError('Package probe process wait failed')
                if time.monotonic() >= deadline:
                    timed_out = True; break
        finally:
            try:
                before_close = job.pids()
            finally:
                job.close()  # KILL_ON_JOB_CLOSE, only this invocation's members.
                if info:
                    job.k.WaitForSingleObject(info.process, 5000)
                    job.k.CloseHandle(info.thread); job.k.CloseHandle(info.process)
        deadline = time.monotonic() + 5
        remaining = job_pids(name)
        while remaining and time.monotonic() < deadline:
            time.sleep(.05); remaining = job_pids(name)
        return {'exit_code': code, 'timed_out': timed_out, 'launcher_pid': info.pid,
                'cleanup': {'mechanism': 'windows-job', 'members_at_close': before_close,
                            'remaining_pids': remaining, 'status': 'stopped' if not remaining else 'cleanup_pending'}}
    process = subprocess.Popen(args, env=environment, start_new_session=True)
    timed_out, code = False, None
    try:
        try:
            code = process.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            timed_out = True
    finally:
        # The process group belongs to this new session; no name/path matching.
        with contextlib.suppress(ProcessLookupError):
            os.killpg(process.pid, signal.SIGTERM)
        try:
            process.wait(timeout=2)
        except subprocess.TimeoutExpired:
            with contextlib.suppress(ProcessLookupError):
                os.killpg(process.pid, signal.SIGKILL)
            process.wait(timeout=5)
        # A successfully exited parent may have left descendants in its session.
        with contextlib.suppress(ProcessLookupError):
            os.killpg(process.pid, signal.SIGKILL)
    def remaining_group():
        rows = subprocess.run(['ps', '-eo', 'pid=,pgid=,stat='], capture_output=True,
                              text=True, timeout=5, check=True).stdout.splitlines()
        return [int(parts[0]) for row in rows if len(parts := row.split()) == 3
                and int(parts[1]) == process.pid and not parts[2].startswith('Z')]
    deadline = time.monotonic() + 5
    remaining = remaining_group()
    while remaining and time.monotonic() < deadline:
        time.sleep(.05); remaining = remaining_group()
    return {'exit_code': code, 'timed_out': timed_out, 'launcher_pid': process.pid,
            'cleanup': {'mechanism': 'posix-session', 'remaining_pids': remaining,
                        'status': 'stopped' if not remaining else 'cleanup_pending'}}


def probe(workspace, probe_script, receipt, timeout=120, keep_extracted=False):
    workspace, output, run = state(workspace)
    probe_script = no_links(probe_script)
    if workspace not in probe_script.parents or not probe_script.is_file() or probe_script.suffix.lower() != '.py':
        raise ValueError('Use an actual case-specific Python probe inside the original workspace')
    if not isinstance(timeout, (int, float)) or isinstance(timeout, bool) or not math.isfinite(timeout) or not 0 < timeout <= 1800:
        raise ValueError('Timeout must be finite and in (0, 1800] seconds')
    temporary = no_links(os.environ.get('TEMP', ''))
    if os.name == 'nt' and temporary != no_links(r'D:\codex+\temp'):
        raise ValueError('Load installed Enter-Environment.ps1; TEMP must be D:\\codex+\\temp')
    if not temporary.is_dir() or any(no_links(os.environ.get(k, '')) != temporary for k in ('TMP', 'TMPDIR')):
        raise ValueError('TEMP, TMP and TMPDIR must identify the same existing private temp root')
    python = no_links(os.environ.get('SCB_PRO_PYTHON', ''))
    if not python.is_file():
        raise ValueError('Load installed Enter-Environment.ps1 to select SCB_PRO_PYTHON')
    archive = delivery_paths(run,output)['source_zip']
    package = read_json(inside(workspace, '.product-v2/source-package.json'))
    if not isinstance(package, dict):
        raise ValueError('source-package.json must contain a JSON object')
    archive_sha, probe_sha = digest(archive), digest(probe_script)
    if package.get('sha256') != archive_sha:
        raise ValueError('Final ZIP differs from source-package.json; pack the current archive first')
    receipt = no_links(receipt)
    if workspace not in receipt.parents or receipt.suffix.lower() != '.json' or receipt.exists():
        raise ValueError('Receipt must be a wholly new JSON path inside the original workspace')
    log = receipt.with_suffix('.log')
    if log.exists():
        raise ValueError('Package probe log already exists; choose a new receipt name')
    receipt.parent.mkdir(parents=True, exist_ok=True)
    # Exclusive reservation also prevents two callers from overwriting receipts.
    with receipt.open('x', encoding='utf-8') as stream:
        stream.write('{}\n')
    with log.open('x', encoding='utf-8'):
        pass
    root = Path(tempfile.mkdtemp(prefix='scb-package-', dir=temporary)).resolve()
    result = root / '.scb-package-result.json'
    report = {'schema_version': 1, 'kind': 'package-startup-probe', 'status': 'starting',
              'run_id': run['run_id'], 'workspace': str(workspace), 'source_zip_sha256': archive_sha,
              'probe_sha256': probe_sha, 'checker_sha256': digest(Path(__file__)),
              'extract_root': str(root), 'log': str(log),
              'scope': 'Real case probe execution and owned-process cleanup; assertions are not independent review.'}
    write_json(receipt, report)
    try:
        try:
            report['extraction'] = unpack(archive, root)
        except (zipfile.BadZipFile, NotImplementedError, zlib.error) as error:
            # Only normalize archive/decoder failures; process cleanup stays in execute.
            raise ValueError('Source ZIP extraction failed: ' + str(error)) from error
        if result.exists():
            raise ValueError('Source ZIP must not prefill the reserved case-probe result')
        args = [str(python), '-B', str(Path(__file__).resolve()), 'worker', '--probe', str(probe_script),
                '--root', str(root), '--result', str(result), '--log', str(log)]
        report.update(execute(args, dict(os.environ, SCB_PACKAGE_RUN_ID=run['run_id']), timeout))
        if report['cleanup']['status'] != 'stopped':
            raise ValueError('Owned package probe processes still require cleanup')
        if report['timed_out'] or report['exit_code'] != 0:
            raise ValueError('Package probe timed out or failed; inspect the private log')
        report['case_assertions'] = validate_result(read_json(no_links(result)))
        if digest(archive) != archive_sha or digest(probe_script) != probe_sha:
            raise ValueError('Final ZIP or case probe changed during execution')
        report['status'] = 'completed'
    except (ValueError, OSError, KeyError, TypeError, zipfile.BadZipFile) as error:
        report['status'] = 'failed'
        report['error'] = str(error)
    finally:
        report['log_sha256'] = digest(log)
        if report['status'] == 'completed':
            report['execution_check'] = {'kind': 'package_startup', 'command': subprocess.list2cmdline(args),
                                         'exit_code': report['exit_code'],
                                         'log': log.relative_to(workspace).as_posix(), 'sha256': report['log_sha256']}
        # Delete only the exact new root, and only after proven controlled exit.
        removed = False
        if report['status'] == 'completed' and not keep_extracted:
            try:
                checked = no_links(root)
                if temporary not in checked.parents or checked.parent != temporary or not checked.name.startswith('scb-package-'):
                    raise ValueError('Unexpected extraction cleanup boundary')
                shutil.rmtree(checked); removed = True
            except (OSError, ValueError):
                report['temp_cleanup'] = 'retained_busy'
        report['extract_root_retained'] = not removed
        write_json(receipt, report)
    return report


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='action', required=True)
    run = sub.add_parser('run')
    run.add_argument('--workspace', required=True); run.add_argument('--probe', required=True)
    run.add_argument('--receipt', required=True); run.add_argument('--timeout', type=float, default=120)
    run.add_argument('--keep-extracted', action='store_true')
    private = sub.add_parser('worker', help=argparse.SUPPRESS)
    for key in ('probe', 'root', 'result', 'log'):
        private.add_argument('--' + key, required=True)
    args = parser.parse_args(argv)
    if args.action == 'worker':
        worker(args.probe, args.root, args.result, args.log); return 0
    try:
        result = probe(args.workspace, args.probe, args.receipt, args.timeout, args.keep_extracted)
    except (ValueError, OSError, KeyError, TypeError) as error:
        result = {'status': 'blocked', 'error': str(error)}
    # Logs/assertion payloads stay private; terminal output is a small pointer.
    print(json.dumps({k: result[k] for k in ('status', 'error', 'source_zip_sha256', 'extract_root_retained') if k in result}
                     | {'receipt': str(args.receipt)}, ensure_ascii=False))
    return 0 if result['status'] == 'completed' else 2


if __name__ == '__main__':
    raise SystemExit(main())
