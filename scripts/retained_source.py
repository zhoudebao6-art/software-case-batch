"""Full project-tree selection for new runs; never edit implementation files."""
from pathlib import Path, PurePosixPath
import os
import re

POLICY = 'clean-source-directory-v3'
INTERNAL_DIRS = {'.git', '.product-v2', '.codex', '.agents', '.claude',
    'node_modules', '.venv', 'venv', '__pycache__', '.pytest_cache', '.cache',
    'source-analysis', 'source_analysis', 'docx-extract', 'docx_extract',
    'document-analysis', 'document_analysis', '原文解析', '文档解析', '原件备份'}
INTERNAL_NAMES = {'agents.md', 'claude.md', 'skill.md', 'build_selfcheck.json',
    'key_facts.json', 'source_trace.json', 'source-trace.json', 'formula_registry.json',
    'source_text.txt', 'source-text.txt', 'material-research.json', 'artifact-manifest.json'}


def exclusion(relative, data=None, extra=(), keep_runtime=False):
    """Exclude identified production/private artifacts, not business categories."""
    p = PurePosixPath(relative.replace('\\', '/'))
    parts = [v.casefold() for v in p.parts]
    name = parts[-1] if parts else ''
    internal = INTERNAL_DIRS - {'.cache'} if keep_runtime else INTERNAL_DIRS
    if any(v in internal for v in parts):
        return 'internal-production-or-dependency-directory'
    if keep_runtime:
        from runtime_cache import exclusion as runtime_exclusion
        why = runtime_exclusion(relative, data)
        if why:
            return why
    if (name in {'.env', 'credentials.json', 'token.json', 'tokens.json', 'id_rsa', 'id_ed25519'}
            or (name.startswith('.env.') and not re.fullmatch(r'\.env(?:\.[a-z0-9_-]+)*\.(?:example|sample|template)', name))
            or p.suffix.casefold() in {'.pfx', '.p12'}):
        return 'credential-file'
    if data is not None and credential_content(relative, data):
        return 'credential-content'
    if p.suffix.casefold() in {'.log', '.pyc', '.pyo'}:
        return 'runtime-file'
    # Attribution must survive README-like parent names and broad cleanup terms.
    if name.upper().startswith(('LICENSE', 'NOTICE', 'COPYING')) or 'licenses' in parts:
        return None
    for item in extra:
        if isinstance(item, dict) and p.as_posix().casefold() == PurePosixPath(item['path'].replace('\\', '/')).as_posix().casefold():
            if keep_runtime and item['reason'] == 'runtime-state':
                continue
            return 'declared-' + item['reason']
    if (name in INTERNAL_NAMES or re.match(
            r'^(?:source[-_]analysis|docx[-_](?:extract|analysis)|analyze_source|extract_docx|render_docx|build_word|make_word|generate_word)(?:\.|$)', name)):
        return 'production-tool-or-record'
    # A business module named analysis/parser/model, its JSON configuration,
    # tests, assets, launch/build scripts and lockfiles are not production debris.
    if re.match(r'^read[\s._-]*me(?:$|[\s._-])', name):
        return 'delivery-readme'
    if 'prompts' in parts[:-1] and name in {'build.txt', 'review.txt', 'repair.txt', '制作提示词.txt'}:
        return 'production-prompt'
    if p.suffix.casefold() in {'.md', '.rst', '.txt', '.doc', '.docx', '.pdf'}:
        from package_policy import excluded_delivery_document
        return excluded_delivery_document(p.name)
    return None


