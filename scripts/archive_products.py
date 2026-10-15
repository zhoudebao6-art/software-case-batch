"""Receipt-bound weekly archives. No model calls, broad product scan, or scheduling."""
import argparse
from contextlib import ExitStack, contextmanager
import ctypes
import hashlib
import json
import os
from pathlib import Path
import shutil
import stat
import time

from common import digest, inside, no_links, read_json, write_json, delivery_paths
from batch_control import identity, transaction


def absolute(value):
    if not Path(value).is_absolute():
        raise ValueError('Explicit absolute paths are required')
    return no_links(value)


def roots(source_root, destination_root, batch_root, state_root):
    paths = [absolute(p) for p in (source_root, destination_root, batch_root, state_root)]
    for i, path in enumerate(paths):
        if path == Path(path.anchor):
            raise ValueError('A whole drive cannot be an archive root')
        for other in paths[i + 1:]:
            if path == other or path in other.parents or other in path.parents:
                raise ValueError('Archive, batch and state roots must be disjoint')
    if not paths[0].is_dir() or not paths[2].is_dir():
        raise ValueError('Source and authoritative batch roots must already exist')
    # Never mkdir a disconnected volume or silently select a different drive.
    if not paths[1].is_dir():
        raise ValueError('Destination root is missing or disconnected; source retained')
    return paths


def product_path(source_root, path):
    path = absolute(path)
    try:
        rel = path.relative_to(source_root)
    except ValueError:
        raise ValueError('Published product lies outside the explicit source root') from None
    if len(rel.parts) != 3 or rel.parts[0] != '批次':
        raise ValueError('Only 批次/<batch>/<case> published products are eligible')
    return path, rel


def snapshot(root, *, allow_empty=False, read_hash=True):
    """Walk explicit product only, refusing links before descending."""
    root = no_links(root)
    files = {}
    if not root.is_dir():
        raise ValueError('Product directory is missing')
    pending = [root]
    while pending:
        directory = pending.pop()
        no_links(directory)
        for path in sorted(directory.iterdir()):
            no_links(path)
            value = path.lstat()
            if stat.S_ISDIR(value.st_mode):
                pending.append(path)
            elif stat.S_ISREG(value.st_mode):
                files[path.relative_to(root).as_posix()] = {
                    'size': value.st_size, 'sha256': digest(path) if read_hash else None,
                    'inode': value.st_ino, 'device': value.st_dev,
                    'mtime_ns': value.st_mtime_ns,
                }
            else:
                raise ValueError('Non-regular product entry refused')
    if not files and not allow_empty:
        raise ValueError('Empty product refused')
    return files


def hashes(files):
    return {name: value['sha256'] for name, value in files.items()}


def directory_tree(root):
    root = no_links(root)
    pending, result = [root], []
    while pending:
        for path in pending.pop().iterdir():
            no_links(path)
            if path.is_dir():
                pending.append(path)
                result.append(path.relative_to(root).as_posix())
    return sorted(result)


def content(files):
    return {name: {key: value[key] for key in ('size', 'sha256')} for name, value in files.items()}


def check_manifest_files(files):
    if not isinstance(files, dict) or not files:
        raise ValueError('Complete receipt file hashes required')
    for rel, sha in files.items():
        if (not isinstance(rel, str) or '\\' in rel or Path(rel).is_absolute()
                or '..' in Path(rel).parts or ':' in rel or
                not isinstance(sha, str) or len(sha) != 64 or
                any(ch not in '0123456789abcdef' for ch in sha)):
            raise ValueError('Unsafe receipt relative path/hash')


