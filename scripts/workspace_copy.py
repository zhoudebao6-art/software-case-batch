"""Copy case content with normal destination inheritance; keep the old tree.

This does not grant permissions, reset ACLs, remove denies or change sandbox
settings. New filesystem objects inherit their destination directory normally.
"""
import json
import hashlib
import os
import shutil
import subprocess
import time
from collections import Counter
from pathlib import Path
from path_safety import has_path_link


def inaccessible_runtime_temps(path, flow, *, omitted_dirs=()):
    """Name unreadable disposable temp directories; refuse every other gap."""
    ignored = set()
    def onerror(exc):
        try:
            rel = Path(exc.filename).relative_to(path).as_posix()
        except (TypeError, ValueError):
            raise flow.Blocked(f'Workspace enumeration failed: {exc}') from exc
        parts = rel.split('/')
        if len(parts) != 3 or parts[:2] != ['.runtime', 'tmp'] or not parts[2].startswith(('pip-', 'tmp')):
            raise flow.Blocked(f'Unreadable non-temp workspace path: {rel}') from exc
        blocked_dir = path / rel
        if blocked_dir.is_symlink() or (hasattr(blocked_dir, 'is_junction') and blocked_dir.is_junction()):
            raise flow.Blocked(f'Unreadable runtime temp link refused: {rel}') from exc
        ignored.add(rel)
    for directory, dirs, _ in os.walk(path, followlinks=False, onerror=onerror):
        dirs[:] = [name for name in dirs if (Path(directory) / name).relative_to(path).as_posix()
                   not in omitted_dirs]
    return sorted(ignored)


def assert_normal_inheritance(path, flow, ignored_dirs=()):
    """Refuse to discard intentional protected/Deny ACLs during materialization."""
    if os.name != 'nt':
        return
    script = r'''$ErrorActionPreference='Stop'
$root=Get-Item -LiteralPath $env:CASEFLOW_COPY_ROOT -Force
$special=@()
function CheckAcl($item) {
  $rel=$item.FullName.Substring($root.FullName.Length).TrimStart('\').Replace('\','/')
  if($env:CASEFLOW_COPY_IGNORED.Contains('|' + $rel + '|')) { return }
  try {
    $acl=if($item.PSIsContainer) { [IO.Directory]::GetAccessControl($item.FullName) } else { [IO.File]::GetAccessControl($item.FullName) }
  } catch { throw "Workspace ACL unreadable: $($item.FullName): $($_.Exception.Message)" }
  if($acl.AreAccessRulesProtected -or @($acl.Access | Where-Object { $_.AccessControlType -eq 'Deny' }).Count) {
    $script:special+= [pscustomobject]@{Path=$item.FullName; Protected=$acl.AreAccessRulesProtected; HasDeny=@($acl.Access | Where-Object { $_.AccessControlType -eq 'Deny' }).Count -gt 0}
  }
  if($item.PSIsContainer) {
    foreach($child in @(Get-ChildItem -LiteralPath $item.FullName -Force -ErrorAction Stop)) { CheckAcl $child }
  }
}
CheckAcl $root
ConvertTo-Json -InputObject $special -Compress'''
    result = subprocess.run(['powershell.exe', '-NoProfile', '-NonInteractive', '-Command', script],
                            env=dict(os.environ, CASEFLOW_COPY_ROOT=str(path),
                                     CASEFLOW_COPY_IGNORED='|' + '|'.join(ignored_dirs) + '|'), capture_output=True,
                            encoding='utf-8', text=True, timeout=60)
    if result.returncode:
        raise flow.Blocked(f'Workspace ACL scan failed: {result.stderr.strip()[:600]}')
    special = json.loads(result.stdout or '[]')
    if special:
        groups = Counter('/'.join(Path(item['Path']).relative_to(path).parts[:3]) for item in special)
        raise flow.Blocked(f'Protected/Deny ACL needs separate diagnosis; fresh copy refused: '
                           f'count={len(special)} groups={dict(groups)} first={special[:3]}')


