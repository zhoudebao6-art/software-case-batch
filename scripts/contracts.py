"""Read-only artifact and recorded dispatch checks; never create model evidence."""
import hashlib
import json
from pathlib import Path
import re
import xml.etree.ElementTree as ET
import zipfile
from common import digest, inside, no_links, read_json
from source_intake import source_figure_numbers

SESSION_ROOT = Path.home()/'.codex/sessions'
NS = {'w':'http://schemas.openxmlformats.org/wordprocessingml/2006/main',
      'a':'http://schemas.openxmlformats.org/drawingml/2006/main',
      'wp':'http://schemas.openxmlformats.org/drawingml/2006/wordprocessingDrawing',
      'r':'http://schemas.openxmlformats.org/officeDocument/2006/relationships'}

ANALYTICAL_CHART_POLICY = 'analytical-v1'
BUILD_CHART_POLICY = 'analytical-v2'
ANALYTICAL_POLICIES = {ANALYTICAL_CHART_POLICY, BUILD_CHART_POLICY}
CONSTRUCTION_POLICY = 'dependency-bound-v1'
CONSTRUCTION_KINDS = {'algorithm','api','persistence','browser','build'}

def construction_checks(workspace, run, plan_path=None):
    """Read actual self-check bindings; never run commands or approve business logic.

    Individual dependency maps permit unchanged checks to retain their actual
    logs. Their union must cover the declared software and recording inputs;
    an independent reviewer still checks whether those scopes are truthful.
    """
    policy=run.get('construction_check_policy_version')
    if 'construction_check_policy_version' not in run:
        return {'required':False,'status':'historical-contract'}
    if policy!=CONSTRUCTION_POLICY:raise ValueError('Unknown construction check policy')
    workspace=no_links(workspace)
    spec_path=inside(workspace,'.product-v2/build-checks.json');spec=read_json(spec_path)
    if spec.get('run_id')!=run.get('run_id') or spec.get('source_docx_sha256')!=run.get('source_docx_sha256'):
        raise ValueError('Construction checks belong to a different run or source')
    if digest(no_links(run['source_docx']))!=run['source_docx_sha256']:
        raise ValueError('Construction original Word source changed')
    manifest_path=inside(workspace,'.product-v2/source-manifest.json');manifest=read_json(manifest_path)
    files=manifest.get('files',[])
    if not isinstance(files,list) or not files or not all(isinstance(p,str) for p in files):
        raise ValueError('Construction requires the explicit source file manifest')
    from proflow import excluded_source
    declared={}
    names=set()
    for relative in files:
        relative=relative.replace('\\','/')
        path=inside(workspace,relative)
        if relative.casefold() in names:raise ValueError('Duplicate construction source member')
        names.add(relative.casefold())
        if not excluded_source(relative,manifest.get('exclude',[])):
            declared[relative]=digest(path)
    if not declared or spec.get('implementation_hashes')!=declared:
        raise ValueError('Construction implementation snapshot is incomplete or stale')
    if 'hashes' in manifest and any(manifest['hashes'].get(p)!=sha for p,sha in declared.items()):
        raise ValueError('Construction source manifest hash changed')
    plan_path=no_links(plan_path or workspace/'.product-v2/record-plan.json')
    if workspace not in plan_path.parents or not plan_path.is_file():
        raise ValueError('Construction recording plan must be an actual file inside its workspace')
    plan=read_json(plan_path);recording_inputs=plan.get('input_files',[])
    if (not isinstance(recording_inputs,list) or not recording_inputs or
            not all(isinstance(p,str) for p in recording_inputs)):
        raise ValueError('Nonempty construction recording inputs required')
    required=dict(declared)
    for relative in recording_inputs:required[relative.replace('\\','/')]=digest(inside(workspace,relative))
    checks=spec.get('checks',{})
    if not isinstance(checks,dict) or not CONSTRUCTION_KINDS.issubset(checks):
        raise ValueError('Five actual construction execution checks required')
    covered=set();bindings={}
    for kind in sorted(CONSTRUCTION_KINDS):
        check=checks[kind]
        if not isinstance(check,dict):raise ValueError('Invalid construction check: '+kind)
        log=inside(workspace,check.get('log',''))
        if (type(check.get('exit_code')) is not int or check['exit_code']!=0 or
                not _nonempty_text(check.get('command')) or log.stat().st_size==0 or check.get('sha256')!=digest(log)):
            raise ValueError('Missing/failed/stale construction execution log: '+kind)
        inputs=check.get('input_files')
        test_files=check.get('test_files')
        if not isinstance(inputs,dict) or not inputs:
            raise ValueError('Nonempty actual construction dependencies required: '+kind)
        if (not isinstance(test_files,list) or not test_files or
                not all(isinstance(p,str) and p in inputs for p in test_files) or len(set(test_files))!=len(test_files)):
            raise ValueError('Bind actual construction test scripts and fixed fixtures: '+kind)
        canonical=set()
        for relative,sha in inputs.items():
            if not isinstance(relative,str) or not isinstance(sha,str) or not re.fullmatch('[0-9a-f]{64}',sha):
                raise ValueError('Invalid construction dependency hash: '+kind)
            key=relative.replace('\\','/')
            if key.casefold() in canonical:raise ValueError('Duplicate construction dependency: '+kind)
            canonical.add(key.casefold())
            if digest(inside(workspace,relative))!=sha:raise ValueError('Construction dependency changed: '+kind+' / '+relative)
            covered.add(key)
        bindings[kind]={'log':check['log'],'sha256':check['sha256'],'input_files':inputs,'test_files':test_files}
    if not set(required).issubset(covered):
        raise ValueError('Construction checks omit current source/recording dependencies: '+', '.join(sorted(set(required)-covered)))
    return {'required':True,'status':'ready','policy':policy,'run_id':run['run_id'],
            'source_docx_sha256':run['source_docx_sha256'],'build_checks_sha256':digest(spec_path),
            'source_manifest_sha256':digest(manifest_path),'plan_sha256':digest(plan_path),
            'implementation_hashes':declared,'checks':bindings,
            'limitation':'Commands were not rerun; current logs and dependency hashes are bound, not independently approved.'}