def blockers(batch_root, batch_id=None, case_id=None):
    """Verified live media, or the requested batch/case's work, blocks archiving."""
    pool = read_json(inside(batch_root, 'queue.json'))
    if not isinstance(pool, list):
        raise ValueError('Authoritative queue must be a list')
    blocked = []
    for ticket in pool:
        if ticket.get('status') != 'active':
            continue
        related = (batch_id is not None and ticket.get('batch_id') == batch_id
                   and (case_id is None or ticket.get('case_id') == case_id))
        if ticket.get('stage') not in {'record', 'evidence'} and not related:
            continue
        owner = ticket.get('owner')
        if not isinstance(owner, dict) or 'pid' not in owner or 'created_ticks' not in owner:
            raise ValueError('Active queue ownership cannot be verified; retain source')
        live = identity(owner['pid']) == owner
        runtime = ticket.get('media_runtime')
        if runtime:
            runtime_identity = runtime.get('identity')
            if (not isinstance(runtime_identity, dict) or runtime_identity.get('pid') != runtime.get('pid')
                    or 'created_ticks' not in runtime_identity):
                raise ValueError('Media runtime identity cannot be verified')
            live |= identity(runtime_identity['pid']) == runtime_identity
            if runtime.get('job_name'):
                from media_job import job_name, job_pids
                expected_job = job_name(batch_root, ticket['batch_id'], ticket['token'])
                if runtime['job_name'] != expected_job:
                    raise ValueError('Media job belongs to a different reservation')
                # The registered root may have exited while its protected job
                # still contains a real FFmpeg/Chromium child.
                live |= bool(job_pids(expected_job))
        if live:
            blocked.append({'batch_id': ticket['batch_id'], 'case_id': ticket['case_id'],
                            'stage': ticket['stage']})
    return blocked


def receipt_case(source_root, destination_root, target, manifest, case):
    workspace = absolute(case['workspace'])
    state = read_json(inside(target, 'state.json'))['cases'][case['case_id']]
    if state.get('phase') != 'delivered':
        raise ValueError('Case is unfinished or under revision')
    run_path = inside(workspace, '.product-v2/run.json')
    final_path = inside(workspace, '.product-v2/final-receipt.json')
    publish_path = inside(workspace, '.product-v2/publish-receipt.json')
    run, final, published = map(read_json, (run_path, final_path, publish_path))
    delivery=delivery_paths(run)
    if ('delivery_layout_version' in final and final['delivery_layout_version']!=delivery['version']):
        raise ValueError('Current layout differs from frozen acceptance')
    if (run.get('workspace') != str(workspace) or run.get('status') != 'published'
            or final.get('status') != 'complete' or
            final.get('delivery_state') != 'verified-candidate' or
            published.get('status') != 'published' or
            published.get('source_receipt_sha256') != digest(final_path) or
            published.get('files') != final.get('files') or
            run.get('output') != published.get('destination')):
        raise ValueError('Current frozen acceptance/publication identity differs')
    check_manifest_files(final['files'])
    proof = absolute(final['execution_evidence'])
    if digest(proof) != final.get('evidence_sha256'):
        raise ValueError('Independent acceptance proof changed')
    source, rel = product_path(source_root, published['destination'])
    destination = no_links(destination_root / rel)
    if any(workspace == product or workspace in product.parents or product in workspace.parents
           for product in (source, destination)):
        raise ValueError('Workspace overlaps product')
    key = hashlib.sha256((str(source) + '\n' + digest(publish_path)).encode()).hexdigest()
    return {'schema_version': 1, 'archive_id': key, 'batch_id': manifest['batch_id'],
            'case_id': case['case_id'], 'workspace': str(workspace), 'source': str(source),
            'destination': str(destination), 'source_root': str(source_root),
            'destination_root': str(destination_root), 'files': final['files'],
            'receipt_sha256': digest(final_path), 'publication_sha256': digest(publish_path),
            'proof_sha256': digest(proof), 'run_sha256': digest(run_path)}


def resolve_location(state_root, original, expected_files=None):
    """Separate locator; frozen signed receipts and run paths remain untouched."""
    original = absolute(original)
    index_path = absolute(state_root) / 'current-locations.json'
    if not index_path.is_file():
        return original
    entry = read_json(index_path).get(str(original))
    if not entry:
        return original
    destination = absolute(entry['destination'])
    root = absolute(entry['destination_root'])
    _, rel = product_path(absolute(entry['source_root']), original)
    if destination != no_links(root / rel):
        raise ValueError('Archive locator escapes its recorded roots')
    if expected_files is not None and entry['files'] != expected_files:
        raise ValueError('Archive locator belongs to a different product version')
    if hashes(snapshot(destination)) != entry['files']:
        raise ValueError('Archived product changed; locator cannot certify bytes')
    return destination


