"""Optional read-only reviewer preparation; never runs tests, views evidence or signs pass.

check prints structured errors without writing. draft writes only a new explicit
private directory. Existing evidence indexes retain their IDs; automatic discovery
is limited to current receipts and declared dependencies, never a workspace scan.
"""
import argparse
import hashlib
import json
from pathlib import Path

from common import digest, inside, no_links, product_location, read_json
from evidence_index import check, review_input

EXECUTION_KINDS = ('algorithm', 'api', 'persistence', 'browser', 'build', 'package_startup')


def execution_checks(value, kinds=EXECUTION_KINDS):
    """Keep the final-proof list contract; construction-check objects differ."""
    if (not isinstance(value, list) or len(value) != len(kinds)
            or not all(isinstance(item, dict) for item in value)
            or not all(isinstance(item.get('kind'), str) for item in value)
            or {item['kind'] for item in value} != set(kinds)):
        raise ValueError('Six distinct execution checks required: checks must be a list of '
                         'objects with exact kinds ' + ', '.join(kinds))
    return value


def inspect(workspace, execution, index=None, manifest=None):
    workspace = no_links(workspace)
    errors, paths = [], set()

    def issue(code, location, message):
        errors.append({'code': code, 'location': str(location), 'message': str(message)[:1000]})

    if index and manifest:
        issue('schema', 'scope', 'Choose an existing complete index OR a supplementary manifest; do not silently omit manifest files')

    def actual(value, expected=None):
        try:
            if not isinstance(value, (str, Path)) or not str(value):
                raise ValueError('Expected an actual file path')
            path = no_links(value) if Path(value).is_absolute() else inside(workspace, value, must_exist=False)
            if workspace not in path.parents:
                raise ValueError('Evidence must be inside the current workspace')
            if not path.is_file():
                issue('missing', value, 'Missing regular evidence file'); return None
            paths.add(path.relative_to(workspace).as_posix())
            if expected is not None and digest(path) != expected:
                issue('stale', value, 'Declared SHA256 differs from current evidence')
            return path
        except (ValueError, OSError, TypeError) as exc:
            issue('schema', value, exc); return None

    def document(value, required=True, expected=None):
        if not required and not (workspace / value).exists():
            return {}
        path = actual(value, expected)
        if path is None:
            return {}
        try:
            result = read_json(path)
            if not isinstance(result, dict):
                raise ValueError('Expected a JSON object')
            return result
        except (ValueError, OSError) as exc:
            issue('schema', value, exc); return {}

    run = document('.product-v2/run.json')
    if run.get('workspace') != str(workspace) or not run.get('run_id'):
        issue('schema', '.product-v2/run.json', 'Current workspace and run_id required')
    proof = document(execution)
    checks = []
    try:
        checks = execution_checks(proof.get('checks'))
    except ValueError as exc:
        issue('schema', 'checks', exc)
    for item in checks:
        kind = item['kind']
        if type(item.get('exit_code')) is not int or item['exit_code'] != 0:
            issue('failed', 'checks.' + kind, 'Actual successful integer exit_code required')
        if not isinstance(item.get('command'), str) or not item['command'].strip():
            issue('schema', 'checks.' + kind + '.command', 'Nonempty actual command required')
        if not isinstance(item.get('sha256'), str) or len(item['sha256']) != 64:
            issue('schema', 'checks.' + kind + '.sha256', 'Actual log SHA256 required')
        log = actual(item.get('log'), item.get('sha256', ''))
        if log and log.stat().st_size == 0:
            issue('missing', item['log'], 'Execution log is empty')

    charts = document('.product-v2/chart-manifest.json')
    try:
        from contracts import chart_policy, chart_records
        if chart_policy(run) is not None:
            chart_records(charts, run)
    except (ValueError, KeyError, TypeError, AttributeError) as exc:
        issue('schema', 'chart-manifest', exc)
    figures = charts.get('figures', [])
    if not isinstance(figures, list) or not figures:
        issue('schema', 'chart-manifest.figures', 'Current nonempty chart records required')
    else:
        for item in figures:
            if not isinstance(item, dict):
                issue('schema', 'chart-manifest.figures', 'Chart must be an object'); continue
            actual(item.get('png'), item.get('sha256', ''))
    package = document('.product-v2/source-package.json')
    members = package.get('files', {})
    if not isinstance(members, dict) or not members:
        issue('schema', 'source-package.files', 'Explicit current source hash map required')
    else:
        for rel, sha in members.items():
            actual(rel, sha)
    controlled = document('.product-v2/controlled-video.json')
    if controlled:
        timeline = document(controlled.get('timeline'), expected=controlled.get('sha256', ''))
        for group in ('frames', 'contact_sheets', 'interaction_frames'):
            items = timeline.get(group, [])
            if not isinstance(items, list) or not items:
                issue('schema', 'timeline.' + group, 'Actual declared timeline items required'); continue
            for item in items:
                if not isinstance(item, dict):
                    issue('schema', 'timeline.' + group, 'Timeline item must be an object'); continue
                actual(item.get('file'), item.get('sha256', ''))
    for name in ('recording.json', 'data-cleaning.json', 'data-quality.json',
                 'data-provenance.json', 'cleanup.json', 'model-dispatch.json', 'build-checks.json'):
        doc = document('.product-v2/' + name, required=False)
        if name == 'build-checks.json' and isinstance(doc.get('checks'), dict):
            for item in doc['checks'].values():
                if not isinstance(item, dict):
                    issue('schema', 'build-checks.checks', 'Construction check must be an object'); continue
                actual(item.get('log'), item.get('sha256', ''))
                inputs = item.get('input_files', {})
                if isinstance(inputs, dict):
                    for rel, sha in inputs.items():
                        actual(rel, sha)

    if manifest:
        extra = document(manifest).get('files')
        if not isinstance(extra, list) or not all(isinstance(rel, str) for rel in extra):
            issue('schema', 'manifest.files', 'Explicit evidence file list required')
        else:
            for rel in extra:
                actual(rel)
    output = None
    try:
        output = product_location(workspace, run)
        if output == workspace or workspace in output.parents or output in workspace.parents:
            raise ValueError('Product and workspace must be disjoint')
        if not output.is_dir() or not any(p.is_file() for p in output.rglob('*')):
            issue('missing', output, 'Current product output is missing or empty')
        archive = output / '模拟系统/项目源码.zip'
        if not archive.is_file():
            issue('missing', archive, 'Current final source ZIP required')
        elif digest(archive) != proof.get('source_zip_sha256') or digest(archive) != package.get('sha256'):
            issue('stale', 'source_zip_sha256', 'Execution and package receipt must bind the final ZIP')
        if proof.get('video_timeline_sha256') != controlled.get('sha256'):
            issue('stale', 'video_timeline_sha256', 'Execution facts must bind the current controlled timeline')
    except (ValueError, OSError, KeyError, TypeError) as exc:
        issue('schema', 'run.output', exc)

    records = []
    if index:
        try:
            check(index, [], workspace)
            records = read_json(index)['evidence']
        except (ValueError, OSError, KeyError, TypeError, AttributeError) as exc:
            issue('stale', 'index', exc)
    elif not errors:
        records = [{'id': 'E' + str(i + 1).zfill(3), 'path': rel, 'sha256': digest(inside(workspace, rel))}
                   for i, rel in enumerate(sorted(paths))]
    return {'schema_version': 1, 'kind': 'review-input-preflight',
            'status': 'blocked' if errors else 'inputs_ready', 'errors': errors,
            'workspace': str(workspace), 'run_id': run.get('run_id'), 'evidence': records,
            'execution_checks': checks, 'source_zip_sha256': proof.get('source_zip_sha256'),
            'video_timeline_sha256': controlled.get('sha256'),
            'scope': 'Declared current evidence only; discovery is not proof of complete review scope. '
                     'Supply an existing complete index or explicit manifest for rendered Word pages and source mappings. '
                     'No commands executed, visuals viewed, review approved or receipt modified.'}


