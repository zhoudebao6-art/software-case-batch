"""Bounded environment probes. No model calls, global settings or case mutations."""
import json
import os
from pathlib import Path
import subprocess
import tempfile
import time


def available_memory_mb():
    """Return currently available physical memory without third-party packages."""
    if os.name == 'nt':
        import ctypes
        class MemoryStatus(ctypes.Structure):
            _fields_ = [('length', ctypes.c_ulong), ('memory_load', ctypes.c_ulong),
                        ('total_phys', ctypes.c_ulonglong), ('avail_phys', ctypes.c_ulonglong),
                        ('total_page', ctypes.c_ulonglong), ('avail_page', ctypes.c_ulonglong),
                        ('total_virtual', ctypes.c_ulonglong), ('avail_virtual', ctypes.c_ulonglong),
                        ('avail_extended_virtual', ctypes.c_ulonglong)]
        status = MemoryStatus()
        status.length = ctypes.sizeof(MemoryStatus)
        if ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(status)):
            return int(status.avail_phys / (1024 * 1024))
        return None
    try:
        for line in Path('/proc/meminfo').read_text(encoding='ascii').splitlines():
            if line.startswith('MemAvailable:'):
                return int(line.split()[1]) // 1024
    except (OSError, ValueError, IndexError):
        pass
    return None


def available_commit_memory_mb():
    """Return Windows commit headroom when it is available.

    Physical RAM is not the same as the commit limit that commonly surfaces as
    ``MemoryError`` on Windows. Keep this probe separate so callers can use
    the more conservative of physical and commit headroom without changing
    the long-standing integer return contract of ``available_memory_mb``.
    """
    if os.name != 'nt':
        return None
    try:
        import ctypes
        from ctypes import wintypes
        class PerformanceInformation(ctypes.Structure):
            _fields_ = [
                ('cb', wintypes.DWORD), ('commit_total', ctypes.c_size_t),
                ('commit_limit', ctypes.c_size_t), ('commit_peak', ctypes.c_size_t),
                ('physical_total', ctypes.c_size_t), ('physical_available', ctypes.c_size_t),
                ('system_cache', ctypes.c_size_t), ('kernel_total', ctypes.c_size_t),
                ('kernel_paged', ctypes.c_size_t), ('kernel_nonpaged', ctypes.c_size_t),
                ('page_size', ctypes.c_size_t), ('handle_count', wintypes.DWORD),
                ('process_count', wintypes.DWORD), ('thread_count', wintypes.DWORD),
            ]
        info = PerformanceInformation()
        info.cb = ctypes.sizeof(info)
        if not ctypes.windll.psapi.GetPerformanceInfo(ctypes.byref(info), info.cb):
            return None
        headroom = max(0, int(info.commit_limit) - int(info.commit_total))
        return int(headroom * int(info.page_size) / (1024 * 1024))
    except (AttributeError, OSError, TypeError, ValueError):
        return None


def recording_memory_requirement_mb(cfg):
    execution = cfg.get('execution', {})
    slots = execution.get('recording_concurrency', 1)
    floor = execution.get('recording_min_available_mb', 0)
    reserve = execution.get('recording_reserve_mb', 0)
    if not all(isinstance(x, int) and x >= 0 for x in (slots, floor, reserve)):
        return 0
    return floor + max(0, slots - 1) * reserve


def recording_memory_status(cfg):
    required = recording_memory_requirement_mb(cfg)
    physical = available_memory_mb() if required else None
    commit = available_commit_memory_mb() if required else None
    readings = [x for x in (physical, commit) if x is not None]
    available = min(readings) if readings else None
    return {'name': 'recording_memory', 'ok': not required or available is None or available >= required,
            'available_mb': available, 'physical_available_mb': physical,
            'commit_available_mb': commit, 'required_mb': required,
            'measurement_available': bool(readings)}


def failure_kind(message):
    text = message.lower()
    if 'blocked by policy' in text or 'rejected by policy' in text:
        return 'policy_denied'
    if any(term in text for term in ('memoryerror', 'memory allocation', 'out of memory', 'recording memory guard')):
        return 'memory_exhausted'
    if any(term in text for term in ('os error 32', 'sharing violation', '另一个程序正在使用此文件')):
        return 'file_in_use'
    if 'setup refresh had errors' in text or 'windows sandbox failed' in text:
        return 'sandbox_setup_failed'
    if any(term in text for term in ('access denied', 'permissionerror', 'permission denied')):
        return 'permission_or_lock'
    return 'environment_error'


