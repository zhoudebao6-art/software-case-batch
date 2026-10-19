"""Build a local, shallow delivery directory index without reviewing artifacts."""
import argparse
from datetime import datetime, timezone
import html
import json
import os
from pathlib import Path
import re
import tempfile

from common import no_links

CENTER = '00_交付中心'
PAGE = '打开交付总览.html'
MARKER = '<!-- scb-delivery-index-v1 -->'
LAYOUTS = [('系统材料', '源代码.zip', '操作视频.mp4'), ('模拟系统', '项目源码.zip', '演示视频.mp4')]


def children(path):
    """Do not follow reparse points or inspect hidden working/candidate trees."""
    result = []
    for child in sorted(path.iterdir(), key=lambda p: p.name.casefold()):
        if child.name.startswith('.') or child.name == CENTER:
            continue
        try:
            no_links(child)
        except ValueError:
            continue
        result.append(child)
    return result


def present(path):
    try:
        path = no_links(path)
        return path.is_file() and path.stat().st_size > 0
    except (OSError, ValueError):
        return False


def case_entry(path, group):
    items = children(path)
    words = [p for p in items if p.suffix.lower() == '.docx' and present(p)]
    systems = [row for row in LAYOUTS if (path / row[0]).is_dir()]
    if not words and not systems:
        return None
    links = {'folder': str(path), 'words': [str(p) for p in words], 'source': '', 'video': '', 'data': ''}
    if systems:
        system, source, video = systems[0]
        for key, filename in [('source', source), ('video', video)]:
            candidate = path / system / filename
            if present(candidate):
                links[key] = str(candidate)
        data = path / system / '数据'
        try:
            if no_links(data).is_dir() and any(p.suffix.lower() == '.csv' and present(p) for p in children(data)):
                links['data'] = str(data)
        except (OSError, ValueError):
            pass
    return {'batch': group, 'title': path.name, **links}


def collect(root):
    cases, packages = [], []

    def walk(path, group, depth):
        entry = case_entry(path, group)
        if entry:
            cases.append(entry)
            return  # Never descend into system source/data or nested ZIPs.
        if depth <= 0:
            return
        for child in children(path):
            if child.is_dir():
                walk(child, group if depth == 1 else child.name, depth - 1)
            elif child.suffix.lower() == '.zip' and present(child):
                packages.append(str(child))

    for path in children(root):
        if path.is_dir():
            walk(path, path.name, 4)
        elif path.suffix.lower() == '.zip' and present(path):
            packages.append(str(path))
    # Parent directory is the batch for both ordinary and collection deliveries.
    for entry in cases:
        entry['batch'] = Path(entry['folder']).parent.name
    return sorted(cases, key=lambda c: (c['batch'], c['title'])), sorted(set(packages))


def link(path, label):
    if not path:
        return '<span class="missing">未找到</span>'
    return f'<a href="{html.escape(Path(path).as_uri(), quote=True)}">{html.escape(label)}</a>'


