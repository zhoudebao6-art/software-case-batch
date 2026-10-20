"""Parent-built short evidence IDs; checks coverage, never invents viewed IDs."""
import argparse
import json
from pathlib import Path
from common import digest,inside,no_links,product_location,read_json,write_json

def create(workspace,manifest,destination):
    workspace=no_links(workspace);spec=read_json(manifest);files=spec.get('files',[])
    if not files or len(set(files))!=len(files):raise ValueError('Unique actual evidence list required')
    records=[{'id':'E'+str(i+1).zfill(3),'path':rel,'sha256':digest(inside(workspace,rel))} for i,rel in enumerate(files)]
    value={'schema_version':1,'review_id':__import__('uuid').uuid4().hex[:12],'workspace':str(workspace),'evidence':records}
    write_json(destination,value);return value

def check(index,ids,workspace=None):
    spec=read_json(index);evidence=spec['evidence'];expected={r['id'] for r in evidence}
    if len(expected)!=len(evidence) or len(ids)!=len(set(ids)):raise ValueError('Duplicate requested or reviewed ID')
    if workspace:
        root=no_links(workspace)
        if str(root)!=spec['workspace']:raise ValueError('Evidence index workspace differs')
        for record in evidence:
            if digest(inside(root,record['path']))!=record['sha256']:raise ValueError('Review snapshot changed: '+record['id'])
    actual=set(ids);return {'complete':actual==expected,'missing':sorted(expected-actual),'unknown':sorted(actual-expected),
        'note':'IDs must come from actual review or legal unchanged prior review. This command never signs or adds IDs.'}

def index_summary(index, spec=None):
    """Short directory for model input; all evidence remains in the full index."""
    index=no_links(index);spec=read_json(index) if spec is None else spec
    kinds={}
    for row in spec['evidence']:
        extension=Path(row['path']).suffix.lower() or '(no extension)'
        kinds[extension]=kinds.get(extension,0)+1
    return {'kind':'neutral-evidence-directory','path':str(index),'sha256':digest(index),
            'evidence_items':len(spec['evidence']),'by_extension':dict(sorted(kinds.items())),
            'coverage_claim':False,
            'instruction':'Read the referenced complete index in bounded chunks as needed. Every required item still needs actual review or separately authenticated legal prior review. Counts and unchanged hashes never establish viewed coverage; first Word/video review remains complete.'}


