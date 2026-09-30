"""Offline, journaled workspace migration. Never stops a process itself."""
import json
import importlib.util
import os
import subprocess
import time
from pathlib import Path
from path_safety import has_path_link


def owned_processes(paths):
    """Conservative command-line ownership guard, plus cwd on Linux test hosts."""
    needles = [str(p).replace('/', '\\').casefold() for p in paths]
    if os.name == 'nt':
        records = []
        for path in paths:
            record = path / 'evidence' / 'process.json'
            if record.is_file():
                data = json.loads(record.read_text(encoding='utf-8'))
                if isinstance(data.get('pid'), int) and isinstance(data.get('command_line'), str):
                    records.append({'pid': data['pid'], 'command_line': data['command_line']})
        env = dict(os.environ, CASEFLOW_MIGRATION_PATHS=json.dumps(needles, ensure_ascii=True),
                   CASEFLOW_MIGRATION_RECORDS=json.dumps(records, ensure_ascii=True))
        script = r'''$ErrorActionPreference='Stop'
$targets = $env:CASEFLOW_MIGRATION_PATHS | ConvertFrom-Json
$records = $env:CASEFLOW_MIGRATION_RECORDS | ConvertFrom-Json
$hits = @(Get-CimInstance Win32_Process | Where-Object {
    $line = ([string]$_.CommandLine).Replace('/', '\').ToLowerInvariant()
    $matched = $false
    foreach ($target in $targets) { if ($line.Contains($target)) { $matched = $true; break } }
    foreach ($record in $records) {
        if ($_.ProcessId -eq $record.pid -and $_.CommandLine -eq $record.command_line) { $matched = $true; break }
    }
    $matched
} | Select-Object ProcessId, Name)
ConvertTo-Json -InputObject $hits -Compress'''
        result = subprocess.run(['powershell.exe', '-NoProfile', '-NonInteractive', '-Command', script],
                                env=env, capture_output=True, text=True, encoding='utf-8', timeout=30, check=True)
        return json.loads(result.stdout or '[]')
    hits = []
    for p in Path('/proc').glob('[0-9]*'):
        if int(p.name) == os.getpid():
            continue
        try:
            line = (p / 'cmdline').read_bytes().decode(errors='replace').replace('/', '\\').casefold()
            cwd = str((p / 'cwd').resolve()).replace('/', '\\').casefold()
            if any(n in line or cwd == n or cwd.startswith(n + '\\') for n in needles):
                hits.append({'ProcessId': int(p.name), 'Name': (p / 'comm').read_text().strip()})
        except (OSError, ValueError):
            pass
    return hits


def plain_child(path, root, flow):
    path = Path(path)
    root = root.resolve(strict=True)
    if has_path_link(path) or path.resolve() == root or not path.resolve().is_relative_to(root):
        raise flow.Blocked(f'Migration path leaves workspace or traverses a link: {path}')
    return path


