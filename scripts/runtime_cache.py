"""Case-owned runtime snapshots within the existing source export, never services.

Mutable cache bytes are delivery data, not implementation revisions. Actual
algorithm inputs remain bound by the original execution input_files contract.
"""
from pathlib import PurePosixPath
from contextlib import closing
import csv
import io
import json
import re
import sqlite3
import time
import gzip
import zipfile
import hashlib

POLICY = 'clean-source-cache-directory-v4'
DATA_SUFFIXES = {'.json', '.jsonl', '.csv', '.tsv', '.npy', '.npz', '.parquet',
    '.arrow', '.bin', '.dat', '.db', '.sqlite', '.sqlite3', '.idx', '.index',
    '.pt', '.pth', '.onnx', '.safetensors', '.model', '.pkl', '.pickle',
    '.txt', '.ldb', '.sst', '.cache', '.gz', '.zip', '.zst', ''}
PRIVATE_NAMES = {'cookies', 'cookies.sqlite', 'cookies.json', 'login data',
    'web data', 'local state', 'storage-state.json', 'storage_state.json',
    'browser-state.json'}
SECRET_FIELD = re.compile(r'^(?:password(?:_hash)?|passwd|api[_-]?key|client_secret|'
    r'access[_-]?token|refresh[_-]?token|session[_-]?token|authorization|'
    r'cookie|private_key|secret|_authToken|_auth)$', re.I)
PRIVATE_MARKER = re.compile(rb'private.{0,12}key|bearer\b|(?:access|refresh|session)[_-]?token|password|passwd|api[_-]?key|client_secret|authorization|cookie|secret|azure_storage_key|_auth|\\u[0-9a-f]{4}', re.I)


def enabled(run):
    return run.get('source_delivery_policy') == POLICY


def roots(spec):
    values = spec.get('runtime_cache_roots', [])
    if not isinstance(values, list) or not all(isinstance(v, str) and v for v in values):
        raise ValueError('runtime_cache_roots must list case-local directories')
    result = []
    for value in values:
        p = PurePosixPath(value.replace('\\', '/'))
        if p.is_absolute() or '..' in p.parts or ':' in value or not p.parts:
            raise ValueError('Unsafe runtime cache root')
        for source in spec.get('source_roots', []):
            s = PurePosixPath(source.replace('\\','/')).as_posix().casefold()
            if s == p.as_posix().casefold() or s.startswith(p.as_posix().casefold() + '/'):
                raise ValueError('Runtime cache root cannot contain an application source root')
        result.append(p.as_posix().casefold())
    return result


def member(relative, spec):
    p = PurePosixPath(relative.replace('\\', '/'))
    name = p.as_posix().casefold()
    in_root = '.cache' in [v.casefold() for v in p.parts[:-1]] or any(
        name.startswith(r + '/') for r in roots(spec))
    # Code/config not identified as cache data never escapes implementation checks.
    if re.search(r'(?i)(?:^|[._-])(?:config|settings|schema|manifest|lock)(?:[._-]|$)', p.name) or p.name.casefold() in {'dockerfile','makefile','procfile'}:
        return False
    return in_root and (p.suffix.casefold() in DATA_SUFFIXES or
        p.name.casefold().endswith(('-wal', '-shm', '-journal')))


def evidence_path(workspace, run, package, relative):
    """Resolve only typed runtime data to its immutable in-workspace export copy."""
    from common import inside, digest
    if not enabled(run):
        return inside(workspace, relative)
    mapping = package.get('runtime_cache_evidence', {})
    if relative not in mapping:
        return inside(workspace, relative)
    frozen = mapping[relative]
    p = PurePosixPath(frozen)
    if not p.as_posix().startswith('.product-v2/source-cache/'):
        raise ValueError('Runtime evidence must be the internal export snapshot')
    path = inside(workspace, frozen)
    if not member(relative, package) and not (
            relative in package.get('runtime_snapshots', {}) and
            PurePosixPath(relative).suffix.casefold() in DATA_SUFFIXES and is_sqlite(path)):
        raise ValueError('Implementation cannot be exempted as runtime cache')
    expected = package.get('files', {}).get(relative)
    if not expected or package.get('runtime_cache_files', {}).get(relative) != expected or digest(path) != expected:
        raise ValueError('Frozen runtime snapshot changed')
    return path


