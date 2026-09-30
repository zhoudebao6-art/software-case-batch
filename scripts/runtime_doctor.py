"""Bounded environment probes. No model calls, global settings or case mutations."""
import json
import os
from pathlib import Path
import subprocess
import tempfile


def failure_kind(message):
    text = message.lower()
    if 'blocked by policy' in text or 'rejected by policy' in text:
        return 'policy_denied'
    if any(term in text for term in ('memoryerror', 'memory allocation', 'out of memory')):
        return 'memory_exhausted'
    if any(term in text for term in ('access denied', 'permissionerror', 'permission denied')):
        return 'permission_or_lock'
    return 'environment_error'


def check_environment(cfg, *, smoke=False, check_cli=True):
    runtime = cfg.get('runtime', {})
    errors, checks = [], []
    for key in ('python', 'node', 'ffmpeg', 'ffprobe', 'soffice', 'pdftoppm', 'docx_renderer'):
        if not runtime.get(key) or not Path(runtime[key]).is_file():
            errors.append('Missing runtime.' + key + '; configure this machine in config.json')
    if not runtime.get('node_modules') or not (Path(runtime['node_modules']) / 'playwright/package.json').is_file():
        errors.append('Missing Playwright package; run setup.ps1 -InstallDependencies')
    if errors:
        return {'ok': False, 'errors': errors, 'checks': checks, 'model_calls': 0}

    def probe(name, command, *, timeout=30, env=None, required_marker=None):
        try:
            result = subprocess.run(command, capture_output=True, text=True, encoding='utf-8',
                                    errors='replace', timeout=timeout, env=env,
                                    **({'creationflags': subprocess.CREATE_NO_WINDOW} if os.name == 'nt' else {}))
            if result.returncode:
                raise RuntimeError((result.stderr or result.stdout or str(result.returncode))[-1600:])
            if required_marker and required_marker not in result.stdout + result.stderr:
                raise RuntimeError('Installed CLI does not support configured ' + required_marker + '; update CLI without weakening approval settings')
            checks.append({'name': name, 'ok': True})
            return True
        except (OSError, subprocess.SubprocessError, RuntimeError) as exc:
            detail = str(exc)[-1600:]
            checks.append({'name': name, 'ok': False, 'kind': failure_kind(detail), 'detail': detail})
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
            probe('codex_login', [cli, 'login', 'status'])
            probe('codex_exec_interface', [cli, 'exec', '--help'],
                  required_marker='--approve-for-me' if cfg.get('runner', {}).get('worker_approval_mode') == 'auto_review' else '--sandbox')
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