def chart_policy(run):
    """An absent policy keeps the historical gate; unknown policies fail closed."""
    policy=run.get('chart_policy')
    if 'chart_policy' in run and policy not in ANALYTICAL_POLICIES:
        raise ValueError('Unknown chart policy; do not silently relax the frozen contract')
    return policy

def _nonempty_text(value):
    return isinstance(value,str) and bool(value.strip())

def check_word_chart_width(block, relations, media, sha, intended_mm):
    """Require the actual inserted drawing to retain the visually checked width."""
    widths=[]
    for drawing in block.findall('.//w:drawing',NS):
        matching=False
        for blip in drawing.findall('.//a:blip',NS):
            target=relations.get(blip.get('{'+NS['r']+'}embed'),'')
            member='word/'+target if not target.startswith('/') else target.lstrip('/')
            matching |= media.get(member)==sha
        if matching:
            extents=drawing.findall('.//wp:extent',NS)
            if len(extents)!=1:raise ValueError('One actual Word drawing extent required for the checked PNG')
            try:widths.append(int(extents[0].get('cx',''))/36000)
            except ValueError:raise ValueError('Invalid Word drawing width')
    if not widths or any(abs(width-intended_mm)>0.05 for width in widths):
        raise ValueError('Actual Word insertion width changed after construction visual self-check')

def chart_records(spec, run):
    """Check declared chart facts, without claiming to recognize PNG text."""
    policy=chart_policy(run)
    figures=spec.get('figures',[])
    if not isinstance(figures,list) or not figures:
        raise ValueError('At least one distinct final chart record required')
    if policy is None and not 2<=len(figures)<=6:
        raise ValueError('Two to six distinct final chart records required by the historical policy')
    ids=set()
    for figure in figures:
        if not isinstance(figure,dict):raise ValueError('Chart records must be objects')
        number=figure.get('figure_id')
        if not isinstance(number,int) or isinstance(number,bool) or number<1 or number in ids:
            raise ValueError('Distinct positive figure_id required')
        ids.add(number)
        if policy in ANALYTICAL_POLICIES:
            for key in ('question','data_source','chart_type'):
                if not _nonempty_text(figure.get(key)):
                    raise ValueError('Analytical chart requires a concrete '+key)
            labels=figure.get('labels')
            if not isinstance(labels,list) or not labels or not all(_nonempty_text(label) for label in labels):
                raise ValueError('Analytical chart requires actual explicit labels')
            caption=figure.get('caption')
            if not _nonempty_text(caption) or any('示意' in text for text in [caption]+labels):
                raise ValueError('New analytical chart captions and labels must not contain 示意')
        if policy==BUILD_CHART_POLICY:
            if figure.get('analysis_role') not in {'baseline_result','professional_analysis'}:
                raise ValueError('Declare each independent chart analysis_role during construction')
            if figure.get('palette') not in {'monochrome','color'}:
                raise ValueError('Declare chart palette, independently of its analytical role')
            check=figure.get('build_selfcheck',{})
            visual=check.get('visual_review',{})
            if (check.get('geometry_status') not in {'pass','review_required'} or check.get('collisions')
                    or check.get('png_sha256')!=figure.get('sha256')
                    or visual.get('png_sha256')!=figure.get('sha256') or visual.get('inspected') is not True
                    or not _nonempty_text(visual.get('evidence'))):
                raise ValueError('Current PNG must pass construction collision checks and actual visual self-check before Word submission')
            width=check.get('final_width_mm')
            if isinstance(width,bool) or not isinstance(width,(int,float)) or not 0<width<=500 or visual.get('final_width_mm')!=width:
                raise ValueError('Construction self-check must bind actual intended Word insertion width')
    if policy==BUILD_CHART_POLICY:
        retained=spec.get('retained_results',[])
        if not isinstance(retained,list) or len(retained)>2:
            raise ValueError('At most two explicitly verified existing monochrome result figures can count toward coverage')
        for old in retained:
            if (not isinstance(old,dict) or old.get('analysis_role')!='baseline_result' or old.get('palette')!='monochrome'
                    or old.get('figure_id') in ids or not isinstance(old.get('figure_id'),int) or isinstance(old.get('figure_id'),bool)
                    or old['figure_id']<1 or not _nonempty_text(old.get('result_reason'))):
                raise ValueError('Retained results must identify actual original statistical results; original workflows do not count')
            ids.add(old['figure_id'])
            viewed=old.get('visual_review',{})
            if viewed.get('inspected') is not True or viewed.get('png_sha256')!=old.get('sha256') or not _nonempty_text(viewed.get('evidence')):
                raise ValueError('Actually inspect any original statistical result counted toward the figure mix')
        baseline=[f for f in figures+retained if f.get('analysis_role')=='baseline_result']
        professional=[f for f in figures if f.get('analysis_role')=='professional_analysis']
        if len(figures)+len(retained)<4 or not 1<=len(baseline)<=2 or len(professional)*2<=len(figures)+len(retained):
            raise ValueError('Four or more effective charts, one or two monochrome result charts and a professional-analysis majority required')
        if any(f.get('palette')!='monochrome' for f in baseline):
            raise ValueError('Baseline result charts must actually use a monochrome palette, checked visually independently')
    return figures