def private_value(value):
    if value is None or value is False or value is True or isinstance(value, (dict, list)):
        return False
    value = str(value).strip()
    return bool(value and value.casefold() not in {
        'null', 'none', 'changeme', 'change_me', 'example', 'placeholder',
        'your_api_key', 'your_password', 'your_token'} and not
        re.fullmatch(r'\$\{[^}]+\}|<[^>]+>|%[^%]+%', value))


def text_private(relative, data, depth=0):
    """Common structured cache credentials; no secret values in diagnostics."""
    from retained_source import credential_content
    suffix = PurePosixPath(relative).suffix.casefold()
    if suffix in {'.gz','.zip'}:
        if depth >= 2:return True
        limit=128*1024*1024
        try:
            if suffix=='.gz':
                with gzip.GzipFile(fileobj=io.BytesIO(data)) as stream:raw=stream.read(limit+1)
                return len(raw)>limit or bool(exclusion(relative[:-3])) or text_private(relative[:-3],raw,depth+1)
            with zipfile.ZipFile(io.BytesIO(data)) as archive:
                if sum(x.file_size for x in archive.infolist())>limit:return True
                from retained_source import exclusion as source_exclusion
                return any(not x.is_dir() and (x.flag_bits&1 or source_exclusion(x.filename,keep_runtime=True) or text_private(x.filename,archive.read(x),depth+1)) for x in archive.infolist())
        except (OSError,ValueError,zipfile.BadZipFile,EOFError):return True
    if credential_content('cache.json', data):
        return True
    try:
        text = data.decode('utf-16' if data.startswith((b'\xff\xfe', b'\xfe\xff')) else 'utf-8-sig')
    except UnicodeError:
        # Binary caches can still contain embedded plain-text credentials.
        text = data.decode('utf-8', errors='ignore')
    if re.search(r'(?i)\bBearer\s+[A-Za-z0-9_.~+/=-]{8,}', text):
        return True
    def walk(obj):
        if isinstance(obj, dict):
            return any((SECRET_FIELD.fullmatch(str(k)) and private_value(v)) or walk(v)
                for k, v in obj.items())
        return isinstance(obj, list) and any(walk(v) for v in obj)
    try:
        if suffix == '.json' or (suffix not in {'.jsonl','.csv','.tsv'} and text.lstrip().startswith(('{','['))):
            return walk(json.loads(text))
        if suffix == '.jsonl':
            return any(walk(json.loads(line)) for line in text.splitlines() if line.strip())
        if suffix in {'.csv', '.tsv'}:
            return any(walk(row) for row in csv.DictReader(io.StringIO(text), delimiter='\t' if suffix == '.tsv' else ','))
    except (ValueError, csv.Error):
        # Parsing cannot establish that malformed runtime data is safe to ship.
        return True
    return False


def exclusion(relative, data=None):
    p = PurePosixPath(relative.replace('\\', '/'))
    if p.name.casefold() in PRIVATE_NAMES or any(x.casefold() in {
            'browser-profile', 'browser_profile', 'user-data-dir', 'chromium-profile'} for x in p.parts):
        return 'private-runtime-profile'
    if p.name.casefold().endswith(('-wal', '-shm', '-journal')):
        return 'database-sidecar-use-consistent-snapshot'
    if data is not None and p.suffix.casefold() in DATA_SUFFIXES and not data.startswith(b'SQLite format 3\x00') and text_private(relative, data):
        return 'private-runtime-content'
    return None


def is_sqlite(path):
    with path.open('rb') as stream:
        return stream.read(16) == b'SQLite format 3\x00'