def batch_readiness(source_root, destination_root, batch_root, target, manifest):
    """Only an entirely delivered, published and inactive batch may archive."""
    cases = manifest.get('cases')
    if not isinstance(cases, list) or not cases:
        raise ValueError('Registered batch requires a nonempty explicit case list')
    ids = [case['case_id'] for case in cases]
    if len(set(ids)) != len(ids):
        raise ValueError('Registered batch has duplicate case identities')
    rows = [receipt_case(source_root, destination_root, target, manifest, case) for case in cases]
    active = blockers(batch_root, manifest['batch_id'])
    if active:
        raise ValueError('Verified active batch work/media: ' + json.dumps(active))
    return rows


def plan(source_root, destination_root, batch_root, state_root):
    source_root, destination_root, batch_root, state_root = roots(
        source_root, destination_root, batch_root, state_root)
    blockers(batch_root)  # Fail closed on missing or malformed authoritative queue.
    result = {'eligible': [], 'retained': [], 'already_archived': []}
    # Only explicit registered batch manifests; never scan the source drive/tree.
    for target in sorted(batch_root.iterdir()):
        no_links(target)
        if not target.is_dir() or not (target / 'manifest.json').is_file():
            continue
        manifest = read_json(inside(target, 'manifest.json'))
        if manifest.get('batch_id') != target.name:
            raise ValueError('Registered batch path/identity differs')
        try:
            rows = batch_readiness(source_root, destination_root, batch_root, target, manifest)
        except (ValueError, OSError, KeyError, TypeError) as exc:
            result['retained'].extend({'batch_id': manifest['batch_id'], 'case_id': case['case_id'],
                                      'reason': 'Batch not ready: ' + str(exc)} for case in manifest['cases'])
            continue
        eligible, retained, already_archived = [], [], []
        for row in rows:
            item = {'batch_id': row['batch_id'], 'case_id': row['case_id']}
            try:
                active = blockers(batch_root, row['batch_id'], row['case_id'])
                if active:
                    raise ValueError('Verified active work/media: ' + json.dumps(active))
                source = Path(row['source'])
                if not source.exists():
                    located = resolve_location(state_root, source, row['files'])
                    if located == source:
                        raise ValueError('Source missing without a verified archive locator')
                    already_archived.append(row)
                    continue
                intent_path = state_root / 'archives' / (row['archive_id'] + '.json')
                intent = read_json(intent_path) if intent_path.exists() else None
                current = snapshot(source, allow_empty=bool(intent and intent.get('status') == 'source-cleanup-started'))
                if intent and intent.get('status') == 'source-cleanup-started':
                    if any(intent['source_snapshot'].get(k) != v for k, v in current.items()):
                        raise ValueError('Source changed during interrupted cleanup')
                    if set(directory_tree(source)) - set(intent['directories']):
                        raise ValueError('Source gained directories during interrupted cleanup')
                elif hashes(current) != row['files']:
                    raise ValueError('Published source bytes differ from frozen receipt')
                row['source_snapshot'] = intent['source_snapshot'] if intent else current
                row['directories'] = intent['directories'] if intent else directory_tree(source)
                eligible.append(row)
            except (ValueError, OSError, KeyError, TypeError) as exc:
                retained.append(dict(item, reason=str(exc)))
        # One changed/missing sibling blocks this whole batch, while unrelated
        # unfinished batches do not prevent a fully completed batch from moving.
        result['already_archived'].extend(already_archived)
        if retained:
            result['retained'].extend(retained)
            result['retained'].extend({'batch_id': row['batch_id'], 'case_id': row['case_id'],
                                      'reason': 'Batch contains a retained sibling; source preserved'} for row in eligible)
        else:
            result['eligible'].extend(eligible)
    return result


