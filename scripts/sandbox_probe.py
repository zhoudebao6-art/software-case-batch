"""Zero-model probes through the installed CLI's existing Windows sandbox.

This never manually edits Codex configuration, permissions or runtime files,
and never stops existing processes; the official sandbox owns its own setup.
A pass covers command execution in the probed directory, not model access,
network access, unrelated case directories or final deliverables.
"""
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import tempfile
import time
import uuid


def run_probe_command(command, **kwargs):
    # A sandbox helper may inherit handles after the CLI has timed out. Files
    # keep that from making communicate() wait forever for inherited pipes.
    with tempfile.TemporaryFile() as out, tempfile.TemporaryFile() as err:
        try:
            result = subprocess.run(command, stdin=subprocess.DEVNULL, stdout=out,
                                    stderr=err, **kwargs)
        except subprocess.TimeoutExpired as exc:
            # Keep the real setup error even if a helper prevents timely exit.
            # A timeout stays a failure regardless of any printed marker.
            out.seek(0); err.seek(0)
            exc.output = out.read().decode('utf-8', 'replace')[-2400:]
            exc.stderr = err.read().decode('utf-8', 'replace')[-2400:]
            raise
        out.seek(0); err.seek(0)
        return subprocess.CompletedProcess(command, result.returncode,
            out.read().decode('utf-8', 'replace'), err.read().decode('utf-8', 'replace'))


def sandbox_log_cursor():
    root = Path(os.environ.get('CODEX_HOME') or Path.home() / '.codex') / '.sandbox'
    try:
        return {p: p.stat().st_size for p in root.glob('sandbox*.log')}
    except OSError:
        return {}


def runtime_diagnostics(before):
    """Bounded shared-log context, explicitly not attributed to a case PID."""
    lines = []
    for path, size in sandbox_log_cursor().items():
        offset = before.get(path, 0)
        if size <= offset:
            continue
        try:
            with path.open('rb') as stream:
                stream.seek(max(offset, size - 32768))
                added = stream.read(32768).decode('utf-8', 'replace')
            lines.extend(line for line in added.splitlines()
                         if re.sub(r'^\[[^]]+\]\s*', '', line).startswith(
                             'runtime read/execute validation failed:'))
        except OSError:
            continue
    return list(dict.fromkeys(re.sub(r'^\[[^]]+\]\s*', '', line)
                              for line in lines))[-4:]


def check_worker_sandbox(cfg, workspace, *, mode='workspace-write'):
    if mode not in {'workspace-write', 'read-only'}:
        raise ValueError('Only the existing restricted worker modes may be probed')
    workspace = Path(workspace).resolve(strict=True)
    from caseflow import native_codex
    from runtime_doctor import failure_kind
    cli = str(native_codex(cfg))
    report = {'name': 'worker_sandbox_' + mode, 'ok': False, 'model_calls': 0,
              'workspace': str(workspace), 'sandbox': mode, 'cli': cli}
    flags = {'creationflags': subprocess.CREATE_NO_WINDOW} if os.name == 'nt' else {}
    before = sandbox_log_cursor()
    started = time.monotonic()
    read_probe = None
    try:
        isolated_temp = workspace / '.runtime' / 'tmp'
        isolated_temp.mkdir(parents=True, exist_ok=True)
        env = {**os.environ, 'TEMP': str(isolated_temp), 'TMP': str(isolated_temp),
               'TMPDIR': str(isolated_temp)}
        help_result = run_probe_command([cli, 'help', 'sandbox'], cwd=workspace,
                                        env=env, timeout=15, **flags)
        help_text = help_result.stdout
        if help_result.returncode:
            raise RuntimeError(help_result.stderr or help_text)
        # Windows CLI versions differ: newer builds take COMMAND directly;
        # older builds expose a windows subcommand. Never execute help as a command.
        if 'Full command args to run under Windows' in help_text:
            # Recent CLIs reserve --cd for named permission profiles. Inherit
            # the subprocess cwd, as the legacy interface also does.
            sandbox_args = ['sandbox']
        elif re.search(r'^\s+windows\s', help_text, re.MULTILINE):
            sandbox_args = ['sandbox', 'windows']
        else:
            raise RuntimeError('Unsupported Windows sandbox CLI interface; inspect installed help')
        marker = 'CASEFLOW_SANDBOX_OK_' + uuid.uuid4().hex
        probe_name = '.caseflow-probe-' + uuid.uuid4().hex
        if mode == 'workspace-write':
            program = ('from pathlib import Path; '
                       f'p=Path({probe_name!r}); '
                       "f=p.open('x',encoding='ascii'); f.write('caseflow'); f.close(); "
                       "assert p.read_text(encoding='ascii')=='caseflow'; p.unlink(); "
                       f'print({marker!r})')
        else:
            read_probe = workspace / probe_name
            with read_probe.open('x', encoding='ascii') as stream:
                stream.write(marker)
            program = (f'from pathlib import Path; p=Path({probe_name!r}); '
                       f'assert p.read_text(encoding="ascii")=={marker!r}; print({marker!r})')
        command = [cli, '-c', 'sandbox_mode=' + json.dumps(mode), *sandbox_args,
                   '--', cfg['runtime']['python'], '-X', 'utf8', '-c', program]
        report['command'] = command
        # Windows cold setup can exceed 45 seconds without a policy rejection.
        # One bounded attempt, no weaker mode and no automatic paid retry.
        result = run_probe_command(command, cwd=workspace, env=env, timeout=90, **flags)
        report['exit_code'] = result.returncode
        if result.returncode or marker not in result.stdout.splitlines():
            raise RuntimeError((result.stderr or result.stdout or
                                'Sandbox probe returned no success marker')[-2400:])
        report['ok'] = True
    except (OSError, subprocess.SubprocessError, RuntimeError) as exc:
        detail = str(exc)[-2400:]
        if isinstance(exc, subprocess.TimeoutExpired):
            def tail(value):
                return (value.decode('utf-8', 'replace') if isinstance(value, bytes)
                        else str(value or ''))[-2400:]
            report.update(timed_out=True, timeout_seconds=exc.timeout,
                          stdout=tail(exc.output), stderr=tail(exc.stderr))
            detail += '\n' + (report['stderr'] or report['stdout'])
        diagnostics = runtime_diagnostics(before)
        report.update(detail=detail, shared_runtime_log_context=diagnostics)
        combined = detail + '\n' + '\n'.join(diagnostics)
        report['kind'] = failure_kind(combined)
        stable = '\n'.join(diagnostics) or re.sub(r'CASEFLOW_SANDBOX_OK_[a-f0-9]+|\.caseflow-probe-[a-f0-9]+', '<probe>', detail)
        report['fingerprint'] = hashlib.sha256(stable.encode('utf-8')).hexdigest()
    finally:
        report['elapsed_seconds'] = round(time.monotonic() - started, 3)
        if read_probe is not None:
            try:
                read_probe.unlink(missing_ok=True)
            except OSError as exc:
                report.update(ok=False, cleanup_error=str(exc))
    return report