def credential_content(relative, data):
    """Recognize private material without printing values or deleting originals."""
    p=PurePosixPath(relative)
    if p.suffix.casefold() not in {'.json','.yaml','.yml','.toml','.ini','.cfg','.conf','.pem','.key'} and p.name.casefold() not in {'.npmrc','.pypirc'} and not p.name.startswith('.env'):
        return False
    try:
        text=data.decode('utf-16' if data.startswith((b'\xff\xfe',b'\xfe\xff')) else 'utf-8-sig')
    except UnicodeError:
        return p.suffix.casefold() in {'.pem','.key'}
    if re.search(r'-----BEGIN (?:[A-Z0-9 ]* )?PRIVATE KEY-----',text):return True
    # Include npm's //registry/:_authToken and cloud service-account JSON.
    pattern=r'''(?im)["']?(?:_authToken|_auth|private_key|client_secret|api[_-]?key|access[_-]?token|refresh[_-]?token|password|passwd|aws_secret_access_key|azure_storage_key)["']?\s*[:=]\s*(?:"([^"\r\n]*)"|'([^'\r\n]*)'|([^\r\n,]+))'''
    for match in re.finditer(pattern,text):
        value=next(v for v in match.groups() if v is not None).strip()
        if not value or value.startswith(('{','[')) or value.casefold() in {'null','none','true','false','changeme','change_me','your_api_key','your_token','your_password','example','placeholder'}:
            continue
        if re.fullmatch(r'\$\{[^}]+\}|\$[A-Za-z_][A-Za-z0-9_]*|%[^%]+%|<[^>]+>',value):continue
        return True
    return False


def select(workspace, spec, keep_runtime=False):
    """Enumerate complete declared project roots, union loose project files.

    Roots are declared in the existing source manifest, not a new workflow gate.
    delivery_files cannot narrow this inventory. No links or outside paths.
    """
    from common import no_links, inside
    workspace = no_links(workspace)
    roots = spec.get('source_roots')
    if not isinstance(roots, list) or not roots or not all(isinstance(r, str) and r for r in roots):
        raise ValueError('source_roots must name complete application directories in the existing manifest')
    internal = INTERNAL_DIRS - {'.cache'} if keep_runtime else INTERNAL_DIRS
    if keep_runtime:
        from runtime_cache import roots as cache_roots
        cache_roots(spec)
        roots = roots + spec.get('runtime_cache_roots', [])
    files = spec.get('files', [])
    if not isinstance(files, list) or not all(isinstance(p, str) for p in files):
        raise ValueError('files must list project files outside or inside source_roots')
    result = set()
    for name in files:
        inside(workspace, name)
        result.add(PurePosixPath(name.replace('\\', '/')).as_posix())
    for name in roots:
        rel = Path(name)
        if rel.is_absolute() or '..' in rel.parts or ':' in name:
            raise ValueError('Unsafe source root: ' + name)
        root = no_links(workspace / rel)
        if root != workspace and workspace not in root.parents:
            raise ValueError('Source root escapes workspace')
        if not root.is_dir():
            raise ValueError('Missing source root: ' + name)
        for current, directories, names in os.walk(root, followlinks=False):
            no_links(current)
            kept = []
            for d in directories:
                path = Path(current) / d
                relative = path.relative_to(workspace).as_posix()
                if any(v.casefold() in internal for v in path.relative_to(workspace).parts):
                    continue
                no_links(path)
                kept.append(d)
            directories[:] = kept
            for n in names:
                path = Path(current) / n
                no_links(path)
                if not path.is_file():
                    raise ValueError('Non-regular source member: ' + str(path))
                result.add(path.relative_to(workspace).as_posix())
    if len({r.casefold() for r in result}) != len(result):
        raise ValueError('Ambiguous source paths')
    # Specific production files may live beside the app. Declare them in the
    # existing exclude field, with a purpose; never use generic folder globs.
    extra=spec.get('exclude', [])
    if not isinstance(extra,list):raise ValueError('exclude must be a list')
    for item in extra:
        if isinstance(item,dict):
            if set(item)!={'path','reason'} or item['reason'] not in {
                    'production-analysis','production-record','production-tool',
                    'original-material','runtime-state','credential','source-archive-copy'}:
                raise ValueError('Exact exclusion requires a recognized cleanup purpose')
            if not isinstance(item['path'],str) or any(c in item['path'] for c in '*?['):
                raise ValueError('Explicit cleanup must name one exact file')
            inside(workspace,item['path'])
        elif not isinstance(item,str):raise ValueError('Invalid exclusion')
    # Old broad globs cannot recreate a small source whitelist.
    for relative in result:
        for pattern in extra:
            if isinstance(pattern,dict):continue
            if (PurePosixPath(relative).match(pattern) or relative == pattern or
                    relative.startswith(pattern.rstrip('/') + '/')) and not exclusion(relative, keep_runtime=keep_runtime):
                raise ValueError('Cannot exclude retained project file: ' + relative)
    return sorted(result)