def review_input(workspace,index,destination,compact=False):
    """Current neutral bindings; no decision, viewed IDs or reviewer signature."""
    workspace=no_links(workspace)
    check(index,[],workspace)  # Rehash every declared evidence item.
    spec=read_json(index)
    from common import file_map
    run=read_json(inside(workspace,'.product-v2/run.json'))
    if run.get('workspace') and run['workspace']!=str(workspace):raise ValueError('Review run workspace identity differs')
    output=product_location(workspace,run)
    if not output.is_dir():raise ValueError('Current product output is missing; do not produce empty review facts')
    artifacts=file_map(output)
    if not artifacts:raise ValueError('Current product output is empty; do not request independent product review')
    from contracts import chart_policy,chart_records
    policy=chart_policy(run)
    manifest=inside(workspace,'.product-v2/chart-manifest.json');charts=read_json(manifest)
    figures=chart_records(charts,run) if policy is not None else charts['figures']
    for figure in figures:
        if digest(inside(workspace,figure['png']))!=figure['sha256']:raise ValueError('Chart input changed')
    facts={'schema_version':1,'kind':'review-input-facts','workspace':str(workspace),
           'run_id':run['run_id'],'index':{'path':str(no_links(index)),'sha256':digest(index)},
           'current_artifacts':artifacts,
           'current_charts':{'manifest_sha256':digest(manifest),'figures':{str(f['figure_id']):f['sha256'] for f in charts['figures']}},
           'instruction':'Reviewer must inspect the required evidence and write independent conclusions, actual reviewed IDs and final proof hash. These bindings are not a review.'}
    from review_packet import current_admitted_metadata
    facts.update(current_admitted_metadata(workspace))
    if compact:facts['evidence_directory']=index_summary(index,spec)
    else:facts['evidence']=spec['evidence']
    facts['review_sequence']={'first':'Use the actual source mappings and algorithm/API/persistence evidence to check applicable acceptance/rejection boundaries and final-engine derived results in references/system-data.md before expensive visual coverage.',
        'on_blocking_defect':'Collect all reproducible material defects in this review. Continue independent checks and the complete first visual reading of stable Word/video even if code needs repair. Stop only checks made impossible or invalid by that actual dependency; disclose exactly what remains unread and why. Never invent coverage or add a whole-case review for minor fixes.',
        'for_pass':'Complete the full required source, document, chart, UI and video review; no visual scope or independent role is reduced. A video already actually reviewed and accepted may inherit its original viewed conclusion while its final media and technical evidence remain unchanged; later minor code, data or copy edits do not require another video review. A video never actually accepted still requires the complete first review.'}
    if policy is not None:
        facts['current_charts']['chart_policy']=policy
        facts['chart_review_requirements']={'every_current_png':True,
            'quality_evidence':['meaning','data','legibility','layout','explanation'],
            'visual_evidence':['no_title_header_evidence','no_schematic_evidence'],
            'instruction':'Open every current PNG and Word context; verify no 示意 and no title/header. Explain source-relative value in meaning and before/red explanation/after context in explanation. Declared captions/labels are not pixel OCR.'}
    if run.get('explanation_context_policy'):
        from contracts import chart_snapshot
        snapshot=chart_snapshot(workspace,output/run['word_name'],run)
        facts['current_charts'].update({
            key:snapshot[key] for key in ('explanation_context_policy','explanation_contexts')})
        facts['chart_review_requirements']['context_instruction']=(
            'These anchors only prove structural placement. Read the actual original example, '
            'preceding prose, inserted explanation and following prose. Confirm the same object, '
            'conditions, formula and results in each explanation judgment. Explanations collected '
            'in an unrelated tail section are a material document defect, not a cosmetic suggestion.')
    controlled=workspace/'.product-v2/controlled-video.json'
    if controlled.exists():
        media=read_json(controlled);timeline=no_links(media['timeline'])
        if workspace not in timeline.parents or digest(timeline)!=media['sha256']:raise ValueError('Current controlled timeline changed')
        facts['current_video_timeline']={'path':str(timeline),'sha256':digest(timeline)}
    # Direct navigation only: do not duplicate hundreds of uniform frames or
    # mark a single evidence ID read. The complete index remains authoritative.
    indexed={str(inside(workspace,row['path'])):row for row in spec['evidence']}
    def reference(path,sha,**extra):
        path=no_links(path) if Path(path).is_absolute() else inside(workspace,path)
        if workspace not in path.parents:raise ValueError('Visual navigation must stay in this workspace')
        row=indexed.get(str(path))
        if (row['sha256'] if row else digest(path))!=sha:raise ValueError('Visual navigation input changed: '+str(path))
        result={'path':str(path),'sha256':sha,**extra}
        if row:result['evidence_id']=row['id']
        return result
    navigation={'coverage_claim':False,
        'instruction':'Open these actual files; a link or hash is not a viewed item. Read every Word page from the full index, all video contact sheets and required full-resolution endpoint/interaction frames; inspect other full-resolution frames where needed. Keep all original evidence and report actual reviewed IDs only.',
        'charts':[reference(f['png'],f['sha256'],figure_id=f['figure_id']) for f in figures]}
    if controlled.exists():
        report=read_json(timeline)
        navigation['video']={group:[reference(item['file'],item['sha256']) for item in report.get(group,[])]
                             for group in ('contact_sheets','interaction_frames')}
        navigation['video']['endpoints']=[reference(item['file'],item['sha256'],type=item['type'])
                                         for item in report.get('frames',[]) if item.get('type') in {'first','last'}]
    facts['visual_navigation']=navigation
    destination=no_links(destination)
    if workspace not in destination.parents or destination.exists():raise ValueError('Use a new internal facts path; do not overwrite any review')
    write_json(destination,facts);return {'facts':str(destination),'sha256':digest(destination),'evidence_items':len(spec['evidence'])}

if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('action',choices=['create','check','review-input']);p.add_argument('--workspace');p.add_argument('--manifest');p.add_argument('--index',required=True);p.add_argument('--output');p.add_argument('--compact',action='store_true');p.add_argument('--ids',nargs='*',default=[]);a=p.parse_args()
    try:
        result=create(a.workspace,a.manifest,a.index) if a.action=='create' else (review_input(a.workspace,a.index,a.output,a.compact) if a.action=='review-input' else check(a.index,a.ids,a.workspace))
        print(json.dumps(result,ensure_ascii=False,indent=2));raise SystemExit(0 if result.get('complete',True) else 2)
    except (OSError,ValueError,KeyError) as e:print('ERROR: '+str(e));raise SystemExit(2)