def draft(workspace, execution, destination, index=None, manifest=None):
    workspace = no_links(workspace); destination = no_links(destination)
    private = workspace / '.product-v2/review-inputs'
    if private not in destination.parents or destination.exists():
        raise ValueError('Use an explicit wholly new private .product-v2/review-inputs/<name> directory; never overwrite evidence or a review')
    report = inspect(workspace, execution, index, manifest)
    if report['errors']:
        return report  # No partial artifacts on failed preflight.
    destination.mkdir(parents=True, exist_ok=False)
    records = report['evidence']
    snapshot = {'schema_version': 1, 'workspace': str(workspace), 'evidence': records,
                'review_id': hashlib.sha256(json.dumps(records, sort_keys=True).encode()).hexdigest()[:12]}

    def save(name, value):
        # Exclusive creation: earlier reviews and index files are never replaced.
        with (destination / name).open('x', encoding='utf-8', newline='\n') as stream:
            json.dump(value, stream, ensure_ascii=False, indent=2); stream.write('\n')
    save('index.json', snapshot)
    facts_path = destination / 'facts.json'
    review_input(workspace, destination / 'index.json', facts_path)
    save('preflight.json', report)
    save('review-draft.json', {'kind': 'non-authoritative-review-draft', 'run_id': report['run_id'],
         'checks': report['execution_checks'], 'source_zip_sha256': report['source_zip_sha256'],
         'video_timeline_sha256': report['video_timeline_sha256'],
         'reviewed_files': read_json(facts_path)['current_artifacts'],
         'reviewed_evidence': [], 'chart_reviews': [], 'visual_notes': [], 'limitations': [],
         'instruction': 'Copied execution facts are unreviewed. Reviewer must actually inspect evidence, '
                        'write independent findings, actual coverage and identity, then attest the final proof hash. '
                        'This draft has no decision or signature and cannot finalize.'})
    return {'status': 'draft_created', 'directory': str(destination), 'evidence_items': len(records),
            'scope': report['scope']}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=['check', 'draft'])
    parser.add_argument('--workspace', required=True); parser.add_argument('--execution', required=True)
    scope = parser.add_mutually_exclusive_group()
    scope.add_argument('--index'); scope.add_argument('--manifest'); parser.add_argument('--output')
    args = parser.parse_args(argv)
    try:
        if args.action == 'draft':
            if not args.output:
                raise ValueError('draft requires an explicit private --output directory')
            result = draft(args.workspace, args.execution, args.output, args.index, args.manifest)
        else:
            result = inspect(args.workspace, args.execution, args.index, args.manifest)
    except (ValueError, OSError, KeyError, TypeError) as exc:
        result = {'status': 'blocked', 'errors': [{'code': 'schema', 'location': args.action, 'message': str(exc)}]}
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 2 if result['status'] == 'blocked' else 0


if __name__ == '__main__':
    raise SystemExit(main())
