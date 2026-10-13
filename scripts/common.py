"""Small, dependency-free helpers for isolated delivery operations."""
import hashlib
import html
import json
import os
from pathlib import Path
import re
import stat
import unicodedata

BANNED = ('物理仿真', '模拟', '虚拟', '仿真', '参考', '源文件', '公式', '正文')
META_COLUMNS = {'生成数据', '数据来源', '是否生成', '是否生成数据', '生成标记', '数据生成方式',
                '数据来源类型', 'generateddata', 'isgenerated', 'synthetic', 'issynthetic',
                'datasource', 'dataprovenance', 'sourcetype', 'generationmethod'}
TEXT_SUFFIXES = {'.py','.js','.cjs','.mjs','.jsx','.ts','.tsx','.html','.htm','.css','.scss',
                 '.json','.jsonl','.csv','.yaml','.yml','.toml','.ini','.cfg','.env','.txt',
                 '.md','.sql','.sh','.bat','.cmd','.ps1','.xml','.svg','.vue','.svelte',
                 '.java','.kt','.c','.h','.cpp','.cs','.go','.rs','.lock','.properties','.conf',
                 '.ipynb','.r','.example'}

def digest(path):
    h = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            h.update(block)
    return h.hexdigest()

def no_links(path):
    path = Path(path).absolute()
    for item in (path, *path.parents):
        try:
            value = item.lstat()
        except FileNotFoundError:
            continue
        if stat.S_ISLNK(value.st_mode) or getattr(value, 'st_file_attributes', 0) & 0x400:
            raise ValueError(f'Path link/reparse point is not allowed: {item}')
    return path.resolve()

def inside(root, relative, *, must_exist=True):
    root = no_links(root)
    rel = Path(relative)
    if rel.is_absolute() or '..' in rel.parts or ':' in str(rel):
        raise ValueError(f'Unsafe relative path: {relative}')
    path = no_links(root / rel)
    if path == root or root not in path.parents:
        raise ValueError(f'Path escapes root: {relative}')
    if must_exist and not path.is_file():
        raise ValueError(f'Missing regular file: {path}')
    return path

def read_json(path):
    return json.loads(Path(path).read_text(encoding='utf-8-sig'))

def write_json(path, value):
    path = no_links(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    scratch = path.with_name(path.name + '.new')
    no_links(scratch)
    with scratch.open('w', encoding='utf-8', newline='\n') as f:
        json.dump(value, f, ensure_ascii=False, indent=2)
        f.write('\n')
        f.flush()
        os.fsync(f.fileno())
    os.replace(scratch, path)

def normalized(value):
    return re.sub(r'[\s_\-\ufeff]+', '', unicodedata.normalize('NFKC', value)).casefold()

def forbidden(value):
    value = html.unescape(unicodedata.normalize('NFKC', value))
    # Decode common escaped literals for inspection only, never execute them.
    value = re.sub(r'\\u([0-9a-fA-F]{4})', lambda m: chr(int(m[1],16)), value)
    return [word for word in BANNED if word in value]

def state(workspace):
    workspace = no_links(workspace)
    run = read_json(workspace / '.product-v2/run.json')
    if run['workspace'] != str(workspace):
        raise ValueError('Workspace identity differs from preparation record')
    output = product_location(workspace,run)
    if output == workspace or output in workspace.parents or workspace in output.parents:
        raise ValueError('Delivery and work directories must be disjoint')
    return workspace, output, run

def product_location(workspace,run):
    """Resolve a verified weekly archive without rewriting the frozen run."""
    workspace=no_links(workspace)
    original=no_links(run['output'])
    if run.get('status')!='published':return original
    config_path=Path(__file__).resolve().parents[1]/'local.config.json'
    config=read_json(config_path) if config_path.exists() else {}
    state_root=os.environ.get('SCB_PRO_ARCHIVE_STATE_ROOT') or config.get('archive_state_root')
    if not state_root:return original
    state_root=no_links(state_root)
    if not (state_root/'current-locations.json').exists():return original
    receipt=read_json(inside(workspace,'.product-v2/final-receipt.json'))
    from archive_products import resolve_location
    target=resolve_location(state_root,original,receipt['files'])
    if target!=original:
        final_path=inside(workspace,'.product-v2/final-receipt.json')
        publish_path=inside(workspace,'.product-v2/publish-receipt.json')
        published=read_json(publish_path)
        locator=read_json(state_root/'current-locations.json')[str(original)]
        if (run.get('workspace')!=str(workspace) or receipt.get('status')!='complete'
                or receipt.get('delivery_state')!='verified-candidate'
                or published.get('status')!='published'
                or published.get('destination')!=run['output']
                or published.get('files')!=receipt['files']
                or published.get('source_receipt_sha256')!=digest(final_path)
                or locator.get('receipt_sha256')!=digest(final_path)
                or locator.get('publication_sha256')!=digest(publish_path)):
            raise ValueError('Archive locator does not bind the current frozen publication receipts')
        if original.exists():
            current=file_map(original)
            if any(receipt['files'].get(name)!=sha for name,sha in current.items()):
                raise ValueError('Archived source has new or changed files; preserve them and resolve the version conflict')
    return target

def file_map(root):
    root = no_links(root)
    found = {}
    for path in sorted(root.rglob('*')):
        no_links(path)
        if path.is_file():
            found[path.relative_to(root).as_posix()] = digest(path)
    return found