def delivery_layout(output, run):
    """Exact user-facing names, including empty unexpected directories."""
    if run.get('schema_version') != 2 or not run.get('word_name'):
        raise ValueError('Legacy run is frozen; create a new version with explicit source-docx')
    expected = {run['word_name'], '模拟系统'}
    if {p.name for p in output.iterdir()} != expected:
        raise ValueError('Delivery root must contain exactly the original Word filename and 模拟系统')
    word = inside(output, run['word_name'])
    system = no_links(output/'模拟系统')
    if not system.is_dir() or {p.name for p in system.iterdir()} != {'项目源码.zip','演示视频.mp4','数据'}:
        raise ValueError('模拟系统 must contain exactly 项目源码.zip, 演示视频.mp4 and 数据')
    for name in ('项目源码.zip','演示视频.mp4'):
        if inside(system,name).stat().st_size == 0:
            raise ValueError('Empty deliverable: '+name)
    data=no_links(system/'数据')
    if not data.is_dir() or not list(data.iterdir()) or any(not p.is_file() or p.suffix.lower()!='.csv' for p in data.iterdir()):
        raise ValueError('数据 must contain nonempty selected CSV files only')
    return word

def chart_snapshot(workspace, word, run):
    """Bind internal PNG bytes to actual Word drawings and captions.

    No pixel classifier is claimed. The independent review must check absence of
    title/header in the actual PNG and Word, tied to these hashes.
    """
    source=no_links(run['source_docx'])
    if digest(source)!=run['source_docx_sha256'] or source.name!=run['word_name']:
        raise ValueError('Frozen source Word identity changed')
    manifest=inside(workspace,'.product-v2/chart-manifest.json')
    spec=read_json(manifest)
    figures=chart_records(spec,run)
    rejected_path=Path(__file__).resolve().parents[1]/'references/original/rules/rejected-chart-versions.json'
    rejected={r['sha256'] for r in read_json(rejected_path).get('versions',[])} if rejected_path.exists() else set()
    if run.get('chart_numbering_policy') == 'source-sequential-v1':
        start = max(source_figure_numbers(source), default=0) + 1
        if [f.get('figure_id') for f in figures] != list(range(start, start+len(figures))):
            raise ValueError('New result figure numbers must continue sequentially after all source figure numbers')
    with zipfile.ZipFile(word) as z:
        doc=ET.fromstring(z.read('word/document.xml'))
        rels=ET.fromstring(z.read('word/_rels/document.xml.rels'))
        relations={r.attrib['Id']:r.attrib['Target'] for r in rels}
        body=doc.find('w:body',NS)
        blocks=list(body)
        # w:t only avoids counting field and styling values as captions.
        paragraphs=[''.join(t.text or '' for t in b.findall('.//w:t',NS)) for b in blocks]
        media={name:hashlib.sha256(z.read(name)).hexdigest() for name in z.namelist() if name.startswith('word/media/')}
        ids,pngs,positions=set(),set(),[]
        for f in figures:
            number=f.get('figure_id')
            if not isinstance(number,int) or isinstance(number,bool) or number<1 or number in ids:
                raise ValueError('Distinct positive figure_id required')
            ids.add(number)
            png=inside(workspace,f['png'])
            sha=digest(png)
            if sha in rejected:raise ValueError('User-rejected chart PNG version cannot be resubmitted unchanged')
            if png.suffix.lower()!='.png' or not png.read_bytes().startswith(b'\x89PNG\r\n\x1a\n') or sha!=f.get('sha256') or sha in pngs:
                raise ValueError('Distinct current PNG snapshots required')
            pngs.add(sha)
            if f.get('title_policy')!='none':
                raise ValueError('PNG title/header policy must be none')
            caption=f.get('caption','')
            if not caption.startswith('图'+str(number)) or len(caption)<=len('图'+str(number)):
                raise ValueError('Exact descriptive Word caption required')
            matches=[i for i,text in enumerate(paragraphs) if text==caption]
            if len(matches)!=1 or matches[0]==0:
                raise ValueError('Chart caption must occur once below its image in Word')
            at=matches[0]
            embeds=blocks[at-1].findall('.//a:blip',NS)
            matching=False
            for b in embeds:
                target=relations.get(b.get('{'+NS['r']+'}embed'),'')
                member='word/'+target if not target.startswith('/') else target.lstrip('/')
                if media.get(member)==sha: matching=True
            if not matching:
                raise ValueError('Word embedded chart bytes differ or caption is not immediately below image')
            if run.get('chart_policy')==BUILD_CHART_POLICY:
                check_word_chart_width(blocks[at-1],relations,media,sha,f['build_selfcheck']['final_width_mm'])
            positions.append(at)
            if not any('请参考图'+str(number) in text for text in paragraphs[:at-1]):
                raise ValueError('Each chart requires an independent body reference before the appended image')
        if positions!=sorted(positions) or [f['figure_id'] for f in figures]!=sorted(ids):
            raise ValueError('Appended chart captions must follow figure-number order')
        # An original drawing cannot be relabeled as a new result figure.
        with zipfile.ZipFile(source) as original:
            for retained in spec.get('retained_results',[]) if run.get('chart_policy')==BUILD_CHART_POLICY else []:
                member=retained.get('source_member','')
                if (not member.startswith('word/media/') or member not in original.namelist()
                        or hashlib.sha256(original.read(member)).hexdigest()!=retained.get('sha256')
                        or retained.get('figure_id') not in source_figure_numbers(source)):
                    raise ValueError('Retained statistical figure must bind original media bytes and original figure number')
            for member in original.namelist():
                if member.startswith('word/') and member not in {'word/document.xml','word/_rels/document.xml.rels'}:
                    if member not in z.namelist() or original.read(member)!=z.read(member):
                        raise ValueError('Original Word non-body parts, media, headers/footers or embedded objects must remain unchanged: '+member)
            old_media={hashlib.sha256(original.read(n)).hexdigest() for n in original.namelist() if n.startswith('word/media/')}
            if pngs & old_media:
                raise ValueError('New result charts cannot reuse original embedded images')
            if not old_media.issubset(set(media.values())):
                raise ValueError('Original Word images must remain unchanged')
            source_body=ET.fromstring(original.read('word/document.xml')).find('w:body',NS)
            if source_body.findall('.//a:blip',NS):
                original_rels=ET.fromstring(original.read('word/_rels/document.xml.rels'))
                original_targets={r.attrib['Id']:r.attrib['Target'] for r in original_rels}
                for blip in source_body.findall('.//a:blip',NS):
                    rid=blip.get('{'+NS['r']+'}embed')
                    target=original_targets.get(rid,'')
                    member='word/'+target if not target.startswith('/') else target.lstrip('/')
                    if relations.get(rid)!=target or media.get(member)!=hashlib.sha256(original.read(member)).hexdigest():
                        raise ValueError('Original Word drawing relationships and image bytes must remain unchanged')
            originals=[ET.tostring(b) for b in source_body if not b.tag.endswith('}sectPr')]
            current=[ET.tostring(b) for b in blocks]
            cursor=0
            for original_block in originals:
                try: at=current.index(original_block,cursor)
                except ValueError: raise ValueError('Original Word body blocks must remain unchanged and in order')
                cursor=at+1
            if positions and cursor>min(positions)-1:
                raise ValueError('All added images and captions must follow all original body content')
    snapshot={'manifest_sha256':digest(manifest),'figures':{str(f['figure_id']):f['sha256'] for f in figures}}
    if chart_policy(run) is not None:snapshot['chart_policy']=run['chart_policy']
    if run.get('chart_policy')==BUILD_CHART_POLICY and spec.get('retained_results'):
        snapshot['retained_results']={str(f['figure_id']):f['sha256'] for f in spec['retained_results']}
    return snapshot

