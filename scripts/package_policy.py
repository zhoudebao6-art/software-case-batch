"""Delivery inspection; never alter source text or business data."""
import base64
import html
from pathlib import PurePosixPath
import re
import unicodedata
from urllib.parse import unquote

CHINESE_TERMS = ('模拟', '虚拟', '仿真', '物理仿真', '参考', '源文件', '公式', '正文')
DOCUMENT_SUFFIXES = {'.txt', '.md', '.rst', '.html', '.htm', '.pdf', '.doc', '.docx', '.json', '.yaml', '.yml'}
_DOC_NAMES = re.compile(
    r'((?:运行|使用|操作|安装|部署)[\s._-]*(?:说明|指南|手册)|用户手册|开发说明|开发文档|设计制作说明|'
    r'制作过程|制作说明|生成过程|生成说明|原件解析|原文解析|文档解析|原件分析|原文分析|'
    r'材料解析|源文档解析|技术文档解析|ai制作|ai生成说明|提示词|命令词|'
    r'^(?:user|usage|operation|run|running|runtime|setup|installation|deployment|developer|development|'
    r'design|manufacturing|making|generation|production)[\s._-]*(?:guide|manual|instructions?|notes?|readme|process|documentation)|'
    r'^(?:usage|instructions|user[\s._-]*manual|getting[\s._-]*started|how[\s._-]*to|development|deployment|'
    r'source[\s._-]*(?:analysis|extraction|mapping)|document[\s._-]*(?:analysis|extraction)|'
    r'docx[\s._-]*(?:analysis|extract)|ai[\s._-]*(?:process|generation|prompt)|prompts?)(?:$|[\s._-]))', re.I)
_PROCESS_PATTERNS = (
    ('data-nature', r'\b(?:synthetic|simulated|mock|artificial|dummy|fake)[\s_-]*(?:data(?:set)?s?|records?|measurements?|samples?)\b'),
    ('data-nature', r'\bdata\s+(?:are|is|were|was)\s+(?:synthetic|simulated|mock|artificial|generated)\b'),
    ('data-nature', r'\b(?:calculation|computed|generated)[\s_-]+(?:outputs?|data(?:set)?s?|records?)\b'),
    ('data-nature', r'\bnot\s+(?:(?:field|actual|real|on[\s-]*site)\s+)?measurements?\b'),
    ('data-nature', r'\b(?:not|no)\s+(?:measurements?|records?|data)\s+from\b'),
    ('production-process', r'\blocal\s+(?:software\s+)?evaluation\b'),
    ('production-process', r'\b(?:ai|llm|chatgpt|codex)[\s_-]+(?:generated|created|produced|generation|prompt)\b'),
    ('production-process', r'\b(?:generated|created|produced)\s+by\s+(?:an?\s+)?(?:ai|llm|chatgpt|codex)\b'),
    ('production-process', r'\b(?:source|original|technical)\s+(?:document|docx|material)\s+(?:analysis|extraction|parsing|mapping)\b'),
    ('production-process', r'(?:数据性质|计算构造数据|非现场|并非现场|非实测|并非实测|AI[制作生成]+|人工智能生成|提示词|命令词|制作过程|原件解析|原文解析|文档解析)'),
    ('production-process', r'\b(?:system\s+prompt|prompt\s+(?:engineering|used|template)|seed\s+(?:used|for\s+data\s+generation))\b'),
)


def _normalize(text):
    return ''.join(c for c in unicodedata.normalize('NFKC', text) if unicodedata.category(c) != 'Cf')


def excluded_delivery_document(relative):
    """Return an exclusion reason for guides/process artifacts, not all text files."""
    path = PurePosixPath(_normalize(str(relative)).replace('\\', '/'))
    for part in path.parts:
        if re.match(r'^read[\s._-]*me(?:$|[\s._-])', part, re.I):
            return 'delivery-readme'
    if path.suffix.casefold() in DOCUMENT_SUFFIXES:
        if _DOC_NAMES.search(path.stem):
            return 'delivery-guide-or-production-document'
        for part in path.parts[:-1]:
            if _DOC_NAMES.search(part):
                return 'delivery-guide-or-production-document'
    return None


def _decode_escapes(text):
    def convert(match):
        try:
            raw = match.group(0)
            if raw.startswith('\\u{'):
                return chr(int(raw[3:-1], 16))
            return chr(int(raw[2:], 16))
        except (ValueError, OverflowError):
            return match.group(0)
    decoded = re.sub(r'\\(?:u\{[0-9a-fA-F]{1,6}\}|u[0-9a-fA-F]{4}|U[0-9a-fA-F]{8}|x[0-9a-fA-F]{2})', convert, text)
    # CSS escaped Unicode and constant JavaScript character constructors.
    decoded = re.sub(r'\\([0-9a-fA-F]{4,6})(?:\s|(?=[\\"\']))', lambda m: chr(int(m[1],16)) if int(m[1],16)<=0x10ffff else m[0], decoded)
    def chars(match):
        try:
            return ''.join(chr(int(v.strip(),0) if v.strip().lower().startswith('0x') else int(v.strip())) for v in match[1].split(','))
        except (ValueError, OverflowError):
            return match[0]
    return re.sub(r'String\.from(?:CharCode|CodePoint)\(\s*((?:0[xX][0-9a-fA-F]+|\d+)(?:\s*,\s*(?:0[xX][0-9a-fA-F]+|\d+))*)\s*\)', chars, decoded)


def _representations(line):
    current = _normalize(line)
    yield 'literal', current
    for _ in range(3):
        decoded = _normalize(html.unescape(unquote(_decode_escapes(current))))
        # Common literal concatenation in Python/JS, never evaluating code.
        decoded = re.sub(r'''(["'])\s*(?:\+\s*)?["']''', '', decoded)
        if decoded == current:
            break
        yield 'decoded', decoded
        current = decoded
    # Inspect literal encoded payloads, not arbitrary binaries or every identifier.
    for candidate in re.findall(r'''["']([A-Za-z0-9+/]{8,}={0,2})["']''', current):
        try:
            decoded = base64.b64decode(candidate, validate=True).decode('utf-8')
        except (ValueError, UnicodeError):
            continue
        if decoded and all(c.isprintable() or c.isspace() for c in decoded):
            yield 'base64-literal', _normalize(decoded)


def audit_delivery_text(relative, text):
    """Return exact line findings. Legal notices still receive content inspection."""
    hits = []
    for number, line in enumerate(text.splitlines(), 1):
        seen = set()
        for representation, value in _representations(line):
            matches = [('restricted-word', term) for term in CHINESE_TERMS if term in value]
            matches.extend((kind, match.group(0)) for kind, pattern in _PROCESS_PATTERNS
                           for match in re.finditer(pattern, value, re.I))
            for kind, words in matches:
                key = (kind, words.casefold())
                if key not in seen:
                    hits.append({'path': str(relative), 'line': number, 'kind': kind,
                                 'words': [words], 'representation': representation})
                    seen.add(key)
    return hits