def render(root, cases, packages, featured):
    groups = sorted({c['batch'] for c in cases}, reverse=True)
    options = ''.join(f'<option>{html.escape(g)}</option>' for g in groups)
    rows = []
    for c in cases:
        search = html.escape(c['batch'] + ' ' + c['title'], quote=True)
        word = ' '.join(link(p, 'Word' if len(c['words']) == 1 else Path(p).stem) for p in c['words']) or '<span class="missing">未找到</span>'
        rows.append(f'<tr data-search="{search}" data-batch="{html.escape(c["batch"], quote=True)}"><td>{html.escape(c["batch"])}</td>'
                    f'<td>{html.escape(c["title"])}</td><td class="actions">{link(c["folder"], "案件文件夹")} {word} '
                    f'{link(c["source"], "源码")} {link(c["video"], "视频")} {link(c["data"], "数据")}</td></tr>')
    featured_html = ''.join(f'<li>{link(str(p), p.name)}</li>' for p in featured)
    packages_html = ''.join(f'<li>{link(p, str(Path(p).relative_to(root)))}</li>' for p in packages)
    return MARKER + '''<!doctype html><html lang="zh-CN"><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>案件交付中心</title><style>
*{box-sizing:border-box}body{margin:0;background:#f5f6f8;color:#19212c;font:16px/1.65 "Microsoft YaHei",sans-serif}
main{max-width:1380px;margin:32px auto;padding:0 28px}h1{margin:0;font-size:30px}h2{font-size:20px;margin:0 0 12px}
p{color:#596576}section{background:white;border:1px solid #dfe4ea;border-radius:10px;padding:22px;margin:20px 0}
a{color:#1458a3;text-decoration:none}a:hover{text-decoration:underline}ul{padding-left:22px;margin:0}li{padding:5px 0;overflow-wrap:anywhere}
.toolbar{display:flex;gap:12px;margin:16px 0;flex-wrap:wrap}input,select{font:inherit;border:1px solid #bcc5d0;border-radius:6px;padding:9px 12px}input{flex:1;min-width:230px}
table{border-collapse:collapse;width:100%}th,td{text-align:left;padding:13px 10px;border-bottom:1px solid #e6eaf0;vertical-align:top}th{font-size:14px;color:#556272}
td:first-child{width:170px;font-size:14px}td:nth-child(2){min-width:320px}.actions{min-width:290px}.actions a{display:inline-block;margin:0 10px 5px 0;white-space:nowrap}
.missing{color:#9c3440;font-size:13px;margin-right:8px}.count{font-size:14px;color:#596576}.scroll{overflow:auto}details summary{cursor:pointer;font-weight:bold}code{overflow-wrap:anywhere}
</style><main><h1>案件交付中心</h1><p>本次要取的文件放在最上方；下方可按批次或案件名称查找。</p>
<section><h2>本次交付</h2><ul>''' + (featured_html or '<li>暂无本次汇总包，可从下方打开已有案件。</li>') + '''</ul></section>
<section><h2>按批次查找案件</h2><div class="toolbar"><input id="q" placeholder="搜索案件名称，例如：电压、患者、重写" aria-label="搜索案件"><select id="batch" aria-label="选择批次"><option value="">全部批次</option>''' + options + '''</select></div><p class="count" id="count"></p><div class="scroll"><table><thead><tr><th>批次</th><th>案件名称</th><th>打开材料</th></tr></thead><tbody>''' + ''.join(rows) + '''</tbody></table></div></section>
<section><details><summary>现有压缩包</summary><ul>''' + (packages_html or '<li>暂无独立压缩包</li>') + '''</ul></details></section>
<p class="count">此页仅整理文件位置，不改变原验收结论；客户是否收件不自动判定。目录文件有变化时，双击“刷新交付目录”。</p></main>
<script>const q=document.getElementById('q'),batch=document.getElementById('batch'),rows=[...document.querySelectorAll('tbody tr')];
function filter(){let n=0;for(const r of rows){const visible=(!batch.value||r.dataset.batch===batch.value)&&r.dataset.search.toLowerCase().includes(q.value.trim().toLowerCase());r.hidden=!visible;if(visible)n++;}document.getElementById('count').textContent='显示 '+n+' 个案件目录，共 '+rows.length+' 个';}q.addEventListener('input',filter);batch.addEventListener('change',filter);filter();</script></html>'''


def refresh(root):
    root = no_links(root)
    if not root.is_dir():
        raise ValueError('Delivery root must already exist')
    center = no_links(root / CENTER)
    target = no_links(center / PAGE)
    if target.exists() and not target.read_text(encoding='utf-8').startswith(MARKER):
        raise ValueError('Preserve unrelated existing index file')
    cases, packages = collect(root)
    featured_dir = no_links(center / '01_本次交付')
    featured = [p for p in children(featured_dir) if p.is_file() and p.suffix.lower() in {'.zip', '.xlsx', '.pdf'} and present(p)] if featured_dir.exists() else []
    page = render(root, cases, packages, featured)
    center.mkdir(parents=True, exist_ok=True)
    # Unique temporary name: simultaneous refreshes cannot truncate one another.
    fd, temporary = tempfile.mkstemp(prefix='.index-', suffix='.tmp', dir=center)
    try:
        with os.fdopen(fd, 'w', encoding='utf-8', newline='\n') as stream:
            stream.write(page); stream.flush(); os.fsync(stream.fileno())
        os.replace(temporary, target)
    finally:
        Path(temporary).unlink(missing_ok=True)
    return {'status': 'indexed', 'page': str(target), 'case_directories': len(cases), 'packages': len(packages),
            'featured': len(featured), 'artifact_contents_read': False, 'acceptance_or_customer_delivery_inferred': False,
            'updated_at_utc': datetime.now(timezone.utc).isoformat()}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', required=True)
    args = parser.parse_args()
    try:
        print(json.dumps(refresh(args.root), ensure_ascii=False))
    except (OSError, ValueError) as error:
        parser.exit(2, str(error) + '\n')


if __name__ == '__main__':
    main()