def _dispatch_events(path, call_id):
    path=no_links(path)
    root=no_links(SESSION_ROOT)
    if root not in path.parents or path.suffix.lower()!='.jsonl':
        raise ValueError('Dispatch must be verified against actual Codex session JSONL, not a hand-written workspace transcript')
    calls,outputs=[],[]
    sessions=[]
    with path.open(encoding='utf-8') as stream:
        for line in stream:
            try: event=json.loads(line)
            except json.JSONDecodeError: continue  # active final partial line is not evidence
            if event.get('type')=='session_meta': sessions.append(event.get('payload',{}).get('id'))
            if event.get('type')!='response_item': continue
            payload=event.get('payload',{})
            if payload.get('call_id')!=call_id: continue
            if payload.get('type')=='function_call': calls.append(event)
            if payload.get('type')=='function_call_output': outputs.append(event)
    if len(calls)!=1 or len(outputs)!=1:
        raise ValueError('One actual dispatch call and matching successful output required')
    if len(sessions)!=1 or not isinstance(sessions[0],str) or not sessions[0]:
        raise ValueError('One actual parent session identity required')
    return calls[0],outputs[0],sessions[0]

def _dispatch_timestamp_ns(value):
    """Use recorded UTC chronology, never an unauthenticated cipher timestamp."""
    from datetime import datetime,timezone
    try:
        moment=datetime.fromisoformat(value.replace('Z','+00:00'))
        if moment.tzinfo is None:raise ValueError('Timezone missing')
        delta=moment.astimezone(timezone.utc)-datetime(1970,1,1,tzinfo=timezone.utc)
    except (AttributeError,TypeError,ValueError):
        raise ValueError('Encrypted review requires actual timezone-aware dispatch/session/final timestamps')
    return ((delta.days*86400+delta.seconds)*1000000+delta.microseconds)*1000

def _encrypted_dispatch_message(message):
    """Recognize the recorded desktop envelope without decrypting or authenticating it."""
    if not isinstance(message,str) or not message.startswith('gAAAA'):return False
    import base64
    import binascii
    try:
        if not re.fullmatch(r'gAAAA[A-Za-z0-9_-]+={0,2}',message):raise ValueError('Envelope shape')
        envelope=base64.b64decode(message,altchars=b'-_',validate=True)
        if len(envelope)<73 or envelope[0]!=128 or (len(envelope)-57)%16:raise ValueError('Envelope shape')
    except (binascii.Error,ValueError):
        raise ValueError('Unsupported encrypted dispatch message envelope; do not bypass plaintext scope checks')
    return True

def _encrypted_review_binding(admission,permit,call,result,parent_id):
    arguments=json.loads(call['payload']['arguments']);message=arguments.get('message')
    if not _encrypted_dispatch_message(message):
        raise ValueError('Desktop encrypted dispatch binding requires the actual supported cipher envelope')
    acquired_ns=admission.get('acquired_ns');issued_ns=permit.get('issued_ns')
    called_ns=_dispatch_timestamp_ns(call.get('timestamp'));returned_ns=_dispatch_timestamp_ns(result.get('timestamp'))
    if (type(acquired_ns) is not int or type(issued_ns) is not int or
            not 0<acquired_ns<=issued_ns<=called_ns<=returned_ns):
        raise ValueError('Immutable admission and verified permit must precede the actual encrypted review dispatch')
    return {'contract':'desktop-encrypted-spawn-v1','token':admission['token'],
        'dispatch_nonce':permit['dispatch_nonce'],'run_id':admission['run_id'],
        'workspace':admission['workspace'],'parent_session_id':parent_id,'call_id':call['payload']['call_id'],
        'dispatch_message_sha256':hashlib.sha256(message.encode('utf-8')).hexdigest(),
        'dispatch_event_sha256':hashlib.sha256(json.dumps([call,result],sort_keys=True,ensure_ascii=False).encode()).hexdigest()}