def tree_hashes(path, flow, *, ignored_dirs=()):
    if has_path_link(path):
        raise flow.Blocked('Workspace copy refuses linked root')
    result = {}
    def onerror(exc):
        raise flow.Blocked(f'Workspace enumeration failed: {exc}') from exc
    for directory, dirs, files in os.walk(path, followlinks=False, onerror=onerror):
        dirs[:] = [d for d in dirs if (Path(directory) / d).relative_to(path).as_posix() not in ignored_dirs]
        for name in dirs + files:
            child = Path(directory) / name
            if has_path_link(child):
                raise flow.Blocked(f'Workspace copy refuses linked path: {child}')
        for name in files:
            child = Path(directory) / name
            if os.name == 'nt' and len(str(child)) >= 240:
                digest = hashlib.sha256()
                with open('\\\\?\\' + str(child), 'rb') as stream:
                    for chunk in iter(lambda: stream.read(1024 * 1024), b''):
                        digest.update(chunk)
                result[child.relative_to(path).as_posix()] = digest.hexdigest()
            else:
                result[child.relative_to(path).as_posix()] = flow.sha256(child)
    return result


def materialize(flow, root, source, target, journal_path, *, process_guard,
                omit_runtime_scratch=False):
    """Resumable content copy and two renames. Source survives in backup."""
    def plain_child(path, root, flow):
        path = Path(path)
        if path.resolve() == root or has_path_link(path) or not path.resolve().is_relative_to(root):
            raise flow.Blocked(f'Workspace copy path outside root or linked: {path}')
        return path
    root = root.resolve(strict=True)
    source = plain_child(source, root, flow)
    target = plain_child(target, root, flow)
    scratch_dirs = ['.runtime/browser', '.runtime/browser-recovery', '.runtime/tmp'] if omit_runtime_scratch else []
    if journal_path.exists():
        journal = flow.read_json(journal_path)
        if (journal['source'], journal['target']) != (str(source), str(target)):
            raise flow.Blocked('Workspace copy journal path identity mismatch')
        if journal['status'] == 'complete':
            return journal
        scan_root = Path(journal['backup']) if Path(journal['backup']).exists() else source
        ignored_dirs = inaccessible_runtime_temps(scan_root, flow, omitted_dirs=scratch_dirs)
        if 'omitted_unreadable_runtime_dirs' in journal and journal['omitted_unreadable_runtime_dirs'] != ignored_dirs:
            raise flow.Blocked('Unreadable runtime temp set changed during workspace copy')
        if 'omitted_runtime_scratch_dirs' in journal and journal['omitted_runtime_scratch_dirs'] != scratch_dirs:
            raise flow.Blocked('Runtime scratch omission changed during workspace copy')
        journal['omitted_unreadable_runtime_dirs'] = ignored_dirs
        journal['omitted_runtime_scratch_dirs'] = scratch_dirs
        flow.atomic_json(journal_path, journal)
    else:
        if source != target and target.exists():
            raise flow.Blocked('Workspace copy target exists')
        token = str(time.time_ns())
        stage = target.parent / ('.case-copy-' + token)
        backup = root / '.runtime' / 'workspace-backups' / token / source.name
        ignored_dirs = inaccessible_runtime_temps(source, flow, omitted_dirs=scratch_dirs)
        journal = {'status': 'planned', 'source': str(source), 'target': str(target),
                   'stage': str(stage), 'backup': str(backup),
                   'files': tree_hashes(source, flow, ignored_dirs=ignored_dirs + scratch_dirs)}
        journal['omitted_unreadable_runtime_dirs'] = ignored_dirs
        journal['omitted_runtime_scratch_dirs'] = scratch_dirs
        flow.atomic_json(journal_path, journal)
    stage = plain_child(journal['stage'], root, flow)
    backup = plain_child(journal['backup'], root, flow)
    hits = process_guard([source, target])
    if hits:
        raise flow.Blocked(f'Workspace copy requires stopped case processes: {hits}')
    expected = journal['files']
    ignored_dirs = journal['omitted_unreadable_runtime_dirs']
    scratch_dirs = journal['omitted_runtime_scratch_dirs']
    copy_expected = {rel: digest for rel, digest in expected.items()
                     if not any(rel.startswith(prefix + '/') for prefix in scratch_dirs)}
    if not backup.exists():
        if tree_hashes(source, flow, ignored_dirs=ignored_dirs + scratch_dirs) != expected:
            raise flow.Blocked('Workspace changed while preparing a fresh copy')
        assert_normal_inheritance(source, flow, ignored_dirs + scratch_dirs)
        stage.mkdir(parents=True, exist_ok=True)
        # Re-copy only incomplete files when resuming; never carry source ACLs.
        def onerror(exc):
            raise flow.Blocked(f'Workspace copy enumeration failed: {exc}') from exc
        for directory, dirs, files in os.walk(source, onerror=onerror):
            dirs[:] = [d for d in dirs if (Path(directory) / d).relative_to(source).as_posix()
                       not in ignored_dirs + scratch_dirs]
            rel = Path(directory).relative_to(source)
            (stage / rel).mkdir(parents=True, exist_ok=True)
            for name in files:
                original, copied = Path(directory) / name, stage / rel / name
                if not copied.exists() or flow.sha256(copied) != expected[(rel / name).as_posix()]:
                    shutil.copy2(original, copied)
        if tree_hashes(stage, flow) != copy_expected or tree_hashes(source, flow, ignored_dirs=ignored_dirs + scratch_dirs) != expected:
            raise flow.Blocked('Fresh workspace copy hash mismatch')
        if process_guard([source, target]):
            raise flow.Blocked('Case process appeared during workspace copy')
        backup.parent.mkdir(parents=True, exist_ok=True)
        plain_child(source, root, flow); plain_child(backup, root, flow)
        source.rename(backup)
    if tree_hashes(backup, flow, ignored_dirs=ignored_dirs + scratch_dirs) != expected:
        raise flow.Blocked('Old workspace backup hash mismatch')
    if stage.exists():
        if target.exists():
            raise flow.Blocked('Workspace copy target appeared; refusing overwrite')
        if tree_hashes(stage, flow) != copy_expected:
            raise flow.Blocked('Fresh staged workspace changed')
        plain_child(stage, root, flow); plain_child(target, root, flow)
        stage.rename(target)
    if tree_hashes(target, flow) != copy_expected:
        raise flow.Blocked('Fresh workspace final hash mismatch')
    journal.update(status='complete', completed_at=time.time(), file_count=len(copy_expected),
                   archived_runtime_file_count=None if scratch_dirs else len(expected) - len(copy_expected))
    flow.atomic_json(journal_path, journal)
    return journal