def migrate(cfg, ref, flow):
    m, folder = flow.load_batch(cfg, ref)
    root = cfg['_root']
    flow.prepare_control_directories(root)
    control = root / '.runtime' / 'planning'
    control.mkdir(parents=True, exist_ok=True)
    journal_path = folder / 'workspace-migration.json'
    with flow.BatchLock(folder), flow.BatchLock(control):
        if journal_path.exists():
            journal = flow.read_json(journal_path)
            if journal.get('batch_id') != m['batch_id']:
                raise flow.Blocked('Migration journal identity mismatch')
            if journal.get('status') == 'complete':
                return journal['result']
            if flow.batch_identity(journal['manifest']) != flow.batch_identity(m):
                raise flow.Blocked('Migration source identity changed')
        else:
            updated = json.loads(json.dumps(m))
            # Published cases remain frozen; explicit redelivery is separate work.
            for e in updated['cases']:
                state_path = flow.state_at(folder, e['case_id'])
                if state_path.exists() and flow.read_json(state_path).get('stage') == 'delivered':
                    if not e.get('workspace_relative'):
                        raise flow.Blocked('Delivered legacy case needs a separate archival plan')
            flow.assign_workspaces(updated, folder, root, include_started=True)
            updated['schema_version'] = 2
            rows = []
            for old, new in zip(m['cases'], updated['cases']):
                src, dst = flow.case_workspace(folder, old), flow.case_workspace(folder, new)
                if src == dst:
                    continue
                plain_child(src, root, flow); plain_child(dst, root, flow)
                if dst.exists():
                    raise flow.Blocked(f'Migration destination already exists: {dst}')
                state_path = flow.state_at(folder, old['case_id'])
                state = flow.read_json(state_path) if state_path.exists() else None
                rows.append({'case_id': old['case_id'], 'from': str(src), 'to': str(dst),
                             'existed': src.exists(), 'state_before': state})
            journal = {'batch_id': m['batch_id'], 'status': 'pending', 'created_at': time.time(),
                       'manifest_before': m, 'manifest': updated, 'moves': rows}
            # Do not even create a journal while a proven owner still runs.
            hits = owned_processes([Path(r['from']) for r in rows if r['existed']]) if rows else []
            if hits:
                raise flow.Blocked(f'Stop verified case processes before migration: {hits}')
            flow.atomic_json(journal_path, journal)
        paths = [Path(r[k]) for r in journal['moves'] if r['existed'] for k in ('from', 'to')]
        hits = owned_processes(paths) if paths else []
        if hits:
            raise flow.Blocked(f'Stop verified case processes before migration: {hits}')
        entries = {e['case_id']: e for e in journal['manifest']['cases']}
        for row in journal['moves']:
            src = plain_child(row['from'], root, flow)
            dst = plain_child(row['to'], root, flow)
            entry = entries[row['case_id']]
            if dst != flow.case_workspace(folder, entry):
                raise flow.Blocked('Migration destination differs from manifest')
            marker = {'batch_id': m['batch_id'], 'case_id': row['case_id'], 'from': str(src), 'to': str(dst)}
            marker_name = '.workspace-migration.json'
            if row['existed']:
                copy_journal = folder / 'migration-copies' / (entry['case_id'] + '.json')
                if src.exists() or copy_journal.exists():
                    if dst.exists() and not copy_journal.exists():
                        raise flow.Blocked('Both old and new workspaces exist; refusing overwrite')
                    if src.exists() and not copy_journal.exists():
                        flow.atomic_json(src / marker_name, marker)
                    dst.parent.mkdir(parents=True, exist_ok=True)
                    spec = importlib.util.spec_from_file_location('caseflow_workspace_copy', Path(__file__).with_name('workspace_copy.py'))
                    module = importlib.util.module_from_spec(spec)
                    spec.loader.exec_module(module)
                    # Fresh objects inherit destination permissions; old ACLs are not copied.
                    module.materialize(flow, root, src, dst, copy_journal, process_guard=owned_processes)
                elif not (dst / marker_name).is_file() or flow.read_json(dst / marker_name) != marker:
                    raise flow.Blocked('Moved workspace ownership cannot be verified')
                copied_source = dst / 'source' / Path(entry['source_path']).name
                if copied_source.exists() and flow.sha256(copied_source) != entry['source_sha256']:
                    raise flow.Blocked('Migrated source copy hash mismatch')
            elif src.exists() or dst.exists():
                raise flow.Blocked('Unstarted migration path changed unexpectedly')
            before = row['state_before']
            if before is not None:
                state = json.loads(json.dumps(before))
                checkpoint = state.get('previous_stage', 'new') if state.get('stage') == 'blocked' else state.get('stage', 'new')
                state.update(stage='new' if checkpoint == 'new' else 'built',
                             workspace=str(dst), case_name=entry['case_name'], reason=None)
                for key in ('active_stage', 'active_started_at', 'waiting_stage', 'waiting_started_at',
                            'previous_stage', 'final_review', 'visual_review', 'video_review', 'controlled_word', 'controlled_video'):
                    state.pop(key, None)
                state['workspace_migration'] = marker
                if checkpoint != 'new':
                    state['needs_workspace_repair'] = True
                flow.atomic_json(flow.state_at(folder, entry['case_id']), state)
            manifest_path = dst / 'evidence' / 'artifact-manifest.json'
            if row['existed'] and manifest_path.exists():
                artifacts = flow.read_json(manifest_path)
                backup = folder / 'migration-backups' / entry['case_id'] / 'artifact-manifest.json'
                if not backup.exists():
                    flow.atomic_json(backup, artifacts)
                for key in ('video', 'video_timeline', 'video_contact_sheets', 'ui_text_audit'):
                    artifacts.pop(key, None)
                flow.atomic_json(manifest_path, artifacts)
        flow.atomic_json(folder / 'manifest.json', journal['manifest'])
        result = {'batch_id': m['batch_id'], 'status': 'migrated', 'batch_workspace': str(folder),
                  'workspaces': [{'case_id': e['case_id'], 'workspace': str(flow.case_workspace(folder, e))}
                                 for e in journal['manifest']['cases']], 'execution': cfg.get('execution', {})}
        journal.update(status='complete', completed_at=time.time(), result=result)
        flow.atomic_json(journal_path, journal)
        flow.atomic_json(folder / 'status.json', {'batch_id': m['batch_id'], 'status': 'ready_to_resume',
                         'case_concurrency': cfg.get('execution', {}).get('case_concurrency', 1)})
        if os.name == 'nt' and folder.parent == root:
            import ctypes
            target = ctypes.c_wchar_p(str(folder))
            attrs = ctypes.windll.kernel32.GetFileAttributesW(target)
            if attrs != -1:
                ctypes.windll.kernel32.SetFileAttributesW(target, attrs | 2)
        return result