def review_dispatch_binding(workspace,admission_reference,permit_reference,session_log,call_id):
    """Read a frozen permit and real call/result; return binding data, never a signature."""
    from batch_control import load_review_admission,load_review_dispatch_permit
    admission=load_review_admission(workspace,admission_reference)
    permit=load_review_dispatch_permit(workspace,admission_reference,permit_reference)
    call,result,parent_id=_dispatch_events(session_log,call_id)
    arguments=json.loads(call['payload']['arguments'])
    if (call['payload'].get('name','').split('.')[-1]!='spawn_agent' or arguments.get('fork_turns')!='none'
            or arguments.get('model')!=admission['model'] or arguments.get('reasoning_effort')!=admission['effort']):
        raise ValueError('Binding needs the actual admitted model/effort spawn_agent call with fork_turns=none')
    output=result['payload'].get('output')
    if isinstance(output,str):output=json.loads(output)
    if not isinstance(output,dict) or not output.get('task_name') or any(output.get(k) for k in ('error','isError','is_error')):
        raise ValueError('Binding needs the actual matching successful dispatch result')
    return _encrypted_review_binding(admission,permit,call,result,parent_id)

def _scope_mentioned(text,name):
    prefix=r'(?:^|[\s,，;；:：()（）\[\]【】]|请|帮|给|把|将|对|让|当前|本次|现在|加急)'
    suffix=r'(?=$|[\s,，.。;；:：()（）\[\]【】]|加急|使用|启用|采用|按|请|要|需要|要求|这批|本批|该批|此批)'
    return bool(name and re.search(prefix+re.escape(name)+suffix,text))

def _direct_user_lines(text):
    fenced=False;material=False;result=[]
    for raw in text.splitlines():
        line=raw.strip()
        if line.startswith(('```','~~~')):fenced=not fenced;continue
        if not line:material=False;continue
        if re.match(r'^(?:材料|原文|引用|示例|例如).{0,12}[:：]\s*$',line):material=True;continue
        if not fenced and not material and not line.startswith('>'):result.append(line)
    return result

def _simple_expedite_command(statement,scope_name):
    """Accept a whole simple command, never a clause cut from other prose."""
    name=re.escape(scope_name)
    courtesy=r'(?:请|帮我|请帮我)?\s*'
    modifiers=r'(?:(?:请|要|需要|都|全部|直接|马上)\s*)*'
    action=r'(?:加急(?:一下|处理|办理|审核|验收)?|(?:启用|使用|采用|按)\s*(?:原加急模式|(?:gpt-6-)?Astra\s*(?:低思考|低|low)))'
    named=courtesy+name+r'\s*(?:(?:这批|本批|该批|此批)(?:案件)?\s*)?'+modifiers+action
    leading=courtesy+r'加急\s*'+name
    return bool(scope_name and re.fullmatch(r'(?:'+named+'|'+leading+r')[。.!！]?',statement,re.I))

def _exact_current_batch(text):
    lines=_direct_user_lines(text)
    if len(lines)!=1 or text.strip()!=lines[0]:return None
    match=re.fullmatch(r'(?:当前批次|本次批次|现在处理批次)\s*[:：=]?\s*([^\s:：=。.]+)\s*[。.]?',lines[0])
    value=match.group(1) if match else ''
    return value if value and all(c.isalnum() or c in '-_' for c in value) else None

def _question_reply_command(actual,statement,scope_name,requests):
    """Use one exact answer from a real question card, never its prompt."""
    if statement.strip()!=statement or len(statement.splitlines())!=1 or _direct_user_lines(statement)!=[statement]:return False
    tag='send_user_message_question_reply'
    match=re.fullmatch(r'\s*<'+tag+r'>\s*(.*?)\s*</'+tag+r'>\s*',actual,re.S)
    if not match or actual.count('<'+tag+'>')!=1 or actual.count('</'+tag+'>')!=1:return False
    def unique_object(pairs):
        result={}
        for key,value in pairs:
            if key in result:raise ValueError('Duplicate question reply key')
            result[key]=value
        return result
    try:
        replies=json.loads(match.group(1),object_pairs_hook=unique_object)
        if not isinstance(replies,list) or not replies:return False
        identities=set();answers=[]
        for reply in replies:
            if not isinstance(reply,dict) or set(reply)!={'questionItemId','question','answer'}:return False
            if not all(isinstance(value,str) for value in reply.values()):return False
            if any('<'+tag in value or '</'+tag in value for value in reply.values()):return False
            identity=json.loads(reply['questionItemId'])
            if (not isinstance(identity,list) or len(identity)!=3 or identity[0]!='request_user_input_async' or
                    not isinstance(identity[1],str) or type(identity[2]) is not int or identity[2]<0):return False
            key=(identity[1],identity[2])
            if key in identities:return False
            identities.add(key)
            request=requests.get(identity[1])
            if not request:return False
            arguments=json.loads(request['arguments'],object_pairs_hook=unique_object)
            if not isinstance(arguments,dict):return False
            questions=arguments.get('questions')
            if (not isinstance(questions,list) or identity[2]>=len(questions) or
                    not isinstance(questions[identity[2]],dict) or questions[identity[2]].get('title')!=reply['question']):return False
            answers.append(reply['answer'])
        # Multiple questions may have different scoped answers. A second answer
        # mentioning this scope is ambiguous, even when only one is an exact match.
        return answers.count(statement)==1 and all(answer==statement or scope_name not in answer for answer in answers)
    except (ValueError,TypeError,KeyError):return False

