"""Cover-bound case-title cleanup, used inside Word writing and existing checks.

Only the redundant literal prefix is removed. No generic '一种' replacement,
cover rewrite, format normalization, or post-review mutation is performed.
"""
from pathlib import Path
import os
import re
import tempfile
import zipfile
from xml.dom import minidom
import xml.etree.ElementTree as ET

POLICY = 'cover-title-prefix-v1'
W = 'http://schemas.openxmlformats.org/wordprocessingml/2006/main'
STORY = re.compile(r'word/(?:document|header\d+|footer\d+|footnotes|endnotes)\.xml\Z')
SECTION_HEADINGS = {'技术摘要', '摘要', '背景资料', '背景技术', '技术领域', '实施方式', '具体实施方式', '权利要求书'}


def cover_title(data, expected):
    """Require an actual standalone cover paragraph, anchored to run title."""
    expected = ''.join(expected.split())
    if not expected:
        raise ValueError('Case title is required')
    allowed = {expected, '一种' + expected}
    if expected.startswith('一种'):
        allowed.add(expected[2:])
    root = ET.fromstring(data)
    for paragraph in list(root.iter('{' + W + '}p'))[:30]:
        text = ''.join(
            ''.join(t.text or '' for t in paragraph.iter('{' + W + '}t')).split())
        if text in SECTION_HEADINGS:
            break
        if text in allowed:
            return text
        if any(b.get('{' + W + '}type') == 'page' for b in paragraph.iter('{' + W + '}br')):
            break
    raise ValueError('Cannot locate standalone cover case title matching run title; do not guess or rewrite cover')


def _edits(text, title):
    if title.startswith('一种'):
        return []
    # Match complete-title references independent of the following sentence.
    # Protect explicitly extended technical names, not arbitrary Chinese prose.
    extension = re.compile(r'(?:(?:及|和|与)(?:其)?(?:系统|方法|装置|设备|介质)|(?:扩展|改进|优化|辅助|衍生)?(?:算法|模型|系统|装置|设备))')
    pattern = re.compile(r'(?:一种)+' + re.escape(title))
    return [(m.start(), m.end() - len(title)) for m in pattern.finditer(text)
            if not extension.match(text[m.end():])]


def normalize_element(root, title):
    """Canonicalize only title prefixes for the existing source-integrity check."""
    count = 0
    for paragraph in root.iter('{' + W + '}p'):
        nodes = []
        def collect(node):
            for child in node:
                if child.tag == '{' + W + '}p':
                    continue
                if child.tag == '{' + W + '}t':
                    nodes.append(child)
                else:
                    collect(child)
        collect(paragraph)
        spans = _edits(''.join(n.text or '' for n in nodes), title)
        offset = 0
        for node in nodes:
            text = node.text or ''
            node.text = ''.join(c for i, c in enumerate(text, offset)
                                if not any(a <= i < b for a, b in spans)) or None
            offset += len(text)
        count += len(spans)
    return count


def normalized_part(data, title):
    """Preserve namespaces/run properties/media; touch text nodes only."""
    doc = minidom.parseString(data)
    count = 0
    for paragraph in doc.getElementsByTagNameNS(W, 'p'):
        nodes = []
        for node in paragraph.getElementsByTagNameNS(W, 't'):
            ancestor = node.parentNode
            while ancestor is not None and not (ancestor.namespaceURI == W and ancestor.localName == 'p'):
                ancestor = ancestor.parentNode
            if ancestor is paragraph:
                nodes.append(node)
        texts = [''.join(c.data for c in n.childNodes if c.nodeType in (c.TEXT_NODE, c.CDATA_SECTION_NODE)) for n in nodes]
        spans = _edits(''.join(texts), title)
        offset = 0
        for node, text in zip(nodes, texts):
            value = ''.join(c for i, c in enumerate(text, offset) if not any(a <= i < b for a, b in spans))
            offset += len(text)
            if value != text:
                for child in list(node.childNodes):
                    node.removeChild(child)
                if value:
                    node.appendChild(doc.createTextNode(value))
        count += len(spans)
    return (doc.toxml(encoding='utf-8') if count else data), count


def check_title(word, source, expected):
    with zipfile.ZipFile(source) as original, zipfile.ZipFile(word) as current:
        title = cover_title(original.read('word/document.xml'), expected)
        if cover_title(current.read('word/document.xml'), expected) != title:
            raise ValueError('Final cover title differs from source cover title')
        findings = {n: normalized_part(current.read(n), title)[1] for n in current.namelist() if STORY.fullmatch(n)}
        findings = {n: count for n, count in findings.items() if count}
        if findings:
            raise ValueError('Case title has redundant 一种 relative to cover: ' + str(findings))
    return {'policy': POLICY, 'cover_title': title, 'redundant_prefixes': 0}


def normalize_written_word(word, source, expected):
    """Call immediately after builder saves, before rendering, hashes or review."""
    word, source = Path(word), Path(source)
    if word.resolve() == source.resolve() or os.path.samefile(word, source):
        raise ValueError('Source Word is read-only; normalize an output copy')
    with zipfile.ZipFile(source) as original:
        title = cover_title(original.read('word/document.xml'), expected)
    with zipfile.ZipFile(word) as archive:
        if cover_title(archive.read('word/document.xml'), expected) != title:
            raise ValueError('Final cover title differs from source cover title')
        changes = {}
        count = 0
        for name in archive.namelist():
            if STORY.fullmatch(name):
                data, total = normalized_part(archive.read(name), title)
                if total:
                    changes[name] = data
                    count += total
        if not changes:
            return {'cover_title': title, 'replacements': 0}
        fd, temp = tempfile.mkstemp(prefix='.title-', suffix='.docx', dir=word.parent)
        os.close(fd)
        try:
            with zipfile.ZipFile(temp, 'w') as output:
                output.comment = archive.comment
                for item in archive.infolist():
                    output.writestr(item, changes.get(item.filename, archive.read(item.filename)))
            with zipfile.ZipFile(temp) as output:
                if output.testzip() is not None:
                    raise ValueError('Word ZIP verification failed')
        except BaseException:
            Path(temp).unlink(missing_ok=True)
            raise
    try:
        os.replace(temp, word)
    finally:
        Path(temp).unlink(missing_ok=True)
    return {'cover_title': title, 'replacements': count}
