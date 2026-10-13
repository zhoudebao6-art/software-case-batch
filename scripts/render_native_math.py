"""Controlled native-math PDF render: shadow DOCX, verified own Office.

Only PDF display compatibility is generated here;
source and shadow DOCX bytes and original formula bodies remain unchanged.
"""
import argparse
import json
import os
from pathlib import Path
import shutil
import socket
import subprocess
import sys
import tempfile
import time


def office_tree(rows, launcher, profile_uri):
    """Derive ownership from the exact held launcher, never a port or name alone."""
    lookup = {row['pid']: row for row in rows}
    root = lookup.get(launcher['pid'])
    if not root:
        return set(), {}
    # CIM CreationDate has microsecond precision; GetProcessTimes has 100 ns.
    # Use the same precision comparison as process_guard.terminate_exact.
    if root['created_ticks'] // 10 != launcher['created_ticks'] // 10:
        raise ValueError('Held Office launcher PID was reused')
    if (root['name'].casefold() != 'soffice.com'
            or profile_uri.casefold() not in root['command'].casefold()):
        raise ValueError('Held Office launcher does not bind this unique profile')
    members = {root['pid']}
    changed = True
    while changed:
        changed = False
        for row in rows:
            parent = lookup.get(row['parent_pid'])
            if (row['pid'] not in members and row['parent_pid'] in members
                    and parent and row['created_ticks'] >= parent['created_ticks']):
                members.add(row['pid'])
                changed = True
    owned = {row['pid']: row for row in rows
             if row['pid'] in members and row['name'].casefold() in {'soffice.com', 'soffice.bin'}
             and profile_uri.casefold() in row['command'].casefold()}
    return members, owned