def expedited_authorization(workspace,record):
    """Explicit original expedited-mode request in a real scoped user message."""
    run=read_json(inside(workspace,'.product-v2/run.json'))
    if record.get('run_id')!=run['run_id'] or record.get('workspace')!=str(no_links(workspace)):
        raise ValueError('Expedited authorization must be restricted to this actual run/workspace')
    path=no_links(record['session_log'])
    if no_links(SESSION_ROOT) not in path.parents or path.suffix.lower()!='.jsonl':
        raise ValueError('Expedited authorization needs an actual parent user message, not a workspace assertion')
    statement=record.get('statement','');scope_name=record.get('scope_name','')
    implicit=bool(re.fullmatch(r'(?:这批|本批|该批|此批)(?:案件)?(?:请|要|需要|都|全部|直接|马上|\s)*加急(?:一下|处理|办理|审核|验收)?[。.!！]?',statement))
    if not implicit and not _simple_expedite_command(statement,scope_name):
        raise ValueError('Only a whole simple positive scoped expedited command selects Astra/low; conditional or material prose does not')
    if not scope_name:
        raise ValueError('Actual expedited request must name its current authorized batch or case')
    from batch_control import media_binding,batch,authorization_scope_names,REVIEW_ADMISSION_CONTRACT
    binding=media_binding(workspace);target_batch=None;qualified=False;ambiguous=False
    if binding:
        _,manifest=batch(binding['root'],binding['batch_id'])
        if manifest.get('review_admission_contract')==REVIEW_ADMISSION_CONTRACT:
            target_batch=binding['batch_id']
            qualified=scope_name in {target_batch,target_batch+'/'+binding['case_id']}
            if not qualified:
                for other_path in no_links(binding['root']).glob('*/manifest.json'):
                    other=read_json(no_links(other_path))
                    if other.get('batch_id')!=target_batch and any(
                        str(no_links(case['workspace'])).casefold()!=str(no_links(workspace)).casefold() and
                        scope_name in authorization_scope_names(other,case) for case in other.get('cases',[])):
                        ambiguous=True;break
    context=record.get('scope_context');found=False;last_batch_context=None;authorized_context=None
    question_requests={};parent_session=False
    if implicit and (not isinstance(context,dict) or context.get('batch_id')!=scope_name):
        raise ValueError('Implicit batch expedite needs the frozen real current-batch context')
    with path.open(encoding='utf-8') as stream:
        for line in stream:
            try:event=json.loads(line)
            except json.JSONDecodeError:continue
            payload=event.get('payload',{})
            if event.get('type')=='session_meta':
                source=payload.get('source')
                parent_session=bool(payload.get('id') and payload.get('thread_source') in (None,'user') and
                                    not (isinstance(source,dict) and 'subagent' in source))
                continue
            if event.get('type')!='response_item':continue
            if payload.get('type')=='function_call' and payload.get('name')=='request_user_input_async':
                call_id=payload.get('call_id')
                if isinstance(call_id,str):question_requests[call_id]=None if call_id in question_requests else payload
                continue
            if payload.get('type')!='message' or payload.get('role')!='user':continue
            actual='\n'.join(part.get('text','') for part in payload.get('content',[]));lines=_direct_user_lines(actual)
            if (hashlib.sha256(actual.encode()).hexdigest()==record.get('user_message_sha256') and
                ((len(lines)==1 and actual.strip()==statement and lines[0]==statement) or
                 (not implicit and parent_session and _question_reply_command(actual,statement,scope_name,question_requests)))):
                if not implicit:
                    # Bare case IDs/aliases inherit an explicit actual batch
                    # context. Reused names need that context or a batch-qualified
                    # command; changing run/workspace cannot change its meaning.
                    if target_batch and not qualified:
                        current=_exact_current_batch(last_batch_context['text']) if last_batch_context else None
                        if ((last_batch_context and current!=target_batch) or (ambiguous and current!=target_batch)):
                            raise ValueError('Ambiguous case authorization requires an explicit matching current-batch context or batch-qualified scope')
                    found=True;authorized_context=last_batch_context
                elif (last_batch_context and last_batch_context['hash']==context.get('user_message_sha256') and
                      last_batch_context['text'].strip()==context.get('statement','').strip() and
                      len(last_batch_context['lines'])==1 and last_batch_context['lines'][0]==context.get('statement') and
                      re.fullmatch(r'(?:当前批次|本次批次|现在处理批次)\s*[:：=]?\s*'+re.escape(scope_name)+r'\s*[。.]?',context['statement'])):
                    found=True
            if any(re.search(r'批次|当前批|这批|本批|该批|另.{0,8}批|切换.{0,8}批|下一批|\bbatch\b',line,re.I) for line in lines):
                last_batch_context={'hash':hashlib.sha256(actual.encode()).hexdigest(),'lines':lines,'text':actual}
    if not found:raise ValueError('Scoped positive expedited authorization not found in the real user message')
    result={'run_id':run['run_id'],'scope_name':scope_name,'user_message_sha256':record['user_message_sha256']}
    if implicit:result['scope_context_user_message_sha256']=context['user_message_sha256']
    elif target_batch and not qualified and authorized_context:
        result['scope_context_user_message_sha256']=authorized_context['hash']
    if target_batch:
        result['batch_binding']={key:binding[key] for key in ('root','batch_id','case_id','manifest_sha256')}
    return result

def final_review_binding(workspace, proof, files, charts, evidence_path, dispatch, hash_file=digest):
    """Authenticate a saved review without rereading original build/repair logs.

    Frozen stage summaries retain their identities; only the actual review
    call and latest independent final are authenticated again. No chart bytes
    or prior visual judgments are rechecked here.
    """
    if not isinstance(dispatch,dict) or not dispatch:
        raise ValueError('Recorded final dispatch bindings required')
    return _model_review(workspace,proof,files,charts,evidence_path,hash_file,
                         _recorded_dispatch=dispatch)


def model_review(workspace, proof, files, charts, evidence_path):
    """Verify actual implementation and admitted independent review dispatch."""
    return _model_review(workspace,proof,files,charts,evidence_path)