class WindowsHandle:
    """Keep identity stable and deny writers/rename; delete this opened object only."""
    def __init__(self, path, *, delete=False, directory=False):
        if os.name != 'nt':
            raise ValueError('Protected archive handles require Windows; source retained')
        from ctypes import wintypes
        self.kernel = ctypes.WinDLL('kernel32', use_last_error=True)
        self.kernel.CreateFileW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD,
                                          ctypes.c_void_p, wintypes.DWORD, wintypes.DWORD,
                                          wintypes.HANDLE]
        self.kernel.CreateFileW.restype = wintypes.HANDLE
        self.kernel.CloseHandle.argtypes = [wintypes.HANDLE]
        self.kernel.SetFileInformationByHandle.argtypes = [wintypes.HANDLE, ctypes.c_int,
                                                          ctypes.c_void_p, wintypes.DWORD]
        self.kernel.ReadFile.argtypes = [wintypes.HANDLE, ctypes.c_void_p, wintypes.DWORD,
                                        ctypes.POINTER(wintypes.DWORD), ctypes.c_void_p]
        self.path = no_links(path)
        access = (0x1 if directory else 0x80000000) | (0x10000 if delete else 0)
        # Directory boundaries allow data operations but refuse rename/reparse swaps.
        sharing = 3 if directory else 1
        self.handle = self.kernel.CreateFileW(str(self.path), access, sharing, None, 3,
                                             0x02000000 | 0x00200000, None)
        if self.handle == ctypes.c_void_p(-1).value:
            raise OSError(ctypes.get_last_error(), 'Protected open failed; source retained', str(path))

    def close(self):
        if self.handle is not None:
            self.kernel.CloseHandle(self.handle)
            self.handle = None

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()

    def sha256(self):
        from ctypes import wintypes
        sha = hashlib.sha256()
        buffer = ctypes.create_string_buffer(1024 * 1024)
        count = wintypes.DWORD()
        while True:
            if not self.kernel.ReadFile(self.handle, buffer, len(buffer), ctypes.byref(count), None):
                raise OSError(ctypes.get_last_error(), 'Protected read failed')
            if not count.value:
                return sha.hexdigest()
            sha.update(buffer.raw[:count.value])

    def delete(self):
        disposition = ctypes.c_ubyte(1)
        if not self.kernel.SetFileInformationByHandle(self.handle, 4, ctypes.byref(disposition), 1):
            raise OSError(ctypes.get_last_error(), 'Protected delete failed; remaining source retained')


@contextmanager
def boundary_guard(*paths):
    """Pin existing ancestors throughout operations, including root reparse races."""
    with ExitStack() as stack:
        seen = set()
        for path in paths:
            for item in reversed((absolute(path), *absolute(path).parents)):
                if item in seen or not item.exists():
                    continue
                seen.add(item)
                if not item.is_dir():
                    raise ValueError('Boundary must be a directory')
                stack.enter_context(WindowsHandle(item, directory=True))
        yield


def durable_rename(source, destination):
    if os.name == 'nt':
        from ctypes import wintypes
        kernel = ctypes.WinDLL('kernel32', use_last_error=True)
        kernel.MoveFileExW.argtypes = [wintypes.LPCWSTR, wintypes.LPCWSTR, wintypes.DWORD]
        if not kernel.MoveFileExW(str(source), str(destination), 8):
            raise OSError(ctypes.get_last_error(), 'Non-overwriting atomic publication failed')
    else:
        raise ValueError('Archive apply requires Windows durable publication')


def copy_stage(source, stage, expected):
    stage.mkdir(parents=True, exist_ok=True)
    existing = snapshot(stage, allow_empty=True)
    if set(existing) - set(expected):
        raise ValueError('Unexpected files in owned staging directory; preserve for inspection')
    required = sum(v['size'] for k, v in expected.items()
                   if content(existing).get(k) != content(expected)[k])
    if shutil.disk_usage(stage).free < required + 1024 * 1024:
        raise ValueError('Destination free space insufficient; source retained')
    for rel, value in expected.items():
        target = inside(stage, rel, must_exist=False)
        if existing.get(rel) and content(existing)[rel] == content(expected)[rel]:
            continue
        origin = inside(source, rel)
        with WindowsHandle(origin) as held:
            if held.sha256() != value['sha256']:
                raise ValueError('Source changed before copy')
            target.parent.mkdir(parents=True, exist_ok=True)
            with origin.open('rb') as inp, target.open('wb') as out:
                shutil.copyfileobj(inp, out, 1024 * 1024)
                out.flush()
                os.fsync(out.fileno())
        if target.stat().st_size != value['size'] or digest(target) != value['sha256']:
            raise ValueError('Staging copy hash/size verification failed')
    if content(snapshot(stage)) != content(expected):
        raise ValueError('Staging inventory differs; source retained')