def sqlite_private(path):
    """Inspect the frozen DB without executing extensions, views or application code."""
    uri = path.resolve().as_uri() + '?mode=ro&immutable=1'
    with closing(sqlite3.connect(uri, uri=True)) as conn:
        conn.execute('PRAGMA trusted_schema=OFF')
        if conn.execute('PRAGMA quick_check').fetchone() != ('ok',):
            raise ValueError('Runtime database snapshot is invalid')
        tables = conn.execute("SELECT name,sql FROM sqlite_master WHERE type='table'").fetchall()
        for table, ddl in tables:
            if ddl and re.match(r'\s*CREATE\s+VIRTUAL', ddl, re.I):
                continue
            quoted = '"' + table.replace('"', '""') + '"'
            columns = conn.execute('PRAGMA table_info(' + quoted + ')').fetchall()
            names = [row[1] for row in columns]
            for row in conn.execute('SELECT * FROM ' + quoted):
                for name, value in zip(names,row):
                    if SECRET_FIELD.fullmatch(name) and private_value(value):return True
                    if isinstance(value,(str,bytes)):
                        data=value.encode('utf8') if isinstance(value,str) else value
                        # Most business cells are timestamps, object IDs or labels.
                        # Parse only possible secret-bearing payloads, same rule set.
                        if PRIVATE_MARKER.search(data.replace(b'\x00',b'')) and text_private('value.txt', data):return True
    return False


def snapshot(source, target, timeout=15):
    """SQLite online backup includes committed WAL; does not checkpoint source.

    The destination is an internal per-export scratch file. Nothing is opened
    on a network; no service, package installer or source rewrite is involved.
    """
    target.parent.mkdir(parents=True, exist_ok=True)
    deadline = time.monotonic() + timeout
    def progress(status, remaining, total):
        if time.monotonic() > deadline:
            raise ValueError('Runtime snapshot busy; retry only this cache export')
    uri = source.resolve().as_uri() + '?mode=ro'
    with closing(sqlite3.connect(uri, uri=True, timeout=1)) as src:
        src.execute('PRAGMA query_only=ON')
        with closing(sqlite3.connect(target)) as dst:
            src.backup(dst, pages=256, progress=progress, sleep=0.02)
    # Force a standalone database, no destination WAL sidecars to ship.
    with closing(sqlite3.connect(target)) as dst:
        dst.execute('PRAGMA trusted_schema=OFF')
        dst.execute('PRAGMA journal_mode=DELETE')
        before = rowid_bindings(dst)
        # Remove deleted-row/free-page bytes from the private copy only.
        dst.execute('VACUUM')
        if rowid_bindings(dst) != before:
            raise ValueError('Runtime snapshot compaction changes implicit rowid references; retain source and export this cache using stable business keys')
    return 'private-runtime-database' if sqlite_private(target) else None


def rowid_bindings(conn):
    """VACUUM may renumber implicit rowids; reject changed business identities."""
    result = {}
    tables=conn.execute("SELECT name,sql FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'").fetchall()
    for name,ddl in tables:
        if not ddl or re.search(r'(?i)\bWITHOUT\s+ROWID\b|\bCREATE\s+VIRTUAL\b',ddl):continue
        table='"'+name.replace('"','""')+'"'
        columns=conn.execute('PRAGMA table_info('+table+')').fetchall()
        names={c[1].casefold() for c in columns}
        alias=next((key for key in ('rowid','_rowid_','oid') if key not in names),None)
        if alias is None:
            # All aliases are shadowed; implicit rowid is not addressable by the app.
            continue
        hashed=hashlib.sha256()
        for row in conn.execute('SELECT '+alias+',* FROM '+table+' ORDER BY '+alias):
            payload=json.dumps(row,ensure_ascii=False,separators=(',',':'),default=lambda v:{'bytes':v.hex()}).encode('utf8')
            hashed.update(len(payload).to_bytes(8,'big'));hashed.update(payload)
        result[name]=hashed.hexdigest()
    return result