def _model_review(workspace, proof, files, charts, evidence_path, hash_file=digest, _recorded_dispatch=None):
    run=read_json(inside(workspace,'.product-v2/run.json'))
    policy=chart_policy(run)
    analytical=policy in ANALYTICAL_POLICIES
    if analytical and charts.get('chart_policy')!=policy:
        raise ValueError('Review chart snapshot must bind the frozen analytical policy')
    spec=read_json(inside(workspace,'.product-v2/model-dispatch.json'))
    stages=spec.get('stages',{})
    if (spec.get('schema_version')!=1 or not {'build','review'}.issubset(stages)
            or any(k not in {'build','review'} and not re.fullmatch(r'repair-[1-9][0-9]*',k) for k in stages)):
        raise ValueError('Actual build and independent review dispatch records required')
    agents,call_ids,verified={},set(),{}
    mode=spec.get('review_mode','ordinary')
    from batch_control import media_binding,batch,load_review_admission,load_review_dispatch_permit,REVIEW_ADMISSION_CONTRACT
    binding=media_binding(workspace)
    required=False
    if binding:
        _,manifest=batch(binding['root'],binding['batch_id'])
        required=manifest.get('review_admission_contract')==REVIEW_ADMISSION_CONTRACT
    reference=stages['review'].get('review_admission');admission=None;dispatch_permit=None
    if required or reference is not None:
        if not isinstance(reference,dict):raise ValueError('New batch review must bind its immutable acquired admission')
        admission=load_review_admission(workspace,reference)
        if mode!=admission['mode'] or proof.get('review_admission')!=reference:
            raise ValueError('Actual model review and independent proof must bind the acquired review route')
        permit_reference=stages['review'].get('review_dispatch_permit')
        if not isinstance(permit_reference,dict) or proof.get('review_dispatch_permit')!=permit_reference:
            raise ValueError('Actual review and proof require the paid-before-dispatch verification permit')
        dispatch_permit=load_review_dispatch_permit(workspace,reference,permit_reference)
        verified['review_admission']={'reference':reference,'token':admission['token'],'route':admission['mode'],
                                     'model':admission['model'],'effort':admission['effort']}
        verified['review_dispatch_permit']=permit_reference
    if mode not in {'ordinary','original-expedited'}:raise ValueError('Unknown review route; do not silently change models')
    review_model,review_effort='gpt-6.1-sol','ultra'
    if mode=='original-expedited':
        authorization=read_json(admission['authorization']['path']) if admission else spec.get('expedited_authorization',{})
        verified['expedited_authorization']=expedited_authorization(workspace,authorization)
        review_model,review_effort='gpt-6-astra','low'
    review_parent=None;encrypted_binding=None;review_window=None
    repairs=sorted((k for k in stages if k.startswith('repair-')),key=lambda k:int(k.split('-')[1]))
    if repairs!=['repair-'+str(i) for i in range(1,len(repairs)+1)]:
        raise ValueError('Repair dispatch sequence must be contiguous and retained')
    order=[('build','high')]+[(k,'ultra') for k in repairs]+[('review',review_effort)]
    final_implementation=repairs[-1] if repairs else 'build'
    for stage,effort in order:
        record=spec['stages'][stage]
        call_id=record.get('call_id')
        if not call_id or call_id in call_ids: raise ValueError('Distinct stage dispatch call IDs required')
        call_ids.add(call_id)
        if _recorded_dispatch is not None and stage!='review':
            saved=_recorded_dispatch.get(stage,{})
            agent_id=record.get('agent_id')
            if (not isinstance(saved,dict) or not isinstance(agent_id,str) or not agent_id or
                    saved.get('agent_id')!=agent_id or saved.get('call_id')!=call_id or
                    not isinstance(saved.get('dispatch_event_sha256'),str) or
                    not re.fullmatch('[0-9a-f]{64}',saved['dispatch_event_sha256']) or agent_id in agents.values()):
                raise ValueError('Frozen implementation dispatch summary is incomplete or inconsistent')
            if (not isinstance(record.get('artifact_hashes'),dict) or not record['artifact_hashes'] or
                    not record.get('chart_snapshot') or
                    (stage==final_implementation and (record['artifact_hashes']!=files or record['chart_snapshot']!=charts))):
                raise ValueError('Frozen implementation completion snapshot changed')
            agents[stage]=agent_id;verified[stage]=saved
            continue
        call,result,parent_id=_dispatch_events(record['session_log'],call_id)
        if stage=='review': review_parent=parent_id
        payload=call['payload']
        if payload.get('name','').split('.')[-1] not in {'spawn_agent'}:
            raise ValueError('Unsupported model dispatch entry; do not silently downgrade')
        args=json.loads(payload['arguments'])
        if stage=='review' and admission:
            message=args.get('message','')
            if _encrypted_dispatch_message(message):
                called_ns=_dispatch_timestamp_ns(call.get('timestamp'));returned_ns=_dispatch_timestamp_ns(result.get('timestamp'))
                review_window=(called_ns,returned_ns)
                encrypted_binding=_encrypted_review_binding(admission,dispatch_permit,call,result,parent_id)
                if proof.get('review_dispatch_binding')!=encrypted_binding or read_json(evidence_path)!=proof:
                    raise ValueError('Encrypted review proof must bind the exact actual call, cipher digest and frozen admission/permit scope')
                verified['review_dispatch_binding']=encrypted_binding
            elif (not isinstance(message,str) or admission['token'] not in message or dispatch_permit['dispatch_nonce'] not in message or admission['run_id'] not in message or
                  admission['workspace'].casefold() not in message.casefold()):
                raise ValueError('Actual review dispatch message must name its admission token, verified permit nonce, run and workspace')
        expected_model=review_model if stage=='review' else 'gpt-6.1-sol'
        if args.get('fork_turns')!='none' or args.get('model')!=expected_model or args.get('reasoning_effort')!=effort:
            raise ValueError('Actual '+stage+' dispatch must explicitly use '+expected_model+'/'+effort+' with fork_turns=none')
        output=result['payload'].get('output')
        if isinstance(output,str):
            # Actual tool output is commonly a JSON object, optionally wrapped.
            output=json.loads(output)
        # This desktop returns task_name, rather than an undocumented agent UUID.
        agent_id=output.get('task_name') if isinstance(output,dict) else None
        if (not agent_id or record.get('agent_id')!=agent_id or agent_id in agents.values()
                or any(output.get(k) for k in ('error','isError','is_error'))):
            raise ValueError('Distinct actual stage agent IDs required')
        agents[stage]=agent_id
        if (stage in {final_implementation,'review'}
                and (record.get('artifact_hashes')!=files or record.get('chart_snapshot')!=charts)):
            raise ValueError('Model stage record is not bound to current artifacts and chart snapshots')
        if not isinstance(record.get('artifact_hashes'),dict) or not record.get('artifact_hashes') or not record.get('chart_snapshot'):
            raise ValueError('Every original build/repair must retain its actual completion snapshot')
        verified[stage]={'agent_id':agent_id,'call_id':call_id,
            'dispatch_event_sha256':hashlib.sha256(json.dumps([call,result],sort_keys=True,ensure_ascii=False).encode()).hexdigest()}
    if proof.get('reviewer_agent_id')!=agents['review'] or proof.get('decision')!='pass' or proof.get('chart_snapshot')!=charts:
        raise ValueError('Current independent admitted reviewer decision and chart snapshot required')
    review_record=spec['stages']['review']
    review_log=no_links(review_record['review_session_log'])
    if no_links(SESSION_ROOT) not in review_log.parents or review_log.suffix.lower()!='.jsonl':
        raise ValueError('Actual independent review session log required')
    actual_model=False
    actual_identity=False
    actual_attestation=False
    child_sessions=[]
    proof_hash=hash_file(evidence_path)
    with review_log.open(encoding='utf-8') as stream:
        for line in stream:
            try: event=json.loads(line)
            except json.JSONDecodeError: continue
            payload=event.get('payload',{})
            if event.get('type')=='session_meta':
                child_sessions.append(payload)
                spawned=payload.get('source',{}).get('subagent',{}).get('thread_spawn',{}) if isinstance(payload.get('source'),dict) else {}
                if spawned.get('agent_path')==agents['review'] and spawned.get('parent_thread_id')==review_parent:
                    actual_identity=True
                    if encrypted_binding:
                        child_id=payload.get('id');created_ns=_dispatch_timestamp_ns(payload.get('timestamp',event.get('timestamp')))
                        actual_identity=(isinstance(child_id,str) and bool(child_id) and child_id!=review_parent
                                         and review_window[0]<=created_ns<=review_window[1])
            if event.get('type')=='turn_context':
                actual_model=payload.get('model')==review_model and payload.get('effort')==review_effort
            final_message=(payload.get('phase')=='final_answer'
                           or ('phase' not in payload and payload.get('channel')=='final'))
            if event.get('type')=='response_item' and payload.get('type')=='message' and payload.get('role')=='assistant' and final_message:
                actual_attestation=False  # Only the most recent actual final can sign this proof.
                content=payload.get('content',[])
                if not content or any(not isinstance(part.get('text'),str) or part.get('encrypted_content') for part in content):continue
                # Parse the whole final message, never a JSON fragment beside
                # conflicting prose. Only one exact trailing memory block is allowed.
                raw=''.join(part['text'] for part in content)
                raw=re.sub(r'\s*<oai-mem-citation>\s*<citation_entries>[\s\S]*?</citation_entries>\s*<rollout_ids>[\s\S]*?</rollout_ids>\s*</oai-mem-citation>\s*$','',raw)
                try: attestation=json.loads(raw)
                except (json.JSONDecodeError,AttributeError): continue
                if (isinstance(attestation,dict) and actual_model and attestation.get('reviewer_agent_id')==agents['review']
                        and attestation.get('review_evidence_sha256')==proof_hash):
                    if encrypted_binding:
                        actual_attestation=(attestation.get('review_dispatch_binding')==encrypted_binding
                                            and _dispatch_timestamp_ns(event.get('timestamp'))>=review_window[1])
                    else:actual_attestation=True
    if encrypted_binding and len(child_sessions)!=1:actual_identity=False
    if not actual_identity or not actual_attestation:
        raise ValueError('Independent reviewer final must attest the exact review JSON SHA256 and any encrypted dispatch binding; builder cannot self-sign pass')
    if _recorded_dispatch is not None:return verified
    reviews=proof.get('chart_reviews',[])
    if policy==BUILD_CHART_POLICY:
        retained_reviews=proof.get('retained_result_reviews',[])
        expected=charts.get('retained_results',{})
        if (not isinstance(retained_reviews,list) or len(retained_reviews)!=len(expected)
                or {str(r.get('figure_id')) for r in retained_reviews}!=set(expected)):
            raise ValueError('Independently verify every original statistical result used to satisfy the figure mix')
        for item in retained_reviews:
            if (item.get('png_sha256')!=expected[str(item['figure_id'])] or item.get('is_statistical_result') is not True
                    or item.get('monochrome') is not True or not _nonempty_text(item.get('evidence'))):
                raise ValueError('Original workflow figures cannot substitute for retained monochrome results')
    if len(reviews)!=len(charts['figures']) or {str(r.get('figure_id')) for r in reviews}!=set(charts['figures']):
        raise ValueError('Independent review must cover every current chart')
    for r in reviews:
        if r.get('png_sha256')!=charts['figures'][str(r['figure_id'])] or r.get('no_title_header') is not True or not r.get('no_title_header_evidence'):
            raise ValueError('Actual PNG/Word no-title-header review required')
        for key in ('meaning','data','legibility','layout','explanation'):
            item=r.get(key,{})
            if item.get('passed') is not True or not item.get('evidence'):
                raise ValueError('Independent chart review failed or missing: '+key)
            if analytical and not _nonempty_text(item.get('evidence')):
                raise ValueError('Analytical chart review requires actual quality evidence: '+key)
        if analytical:
            if not _nonempty_text(r.get('no_title_header_evidence')):
                raise ValueError('Analytical chart review requires actual no-title-header evidence')
            if r.get('no_schematic') is not True or not _nonempty_text(r.get('no_schematic_evidence')):
                raise ValueError('Actual PNG/Word no-示意 review required')
    return verified
