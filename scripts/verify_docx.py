"""Verify preservation and final-image identity without claiming rendered visual correctness."""
from pathlib import Path
import argparse, collections, hashlib, json, zipfile
from lxml import etree as E

NS={'w':'http://schemas.openxmlformats.org/wordprocessingml/2006/main','m':'http://schemas.openxmlformats.org/officeDocument/2006/math'}
def sha(data):return hashlib.sha256(data).hexdigest()
def tree_value(node):
    return [node.tag,sorted(node.attrib.items()),node.text if node.text and node.text.strip() else '',[tree_value(c) for c in node]]
def scan(path):
    with zipfile.ZipFile(path) as z:
        if z.testzip() is not None:raise ValueError(f'Corrupt ZIP: {path}')
        root=E.fromstring(z.read('word/document.xml'),parser=E.XMLParser(resolve_entities=False,no_network=True))
        paragraphs=[''.join(p.xpath('.//w:t/text() | .//m:t/text()',namespaces=NS)).strip() for p in root.xpath('//w:body//w:p',namespaces=NS)]
        math=[sha(json.dumps(tree_value(n),ensure_ascii=False).encode('utf-8')) for n in root.xpath('//m:oMath',namespaces=NS)]
        media={n:sha(z.read(n)) for n in z.namelist() if n.startswith('word/media/')}
        return {'paragraphs':[t for t in paragraphs if t],'math':math,'media':media}

def verify(original,revised,figures=()):
    original=Path(original);revised=Path(revised)
    a,b=scan(original),scan(revised);cursor=0;missing=[]
    for i,text in enumerate(a['paragraphs']):
        try:cursor=b['paragraphs'].index(text,cursor)+1
        except ValueError:missing.append({'nonempty_paragraph':i+1,'text':text[:160]})
    missing_math=list((collections.Counter(a['math'])-collections.Counter(b['math'])).elements())
    final_media=set(b['media'].values())
    missing_media=[n for n,h in a['media'].items() if h not in final_media]
    figures_result=[{'path':str(p),'sha256':sha(Path(p).read_bytes()),'embedded':sha(Path(p).read_bytes()) in final_media} for p in figures]
    return {'original_sha256':sha(original.read_bytes()),'revised_sha256':sha(revised.read_bytes()),
            'original_paragraphs':len(a['paragraphs']),'revised_paragraphs':len(b['paragraphs']),
            'missing_original_paragraphs':missing,'original_omml':len(a['math']),'revised_omml':len(b['math']),
            'changed_or_missing_original_formula_count':len(missing_math),'missing_original_media':missing_media,
            'figures':figures_result,'structural_preservation_ok':not missing and not missing_math and not missing_media,
            'all_requested_figures_embedded':all(x['embedded'] for x in figures_result),
            'rendered_visual_status':'not_checked','note':'Does not prove figure order, captions, red color, semantic source mapping or page layout; inspect final rendered pages.'}

def main():
    p=argparse.ArgumentParser();p.add_argument('original',type=Path);p.add_argument('revised',type=Path);p.add_argument('--figure',action='append',default=[],type=Path);p.add_argument('--output',type=Path);a=p.parse_args()
    r=verify(a.original,a.revised,a.figure);text=json.dumps(r,ensure_ascii=False,indent=2)
    if a.output:a.output.parent.mkdir(parents=True,exist_ok=True);a.output.write_text(text,encoding='utf-8')
    print(text)
    if not r['structural_preservation_ok'] or not r['all_requested_figures_embedded']:raise SystemExit(2)
if __name__=='__main__':main()