def refresh(cfg, ref, cid, flow, *, process_guard, omit_runtime_scratch=False):
    m, folder = flow.load_batch(cfg, ref)
    entries = [e for e in m['cases'] if e['case_id'] == cid]
    if len(entries) != 1:
        raise flow.Blocked('Unknown maintenance case')
    entry = entries[0]
    case = flow.case_workspace(folder, entry)
    control = folder / 'maintenance' / cid
    control.mkdir(parents=True, exist_ok=True)
    with flow.BatchLock(control):
        state_path = flow.state_at(folder, cid)
        state = flow.read_json(state_path)
        if state.get('stage') != 'blocked' or state.get('active_stage') or state.get('waiting_stage'):
            raise flow.Blocked('Only a stopped blocked case can be refreshed while other cases run')
        journal = materialize(flow, cfg['_root'], case, case, control / 'workspace-copy.json',
                              process_guard=process_guard, omit_runtime_scratch=omit_runtime_scratch)
        state['needs_workspace_repair'] = True
        state['workspace_migration'] = state.get('workspace_migration') or {'from': str(case), 'to': str(case)}
        state['workspace_copy'] = {'backup': journal['backup'], 'file_count': journal['file_count'],
                                   'omitted_unreadable_runtime_dirs': journal['omitted_unreadable_runtime_dirs'],
                                   'omitted_runtime_scratch_dirs': journal['omitted_runtime_scratch_dirs'],
                                   'archived_runtime_file_count': journal['archived_runtime_file_count'],
                                   'completed_at': journal['completed_at']}
        flow.atomic_json(state_path, state)
        return {'status': 'refreshed', 'workspace': str(case), **state['workspace_copy']}


if __name__ == '__main__':
    import argparse
    import caseflow as flow
    from migrate_batch import owned_processes
    parser = argparse.ArgumentParser()
    parser.add_argument('--config', type=Path, required=True)
    parser.add_argument('--batch', required=True)
    parser.add_argument('--case', required=True)
    parser.add_argument('--omit-runtime-scratch', action='store_true')
    args = parser.parse_args()
    print(json.dumps(refresh(flow.config_at(args.config), args.batch, args.case, flow,
                             process_guard=owned_processes,
                             omit_runtime_scratch=args.omit_runtime_scratch), ensure_ascii=False, indent=2))