def verified_listener(rows, launcher, profile_uri, port):
    _, owned = office_tree(rows, launcher, profile_uri)
    listeners = [row for row in rows if port in row['ports']]
    if not listeners:
        return None
    if len(listeners) != 1:
        raise ValueError('Listener identity is not unique; no UNO connection')
    listener = listeners[0]
    if (listener['pid'] not in owned or 'port=' + str(port) not in listener['command']):
        raise ValueError('Listener is not this held Office subtree/profile; no UNO connection')
    return listener


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    for key in ('source', 'output', 'office-dir', 'pdftoppm'):
        parser.add_argument('--' + key, required=True)
    parser.add_argument('--worker-script')
    parser.add_argument('--worker-sha256')
    parser.add_argument('--source-sha256')
    parser.add_argument('--port', type=int, default=0)
    args = parser.parse_args(argv)
    # This invocation alone receives these settings; no system changes.
    os.environ.update(TEMP=r'D:\codex+\temp', TMP=r'D:\codex+\temp', TMPDIR=r'D:\codex+\temp',
                      PYTHONPYCACHEPREFIX=r'D:\codex+\cache\python-pycache',
                      PYTHONUTF8='1', PYTHONIOENCODING='utf-8')
    sys.pycache_prefix = os.environ['PYTHONPYCACHEPREFIX']
    from common import digest, no_links, read_json, write_json
    from archive_products import WindowsHandle
    from batch_control import identity
    from process_guard import inventory, same, terminate_exact

    def path(value):
        if not Path(value).is_absolute():
            raise ValueError('Explicit absolute paths are required')
        return no_links(value)

    source, output = path(args.source), path(args.output)
    office, pdftoppm = path(args.office_dir), path(args.pdftoppm)
    worker = path(args.worker_script) if args.worker_script else path(Path(__file__).with_name('native_math_worker.py'))
    if args.worker_script and not args.worker_sha256:
        raise ValueError('External worker override requires an explicit pinned hash')
    expected_worker = args.worker_sha256 or digest(worker)
    if source.suffix.casefold() != '.docx' or not source.is_file():
        raise ValueError('An existing explicit DOCX source is required')
    if output.exists() or output == Path(output.anchor):
        raise ValueError('A new non-drive-root output is required; no overwrite or adoption')
    if not all(p.is_file() for p in (office / 'soffice.com', office / 'python.exe', pdftoppm, worker)):
        raise ValueError('The already validated exact runtime paths must exist')
    if digest(worker) != expected_worker:
        raise ValueError('Pinned native-math worker hash differs')
    before = digest(source)
    if args.source_sha256 and args.source_sha256 != before:
        raise ValueError('Pinned source Word hash differs')
    from native_math_worker import math_manifest
    math_manifest(source)  # Refuse unsupported mixed colors before starting Office.
    if args.port != 0 and not 1024 <= args.port <= 65535:
        raise ValueError('Use port 0 or an explicit unprivileged loopback port')
    with socket.socket() as probe:
        probe.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
        probe.bind(('127.0.0.1', args.port))
        port = probe.getsockname()[1]
    output.mkdir(parents=True)
    task = Path(tempfile.mkdtemp(prefix='office-parent-controlled-', dir=r'D:\codex+\temp'))
    shadow = task / source.name
    profile_uri = (task / 'profile').as_uri()
    report = {'kind': 'parent-controlled-native-math-PDF-render', 'status': 'starting',
              'source': str(source), 'source_sha256': before, 'worker': str(worker),
              'worker_sha256': expected_worker, 'output': str(output), 'port': port,
              'port_free_before_launch': True, 'profile': profile_uri, 'shadow': str(shadow),
              'owned_processes': [], 'cleanup': [], 'visual_review': 'pending actual all-page viewing',
              'limitation': 'PDF native Formula color compatibility; no Word/WPS GUI or business acceptance claim'}
    process = None
    owned = {}
    started = time.monotonic()
    stdout = stderr = None

    def capture_owned():
        rows = inventory()
        members, current = office_tree(rows, report['launcher_identity'], profile_uri)
        owned.update(current)
        return rows, members

    def run_logged(command, *, prefix, filename, timeout):
        """Save actual streams even when run raises before returning a result."""
        def save(stdout_value, stderr_value, exit_code, timed_out):
            # TimeoutExpired streams can be bytes even with text=True. Keep
            # those bytes intact, including any incomplete UTF-8 character.
            def raw(value):
                return value.encode('utf-8') if isinstance(value, str) else value or b''

            stdout_bytes, stderr_bytes = raw(stdout_value), raw(stderr_value)
            log = output / filename
            stdout_log = output / (Path(filename).stem + '.stdout.log')
            stderr_log = output / (Path(filename).stem + '.stderr.log')
            stdout_log.write_bytes(stdout_bytes)
            stderr_log.write_bytes(stderr_bytes)
            log.write_bytes(stdout_bytes + b'\n' + stderr_bytes)
            report.update({prefix + '_exit_code': exit_code,
                           prefix + '_timed_out': timed_out,
                           prefix + '_timeout_seconds': timeout,
                           prefix + '_log': str(log), prefix + '_log_sha256': digest(log),
                           prefix + '_stdout_log': str(stdout_log),
                           prefix + '_stdout_sha256': digest(stdout_log),
                           prefix + '_stderr_log': str(stderr_log),
                           prefix + '_stderr_sha256': digest(stderr_log)})

        try:
            result = subprocess.run(command, capture_output=True, text=True, encoding='utf-8',
                                    timeout=timeout, creationflags=subprocess.CREATE_NO_WINDOW)
        except subprocess.TimeoutExpired as error:
            save(error.stdout, error.stderr, None, True)
            raise
        save(result.stdout, result.stderr, result.returncode, False)
        return result

    try:
        with WindowsHandle(source) as held_source, WindowsHandle(worker) as held_worker:
            if held_source.sha256() != before or held_worker.sha256() != expected_worker:
                raise ValueError('Source or pinned worker changed before protected copy')
            shutil.copy2(source, shadow)
            if digest(shadow) != before:
                raise ValueError('Shadow copy differs from the protected DOCX')
            command = [str(office / 'soffice.com'), '-env:UserInstallation=' + profile_uri,
                       '--headless', '--norestore', '--nodefault', '--nofirststartwizard',
                       '--accept=socket,host=127.0.0.1,port=' + str(port) + ';urp;StarOffice.ServiceManager']
            report['launcher_command'] = subprocess.list2cmdline(command)
            stdout = (output / 'office-service.stdout.log').open('wb')
            stderr = (output / 'office-service.stderr.log').open('wb')
            process = subprocess.Popen(command, stdout=stdout, stderr=stderr,
                                       creationflags=subprocess.CREATE_NO_WINDOW)
            report['launcher_pid'] = process.pid
            report['launcher_identity'] = identity(process.pid)
            if not report['launcher_identity']:
                raise ValueError('Held Office launcher identity is unavailable')
            deadline = time.monotonic() + 50
            while time.monotonic() < deadline:
                rows, _ = capture_owned()
                listener = verified_listener(rows, report['launcher_identity'], profile_uri, port)
                if listener:
                    report['verified_listener'] = listener
                    break
                if process.poll() is not None:
                    raise ValueError('Own Office launcher exited before a verified listener')
                time.sleep(.25)
            else:
                raise ValueError('No verified own Office listener before timeout')
            if identity(process.pid) != report['launcher_identity'] or process.poll() is not None:
                raise ValueError('Held Office launcher changed before UNO dispatch')
            cmd = [str(office / 'python.exe'), str(worker), '--source', str(shadow), '--output', str(output),
                   '--port', str(port), '--launcher-pid', str(process.pid),
                   '--launcher-created-ticks', str(report['launcher_identity']['created_ticks']),
                   '--listener-pid', str(listener['pid']), '--listener-created-ticks', str(listener['created_ticks']),
                   '--profile-uri', profile_uri]
            report['worker_command'] = subprocess.list2cmdline(cmd)
            result = run_logged(cmd, prefix='worker', filename='uno-worker.log', timeout=150)
            if result.returncode:
                raise ValueError('Pinned worker failed; preserve its actual log')
            if digest(source) != before or digest(shadow) != before or digest(worker) != expected_worker:
                raise ValueError('Protected source, shadow or worker hash changed')
            process.wait(timeout=20)
            mapping_path = output / 'math-color-render-mapping.json'
            mapping = read_json(mapping_path)
            if mapping['source_sha256'] != before:
                raise ValueError('Native math mapping source hash differs')
            for item in mapping['expected']:
                expected = ('color hex FF0000 { ' + item['native_formula_before'] + ' }'
                            if item['explicit_red'] else item['native_formula_before'])
                if item['native_formula_after'] != expected:
                    raise ValueError('Native formula body differs from its unchanged body/color wrapper')
            pdf = output / (source.stem + '.pdf')
            raster = run_logged([str(pdftoppm), '-png', '-r', '144', str(pdf), str(output / 'page')],
                                prefix='raster', filename='pdftoppm.log', timeout=300)
            if raster.returncode:
                raise ValueError('Actual PDF page rendering failed')
            pages = sorted(output.glob('page-*.png'), key=lambda item: int(item.stem.split('-')[-1]))
            if not pages:
                raise ValueError('No actual rendered pages')
            report.update(status='rendered', pdf=str(pdf), pdf_sha256=digest(pdf),
                          pages=[{'path': str(page), 'sha256': digest(page)} for page in pages],
                          mapping=str(mapping_path), mapping_sha256=digest(mapping_path),
                          math_objects=len(mapping['expected']),
                          explicit_red_objects=sum(item['explicit_red'] for item in mapping['expected']))
    except Exception as error:
        report.update(status='failed', error=str(error))
    finally:
        if process:
            try:
                try:
                    rows, _ = capture_owned()
                except Exception as error:
                    # A reused/changed launcher must not suppress cleanup of
                    # independently verified originals or authorize its replacement.
                    report['ownership_recheck_error'] = str(error)
                    rows = inventory()
                for saved in sorted(owned.values(), key=lambda row: row['pid'] == process.pid):
                    current = next((row for row in rows if row['pid'] == saved['pid']), None)
                    if same(saved, current):
                        fresh = next((row for row in inventory() if row['pid'] == saved['pid']), None)
                        if same(saved, fresh):
                            terminate_exact(saved)
                            report['cleanup'].append({'pid': saved['pid'], 'status': 'own_verified_process_stopped'})
                        else:
                            report['cleanup'].append({'pid': saved['pid'], 'status': 'original_exited_replacement_preserved'})
                    else:
                        report['cleanup'].append({'pid': saved['pid'], 'status': 'original_exited_replacement_preserved'})
                after = inventory()
                remaining = [row for row in after if any(same(row, saved) for saved in owned.values())]
                occupied = [row for row in after if port in row['ports']]
                launcher_remains = identity(process.pid) == report.get('launcher_identity')
                report.update(owned_processes=list(owned.values()), remaining=remaining,
                              ports_still_listening=occupied, launcher_still_alive=launcher_remains)
                if remaining or occupied or launcher_remains:
                    report.update(status='cleanup_pending', error='Verified Office process or port remains; unrelated processes preserved')
            except Exception as error:
                report.update(status='cleanup_pending', cleanup_error=str(error))
        if stdout:
            stdout.close()
        if stderr:
            stderr.close()
        report.update(source_unchanged=digest(source) == before,
                      shadow_sha256=digest(shadow) if shadow.is_file() else None,
                      elapsed_seconds=round(time.monotonic() - started, 3))
        if not report['source_unchanged'] or report['shadow_sha256'] != before:
            report.update(status='failed', error='Source/shadow Word identity differs')
        write_json(output / 'controlled-render.json', report)
    print(json.dumps({'report': str(output / 'controlled-render.json'), 'status': report['status'],
                      'error': report.get('error'), 'pages': report.get('pages'),
                      'elapsed_seconds': report['elapsed_seconds']}, ensure_ascii=False, indent=2))
    return 0 if report['status'] == 'rendered' else 2


if __name__ == '__main__':
    raise SystemExit(main())