def cleanup_source(source, destination, expected, journal_path, journal):
    """No recursive remove: pin every exact file before any deletion begins."""
    with ExitStack() as stack:
        current = snapshot(source, allow_empty=journal.get('status') == 'source-cleanup-started')
        if any(expected.get(k) != v for k, v in current.items()):
            raise ValueError('Source identity/content changed; source retained')
        target_current = snapshot(destination)
        if content(target_current) != content(expected):
            raise ValueError('Published archive changed; source retained')
        if directory_tree(destination) != journal['directories']:
            raise ValueError('Published archive directory tree changed; source retained')
        current_directories = directory_tree(source)
        if set(current_directories) - set(journal['directories']):
            raise ValueError('Source gained directories; source retained')
        target_handles = []
        for rel in expected:
            target_handles.append((rel, stack.enter_context(WindowsHandle(inside(destination, rel)))))
        source_handles = []
        for rel in current:
            source_handles.append((rel, stack.enter_context(WindowsHandle(inside(source, rel), delete=True))))
        directories = [source]
        pending = [source]
        while pending:
            for child in pending.pop().iterdir():
                no_links(child)
                if child.is_dir():
                    directories.append(child)
                    pending.append(child)
        directory_handles = {d: stack.enter_context(WindowsHandle(d, delete=True, directory=True))
                             for d in sorted(directories, key=lambda p: len(p.parts))}
        pinned_inventory = snapshot(source, allow_empty=True, read_hash=False)
        before_inventory = {k: dict(v, sha256=None) for k, v in current.items()}
        if pinned_inventory != before_inventory:
            raise ValueError('Source boundary changed while acquiring handles')
        for rel, held in source_handles + target_handles:
            if held.sha256() != expected[rel]['sha256']:
                raise ValueError('Protected final content proof failed; source retained')
        journal['status'] = 'source-cleanup-started'
        write_json(journal_path, journal)
        for rel, held in source_handles:
            held.delete()
            held.close()
        for directory in sorted(directories, key=lambda p: len(p.parts), reverse=True):
            # Refuse new or revised material; never recursively clear it.
            if any(directory.iterdir()):
                raise ValueError('Source gained entries during cleanup; new material retained')
            directory_handles[directory].delete()
            directory_handles[directory].close()


