"""Verify preservation and final-image identity without claiming rendered visual correctness."""
from pathlib import Path
import argparse, collections, hashlib, json, posixpath, re, zipfile
from lxml import etree as E

NS={'w':'http://schemas.openxmlformats.org/wordprocessingml/2006/main','m':'http://schemas.openxmlformats.org/officeDocument/2006/math'}
NS.update(a='http://schemas.openxmlformats.org/drawingml/2006/main', r='http://schemas.openxmlformats.org/officeDocument/2006/relationships', v='urn:schemas-microsoft-com:vml')
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
        rels={}
        if 'word/_rels/document.xml.rels' in z.namelist():
            for rel in E.fromstring(z.read('word/_rels/document.xml.rels'), parser=E.XMLParser(resolve_entities=False,no_network=True)):
                if rel.get('TargetMode') != 'External':
                    target=rel.get('Target','')
                    rels[rel.get('Id')]=media.get(posixpath.normpath(target.lstrip('/') if target.startswith('/') else 'word/'+target))
        blocks=[]
        for node in root.find('w:body', NS):
            if node.tag == '{'+NS['w']+'}sectPr':continue
            ids=node.xpath('.//a:blip/@r:embed | .//v:imagedata/@r:id',namespaces=NS)
            blocks.append({'text': ''.join(node.xpath('.//w:t/text() | .//m:t/text()',namespaces=NS)).strip(),
                           'images':[rels.get(rid) for rid in ids],
                           'has_drawing':bool(node.xpath('.//w:drawing | .//w:pict',namespaces=NS)),
                           'paragraph':node.tag == '{'+NS['w']+'}p'})
        return {'paragraphs':[t for t in paragraphs if t],'math':math,'media':media,'blocks':blocks}

def figure_placement(blocks, figures):
    """Only new pictures/captions may follow the start of the appended figure section.

    Explanatory prose belongs at its source embodiment anchor. Original figures
    are not moved or counted. Visual layout and prose relevance still need review.
    """
    wanted=[f['sha256'] for f in figures]
    positions=[[i for i,b in enumerate(blocks) for h in b['images'] if h == digest] for digest in wanted]
    issues=[];captions=[]
    if any(len(p) != 1 for p in positions) or len(set(wanted)) != len(wanted):
        issues.append('Each requested new figure must be drawn exactly once')
    located=[p[0] for p in positions if len(p)==1]
    if len(located)==len(wanted) and located != sorted(located):
        issues.append('New figures are not in manifest order')
    allowed=set();numbers=[]
    for index in located:
        block=blocks[index];allowed.add(index)
        if not block['paragraph'] or block['text'] or len(block['images']) != 1:
            issues.append(f'Figure block {index} contains text or multiple images')
        following=next((j for j in range(index+1,len(blocks)) if blocks[j]['text'] or blocks[j]['has_drawing']),None)
        caption=blocks[following] if following is not None else None
        match=re.match(r'^图\s*([0-9]+)(?![0-9])', caption['text']) if caption else None
        if not caption or caption['has_drawing'] or not caption['paragraph'] or not match:
            issues.append(f'Figure block {index} needs its caption immediately below')
        else:
            allowed.add(following);captions.append(caption['text']);numbers.append(int(match[1]))
    if numbers != sorted(set(numbers)):
        issues.append('New figure caption numbers must increase without duplicates')
    if located:
        for i in range(min(located),len(blocks)):
            if i not in allowed and (blocks[i]['text'] or blocks[i]['has_drawing']):
                issues.append(f'Body content follows a new figure at block {i}')
    body_text='\n'.join(b['text'] for b in blocks[:min(located)]) if located else ''
    missing_references=[n for n in numbers if not re.search(r'(?:请参考|参阅|参见|参考)\s*图\s*'+str(n)+r'(?!\d)',body_text)]
    return {'ok':not issues,'positions':positions,'captions':captions,'issues':issues,
            'missing_body_references':missing_references,
            'body_references_complete':len(numbers)==len(wanted) and not missing_references}

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
    placement=figure_placement(b['blocks'],figures_result)
    return {'original_sha256':sha(original.read_bytes()),'revised_sha256':sha(revised.read_bytes()),
            'original_paragraphs':len(a['paragraphs']),'revised_paragraphs':len(b['paragraphs']),
            'missing_original_paragraphs':missing,'original_omml':len(a['math']),'revised_omml':len(b['math']),
            'changed_or_missing_original_formula_count':len(missing_math),'missing_original_media':missing_media,
            'figures':figures_result,'structural_preservation_ok':not missing and not missing_math and not missing_media,
            'all_requested_figures_embedded':all(x['embedded'] for x in figures_result),
            'all_requested_figures_at_document_end':placement['ok'],'figure_placement':placement,
            'all_requested_figures_referenced_in_body':placement['body_references_complete'],
            'rendered_visual_status':'not_checked','note':'Checks new picture placement and caption order structurally, not caption meaning, red color, prose context or page layout; inspect final rendered pages.'}

def main():
    p=argparse.ArgumentParser();p.add_argument('original',type=Path);p.add_argument('revised',type=Path);p.add_argument('--figure',action='append',default=[],type=Path);p.add_argument('--output',type=Path);a=p.parse_args()
    r=verify(a.original,a.revised,a.figure);text=json.dumps(r,ensure_ascii=False,indent=2)
    if a.output:a.output.parent.mkdir(parents=True,exist_ok=True);a.output.write_text(text,encoding='utf-8')
    print(text)
    if not all(r[key] for key in ('structural_preservation_ok','all_requested_figures_embedded','all_requested_figures_at_document_end','all_requested_figures_referenced_in_body')):raise SystemExit(2)
if __name__=='__main__':main()
