"""Frozen delivery scope; never start/extract a package or attest runtime checks."""
MAIN_CODE_POLICY = 'main-code-v1'
DIRECTORY_POLICY = 'main-code-directory-v2'
from retained_source import POLICY as RETAINED_DIRECTORY_POLICY
from runtime_cache import POLICY as RUNTIME_CACHE_POLICY, enabled as retain_runtime_cache

def retain_all_source(run):
    return run.get('source_delivery_policy') in {RETAINED_DIRECTORY_POLICY, RUNTIME_CACHE_POLICY}
BUSINESS_CHECKS = ('algorithm', 'api', 'persistence', 'browser', 'build')


def main_code_only(run):
    if 'source_delivery_policy' not in run:
        return False
    if run['source_delivery_policy'] not in {MAIN_CODE_POLICY, DIRECTORY_POLICY, RETAINED_DIRECTORY_POLICY, RUNTIME_CACHE_POLICY}:
        raise ValueError('Unknown source delivery policy')
    return True


def directory_delivery(run):
    main_code_only(run)
    return run.get('source_delivery_policy') in {DIRECTORY_POLICY, RETAINED_DIRECTORY_POLICY, RUNTIME_CACHE_POLICY}


def source_members(path):
    """Hash real bytes. Directories never become synthetic publication files."""
    from common import no_links, file_map
    path = no_links(path)
    if path.is_dir():
        members = file_map(path)
        if not members or len({name.casefold() for name in members}) != len(members):
            raise ValueError('Nonempty, unambiguous source directory required')
        return members
    from contracts import zip_member_hashes
    return zip_member_hashes(path)


def tree_digest(members):
    """Versioned canonical relative-path/SHA256 map, NOT a ZIP byte hash."""
    import hashlib, json
    if not members:
        raise ValueError('Source directory has no files')
    payload = json.dumps(members, ensure_ascii=False, sort_keys=True, separators=(',', ':'))
    return hashlib.sha256(('source-tree-v1\n' + payload).encode('utf-8')).hexdigest()


def source_digest(path):
    from common import no_links, digest
    path = no_links(path)
    return tree_digest(source_members(path)) if path.is_dir() else digest(path)


def source_map_digest(run, output, files):
    from common import delivery_paths
    prefix = delivery_paths(run, output)['source_zip'].relative_to(output).as_posix()
    if directory_delivery(run):
        return tree_digest({k[len(prefix)+1:]: v for k, v in files.items() if k.startswith(prefix+'/')})
    return files.get(prefix)


def source_descriptor(run):
    return {'format': 'directory' if directory_delivery(run) else 'zip',
            'hash_kind': 'source-tree-v1' if directory_delivery(run) else 'file-sha256'}


def execution_kinds(run, package_revision=False):
    main = main_code_only(run)
    if package_revision:
        return () if main else ('package_startup',)
    return BUSINESS_CHECKS if main else BUSINESS_CHECKS + ('package_startup',)


def selected_files(spec, run, workspace=None):
    if retain_all_source(run):
        from retained_source import select
        return select(workspace, spec, keep_runtime=retain_runtime_cache(run))
    files = spec.get('files', [])
    if not main_code_only(run):
        return files
    if not isinstance(files, list) or not files or not all(isinstance(p, str) for p in files):
        raise ValueError('files must retain the complete implementation path list')
    selected = spec.get('delivery_files')
    if (not isinstance(selected, list) or not selected or
            not all(isinstance(p, str) and p in files for p in selected) or
            len({p.replace('\\', '/').casefold() for p in selected}) != len(selected)):
        raise ValueError('delivery_files must select distinct main source paths from the existing files manifest')
    # Preserve legal notices for code retained in the package. Keeping the
    # manifest's notices conservatively avoids silently dropping attribution.
    from pathlib import PurePosixPath
    result = list(selected)
    for rel in files:
        p = PurePosixPath(rel.replace('\\', '/'))
        if (p.name.upper().startswith(('LICENSE', 'NOTICE', 'COPYING')) or
                'licenses' in [s.casefold() for s in p.parts]) and rel not in result:
            result.append(rel)
    return result