def check_environment(cfg, *, smoke=False, check_cli=True):
    runtime = cfg.get('runtime', {})
    errors, checks = [], []
    execution = cfg.get('execution', {})
    required_memory = recording_memory_requirement_mb(cfg)
    if required_memory:
        memory = recording_memory_status(cfg)
        physical, commit, available = (memory[k] for k in ('physical_available_mb', 'commit_available_mb', 'available_mb'))
        checks.append(memory)
        if available is not None:
            if available < required_memory:
                details = f'{available}MB effective headroom'
                if physical is not None and commit is not None:
                    details += f' (physical {physical}MB, commit {commit}MB)'
                errors.append(f'Recording memory guard: {details}, at least {required_memory}MB required for {execution.get("recording_concurrency", 1)} recording slot(s); free memory before resuming this batch; lower local recording concurrency before planning a future batch')
    for key in ('python', 'node', 'ffmpeg', 'ffprobe', 'soffice', 'pdftoppm', 'docx_renderer'):
        if not runtime.get(key) or not Path(runtime[key]).is_file():
            errors.append('Missing runtime.' + key + '; configure this machine in config.json')
    if not runtime.get('node_modules') or not (Path(runtime['node_modules']) / 'playwright/package.json').is_file():
        errors.append('Missing Playwright package; run setup.ps1 -InstallDependencies')
    if errors:
        return {'ok': False, 'errors': errors, 'checks': checks, 'model_calls': 0}

    def probe(name, command, *, timeout=30, env=None, required_marker=None):
        started = time.monotonic()
        try:
            result = subprocess.run(command, capture_output=True, text=True, encoding='utf-8',
                                    errors='replace', timeout=timeout, env=env,
                                    **({'creationflags': subprocess.CREATE_NO_WINDOW} if os.name == 'nt' else {}))
            if result.returncode:
                raise RuntimeError((result.stderr or result.stdout or str(result.returncode))[-1600:])
            if required_marker and required_marker not in result.stdout + result.stderr:
                raise RuntimeError('Installed CLI does not support configured ' + required_marker + '; update CLI without weakening approval settings')
            checks.append({'name': name, 'ok': True, 'elapsed_seconds': round(time.monotonic() - started, 3)})
            return True
        except (OSError, subprocess.SubprocessError, RuntimeError) as exc:
            detail = str(exc)[-1600:]
            checks.append({'name': name, 'ok': False, 'kind': failure_kind(detail), 'detail': detail,
                           'elapsed_seconds': round(time.monotonic() - started, 3)})
            errors.append(name + ': ' + detail)
            return False

    probe('python_packages', [runtime['python'], '-X', 'utf8', '-c',
          'import sys; assert sys.version_info >= (3,11); import PIL,lxml,pypdf,docx'])
    for key, flag in [('node', '--version'), ('ffmpeg', '-version'), ('ffprobe', '-version'), ('pdftoppm', '-v')]:
        probe(key, [runtime[key], flag])
    # Windows GUI launcher can wait on the user's existing Office profile.
    # The console launcher and a private profile never attach to that session.
    with tempfile.TemporaryDirectory(prefix='caseflow-office-version-') as temp:
        office = Path(runtime['soffice'])
        if os.name == 'nt' and office.with_suffix('.com').is_file():
            office = office.with_suffix('.com')
        probe('soffice', [str(office), '-env:UserInstallation=' + (Path(temp) / 'profile').as_uri(), '--headless', '--version'])
    if check_cli:
        from caseflow import native_codex, Blocked
        try:
            cli = str(native_codex(cfg))
            probe('codex_version', [cli, '--version'])
            # Cold credential lookup can legitimately exceed 30 seconds. Keep
            # a bounded wait and require the real successful exit, never retry
            # a rejected operation or infer login from the version command.
            probe('codex_login', [cli, 'login', 'status'], timeout=60)
            probe('codex_exec_interface', [cli, 'exec', '--help'],
                  required_marker='--approve-for-me' if cfg.get('runner', {}).get('worker_approval_mode') == 'auto_review' else '--sandbox')
            if os.name == 'nt' and not errors:
                from sandbox_probe import check_worker_sandbox
                # Probe the common runtime once before the batch fans out. This
                # does not replace each worker's own case-directory write check.
                parent = Path(cfg.get('_root', tempfile.gettempdir())) / '.runtime' / 'preflight'
                parent.mkdir(parents=True, exist_ok=True)
                with tempfile.TemporaryDirectory(prefix='sandbox-', dir=parent) as temp:
                    for mode in ('workspace-write', 'read-only'):
                        result = check_worker_sandbox(cfg, Path(temp), mode=mode)
                        checks.append(result)
                        if not result['ok']:
                            errors.append(result['name'] + ': ' + result.get('detail', 'failed'))
                            break  # No second attempt against the same shared blocker.
        except Blocked as exc:
            errors.append(str(exc))
    browser_script = """const {createRequire}=require('module');
const path=require('path');const fs=require('fs');
const {chromium}=createRequire(path.join(process.argv[1],'package.json'))('playwright');
if(!fs.existsSync(chromium.executablePath()))throw Error('Chromium missing: run playwright install chromium');
if(process.argv[2]==='smoke') (async()=>{let b;try{b=await chromium.launch({headless:true});
const p=await b.newPage();await p.setContent('<h1>Caseflow probe</h1>');
if(await p.locator('h1').innerText()!=='Caseflow probe')throw Error('Browser probe failed');}
finally{if(b)await b.close();}})().catch(e=>{console.error(e);process.exitCode=1;});"""
    probe('playwright_browser', [runtime['node'], '-e', browser_script, runtime['node_modules'],
                                'smoke' if smoke else 'check'], timeout=60)
    if smoke and not errors:
        with tempfile.TemporaryDirectory(prefix='caseflow-render-probe-') as temp:
            document = Path(temp) / 'probe.docx'
            env = dict(os.environ, CASEFLOW_SOFFICE=runtime['soffice'], CASEFLOW_PDFTOPPM=runtime['pdftoppm'])
            env['PATH'] = os.pathsep.join([str(Path(runtime['soffice']).parent), str(Path(runtime['pdftoppm']).parent), env.get('PATH','')])
            if probe('create_probe_docx', [runtime['python'], '-c',
                     "from docx import Document; import sys; d=Document();d.add_paragraph('Caseflow probe');d.save(sys.argv[1])", str(document)]):
                probe('word_render', [runtime['python'], '-X', 'utf8', runtime['docx_renderer'],
                      str(document), '--output_dir', str(Path(temp) / 'render'), '--emit_pdf'], timeout=600, env=env)
    return {'ok': not errors, 'errors': errors, 'checks': checks, 'model_calls': 0,
            'scope': 'Environment only; model entitlement and real case delivery remain unverified'}
