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

LEGACY_DELIVERY_LAYOUT = 'legacy-v1'
DEFAULT_DELIVERY_LAYOUT = 'system-materials-v2'
_DELIVERY_LAYOUTS = {
    LEGACY_DELIVERY_LAYOUT: ('模拟系统', '项目源码.zip', '演示视频.mp4'),
    DEFAULT_DELIVERY_LAYOUT: ('系统材料', '源代码.zip', '操作视频.mp4'),
}


def delivery_paths(run, output=None):
    """Resolve only the run's frozen layout, including historical missing fields.

    Stored absolute aliases belong to the original output, even when an archive
    locator supplies a different current output. They may never override layout.
    """
    version = run.get('delivery_layout_version', LEGACY_DELIVERY_LAYOUT)
    if not isinstance(version, str) or version not in _DELIVERY_LAYOUTS:
        raise ValueError(f'Unknown frozen delivery layout: {version!r}')
    system, source, video = _DELIVERY_LAYOUTS[version]
    if not isinstance(run.get('output'),str) or not Path(run['output']).is_absolute():
        raise ValueError('Frozen delivery output must be an explicit absolute path')
    original = no_links(run['output'])
    root = no_links(output) if output is not None else original
    relative = {'system': system, 'source_zip': system+'/'+source,
                'video': system+'/'+video, 'data_dir': system+'/数据'}
    if 'word_name' in run:
        name = run['word_name']
        if (not isinstance(name, str) or not name or name in {'.', '..'}
                or any(char in name for char in ('/', '\\', ':'))
                or Path(name).suffix.lower() != '.docx'):
            raise ValueError('Frozen Word name must be the original simple .docx filename')
        relative['word'] = name
    for key, rel in relative.items():
        if key in run and (not isinstance(run[key], str) or not Path(run[key]).is_absolute()
                           or no_links(run[key]) != inside(original, rel, must_exist=False)):
            raise ValueError(f'Frozen delivery path differs from layout: {key}')
    return {'version': version, 'system_name': system, 'source_name': source,
            'video_name': video, 'output': root,
            **{key: inside(root, rel, must_exist=False) for key, rel in relative.items()}}

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
    delivery_paths(run, output)
    if output == workspace or output in workspace.parents or workspace in output.parents:
        raise ValueError('Delivery and work directories must be disjoint')
    return workspace, output, run

def product_location(workspace,run):
    """Resolve a verified weekly archive without rewriting the frozen run."""
    workspace=no_links(workspace)
    original=no_links(run['output'])
    delivery_paths(run)
    if run.get('status')!='published':return original
    config_path=Path(__file__).resolve().parents[1]/'local.config.json'
    config=read_json(config_path) if config_path.exists() else {}
    state_root=os.environ.get('SCB_PRO_ARCHIVE_STATE_ROOT') or config.get('archive_state_root')
    if not state_root:return original
    state_root=no_links(state_root)
    if not (state_root/'current-locations.json').exists():return original
    receipt=read_json(inside(workspace,'.product-v2/final-receipt.json'))
    if ('delivery_layout_version' in receipt and receipt['delivery_layout_version']!=delivery_paths(run)['version']):
        raise ValueError('Archive layout differs from the frozen acceptance receipt')
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


if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser(description='Read the frozen delivery paths without mutation')
    parser.add_argument('--delivery-paths', required=True, metavar='WORKSPACE')
    args = parser.parse_args()
    workspace, output, run = state(args.delivery_paths)
    result = delivery_paths(run, output)
    result['run_sha256'] = digest(workspace / '.product-v2/run.json')
    print(json.dumps({key: str(value) if isinstance(value, Path) else value for key, value in result.items()}, ensure_ascii=False))