def apply_one(row, source_root, destination_root, batch_root, state_root):
    source, destination = Path(row['source']), Path(row['destination'])
    journal_path = state_root / 'archives' / (row['archive_id'] + '.json')
    stage = destination_root / '.archive-staging' / row['archive_id']
    stage = no_links(stage)
    state_root.mkdir(parents=True, exist_ok=True)
    with boundary_guard(source_root, destination_root, batch_root, state_root, source.parent):
        if journal_path.exists():
            journal = read_json(journal_path)
            if any(journal.get(k) != row.get(k) for k in row if k != 'source_snapshot'):
                raise ValueError('Resume intent differs from current frozen product; preserve both')
        else:
            if destination.exists() or stage.exists():
                raise ValueError('Destination/staging conflict; no overwrite or adoption')
            journal = dict(row, status='copying', created_ns=time.time_ns())
            write_json(journal_path, journal)
        expected = journal['source_snapshot']
        if not destination.exists():
            if hashes(snapshot(source)) != row['files']:
                raise ValueError('Source changed before resumable copy')
            stage.mkdir(parents=True, exist_ok=True)
            if set(directory_tree(stage)) - set(journal['directories']):
                raise ValueError('Owned staging contains unexpected directories')
            for rel in journal['directories']:
                no_links(stage / rel).mkdir(parents=True, exist_ok=True)
            copy_stage(source, stage, expected)
            if directory_tree(stage) != journal['directories']:
                raise ValueError('Staging directory tree differs')
            if blockers(batch_root, row['batch_id'], row['case_id']):
                raise ValueError('Verified work/media became active; postpone publication')
            target = batch_root / row['batch_id']
            batch_readiness(source_root, destination_root, batch_root, target,
                            read_json(inside(target, 'manifest.json')))
            destination.parent.mkdir(parents=True, exist_ok=True)
            with boundary_guard(destination.parent, stage.parent):
                durable_rename(stage, destination)
        if content(snapshot(destination)) != content(expected):
            raise ValueError('Destination conflict or changed archive; source retained')
        if directory_tree(destination) != journal['directories']:
            raise ValueError('Destination directory tree differs; source retained')
        if journal.get('status') != 'source-cleanup-started':
            journal['status'] = 'published'
        write_json(journal_path, journal)
        with transaction(state_root):
            index_path = state_root / 'current-locations.json'
            index = read_json(index_path) if index_path.exists() else {}
            previous = index.get(str(source))
            locator = {key: journal[key] for key in ('archive_id', 'source', 'destination',
                       'source_root', 'destination_root', 'files', 'receipt_sha256', 'publication_sha256')}
            if previous and previous != locator:
                raise ValueError('Existing location points to a different version; preserve both')
            index[str(source)] = locator
            write_json(index_path, index)
        # Shared batch transaction excludes a new supported revision/record lease.
        with transaction(batch_root):
            target = batch_root / row['batch_id']
            manifest = read_json(inside(target, 'manifest.json'))
            batch_readiness(source_root, destination_root, batch_root, target, manifest)
            case = next(c for c in manifest['cases'] if c['case_id'] == row['case_id'])
            fresh = receipt_case(source_root, destination_root, target, manifest, case)
            if any(fresh[k] != row[k] for k in fresh):
                raise ValueError('Case/receipt changed before cleanup; source retained')
            if blockers(batch_root, row['batch_id'], row['case_id']):
                raise ValueError('Verified active task prevents source cleanup')
            if source.exists():
                cleanup_source(source, destination, expected, journal_path, journal)
        journal['status'] = 'archived'
        journal['completed_ns'] = time.time_ns()
        write_json(journal_path, journal)
        return journal


def apply(source_root, destination_root, batch_root, state_root):
    source_root, destination_root, batch_root, state_root = roots(
        source_root, destination_root, batch_root, state_root)
    report = plan(source_root, destination_root, batch_root, state_root)
    report['archived'] = []
    # Serial deterministic scripts only; no model dispatch or process termination.
    for row in report.pop('eligible'):
        try:
            state_root.mkdir(parents=True, exist_ok=True)
            with job_guard(state_root):
                report['archived'].append(apply_one(row, source_root, destination_root, batch_root, state_root))
        except (ValueError, OSError, KeyError, TypeError) as exc:
            report['retained'].append({'batch_id': row['batch_id'], 'case_id': row['case_id'],
                                       'reason': str(exc), 'source': row['source']})
    return report


@contextmanager
def job_guard(state_root):
    """Native exclusive lock releases on crash; persistent filename is not liveness."""
    if os.name != 'nt':
        raise ValueError('Archive apply requires Windows protected handles')
    from ctypes import wintypes
    kernel = ctypes.WinDLL('kernel32', use_last_error=True)
    kernel.CreateFileW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD,
                                  ctypes.c_void_p, wintypes.DWORD, wintypes.DWORD, wintypes.HANDLE]
    kernel.CreateFileW.restype = wintypes.HANDLE
    kernel.CloseHandle.argtypes = [wintypes.HANDLE]
    path = no_links(state_root / 'archive-job.lock')
    handle = kernel.CreateFileW(str(path), 0xC0000000, 0, None, 4, 0x00200000, None)
    if handle == ctypes.c_void_p(-1).value:
        raise OSError(ctypes.get_last_error(), 'Archive job busy; retry without deleting its lock')
    try:
        yield
    finally:
        kernel.CloseHandle(handle)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command', choices=['plan', 'apply'])
    for name in ('source-root', 'destination-root', 'batch-root', 'state-root'):
        parser.add_argument('--' + name, required=True)
    args = parser.parse_args(argv)
    try:
        result = globals()[args.command](args.source_root, args.destination_root,
                                         args.batch_root, args.state_root)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 2 if result['retained'] else 0
    except (ValueError, OSError, KeyError, TypeError) as exc:
        print(json.dumps({'error': str(exc), 'source_cleanup': 'not_started'}, ensure_ascii=False))
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
