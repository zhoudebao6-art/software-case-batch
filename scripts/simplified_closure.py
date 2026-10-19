"""One receipt-backed targeted closure; never manufacture an independent pass.

The original reviewer and repairer attest their own existing evidence in actual
Codex sessions. This module only authenticates, checks changed dependencies and
publishes. It never starts a model, rebuilds an artifact or repeats a recording.
"""
import hashlib
import json
import os
from pathlib import Path
import re
import tempfile
import zipfile

from common import digest, file_map, inside, no_links, read_json, write_json, delivery_paths
from review_packet import execution_checks

CONTRACT='targeted-closure-v1'


def authorized_instruction(text,workspace,case_id,scope_context=False):
    """Recognize direct scope/action/reduced-review intent, not fixed wording."""
    from contracts import _direct_user_lines
    if ('<heartbeat>' in text or re.search(r'不(?:允许|同意|授权)[^，,。；;\n]{0,48}(?:小问题|简化|(?:取消|跳过|省略|减少|绕过|停止).{0,8}(?:审核|复验)|(?:直接|就|只).{0,10}(?:打包|压缩包|导出))|不要.{0,5}(?:取消|跳过|省略|减少|绕过|停止).{0,8}(?:审核|复验)|(?:仍需|仍要|必须|照常).{0,12}(?:审核|复验)',text)):
        return False
    lines=_direct_user_lines(text)
    direct=[]
    for line in lines:
        if (re.search(r'[?？]|能不能|是否|可不可以|假如|假设',line)
                or re.match(r'^(?:[“"\']|文档|材料|原文|引用|示例|例如|别人|对方|有人|系统说明)',line)
                or re.search(r'(?:不得|不能|禁止).{0,20}(?:打包|压缩包|导出)|(?:不要|不应).{0,20}(?:直接|就|只).{0,10}(?:打包|压缩包|导出)',line)):
            continue
        direct.append(line)
    statement='\n'.join(direct)
    path=str(workspace).replace('\\','/').rstrip('/').casefold()
    repair_pattern=r'小问题.{0,32}(?:修|补).{0,32}(?:打包|压缩包|导出)'
    scope=False
    for clause in re.split(r'[。；;\n]',statement):
        if not re.search(repair_pattern,clause):continue
        # A delivery location is not an instruction to work on that case/path.
        scoped=re.sub(r'(?:成品|成果|输出|交付|候选)(?:文件|目录|路径|位置)?\s*(?:默认|放到|放在|保存到|保存至|输出到|集中到|用|位于|为|：|:)\s*[A-Za-z]:[\\/][^，,。；;\n]*','',clause)
        normalized=scoped.replace('\\','/').casefold()
        path_scope=bool(re.search(r'(?<![\w/.:\-])'+re.escape(path)+r'(?![\w/.\-])',normalized))
        case_scope=scope_context and bool(re.search(r'(?<![A-Za-z0-9_./:\-])'+re.escape(case_id)+r'(?![A-Za-z0-9_.\-])',scoped,re.I))
        explicit_scope=bool(re.search(r'(?<![A-Za-z0-9_])case_[A-Za-z0-9_\-]+|[A-Za-z]:[\\/]',scoped,re.I))
        general_scope=not explicit_scope and bool(re.search(r'(?:以后|今后)\s*(?:所有|全部|每个案件|这种|这类|类似|小问题)|通用要求|所有案件',scoped))
        scope=scope or path_scope or case_scope or general_scope
        scope=scope or (scope_context and not explicit_scope and any(key in scoped for key in ('剩余批次','剩下的案件','剩余案件')))
    repair=bool(re.search(repair_pattern,statement,re.S))
    reduced=bool(re.search(r'(?:不再|不要|不得|不用|无需).{0,32}(?:反复|整案|复验|审核|大费周章)',statement,re.S))
    return scope and repair and reduced


def reference(path):
    path=no_links(path)
    return {'path':str(path),'sha256':digest(path)}


def bound(workspace,value):
    if not isinstance(value,dict):raise ValueError('Actual workspace evidence path and SHA256 required')
    path=no_links(value['path']) if Path(value['path']).is_absolute() else inside(workspace,value['path'])
    if workspace not in path.parents or not path.is_file() or digest(path)!=value.get('sha256'):
        raise ValueError('Evidence missing, changed or outside this case workspace')
    return path


def authorization(value,workspace,case_id,parent_session_log=None):
    """Read a real human message, never an assistant or a self-declared policy."""
    import contracts
    path=no_links(value['session_log'])
    if no_links(contracts.SESSION_ROOT) not in path.parents or path.suffix.lower()!='.jsonl':
        raise ValueError('Simplified closure authorization requires an actual Codex user session')
    matches=[];session_ids=[]
    with path.open(encoding='utf-8') as stream:
        for line in stream:
            try:event=json.loads(line)
            except json.JSONDecodeError:continue
            payload=event.get('payload',{})
            if event.get('type')=='session_meta':session_ids.append(payload.get('id'))
            text=None
            if event.get('type')=='response_item' and payload.get('type')=='message' and payload.get('role')=='user':
                text=''.join(item.get('text','') for item in payload.get('content',[]) if isinstance(item,dict))
            elif event.get('type')=='event_msg' and payload.get('type')=='user_message':text=payload.get('message')
            if isinstance(text,str) and hashlib.sha256(text.encode()).hexdigest()==value.get('user_message_sha256'):
                matches.append(text)
    if not matches:raise ValueError('Exact actual human simplified closure instruction not found')
    text=matches[0]
    scope_context=False
    if parent_session_log is not None and len(session_ids)==1:
        parent_path=no_links(parent_session_log)
        if no_links(contracts.SESSION_ROOT) not in parent_path.parents or parent_path.suffix.lower()!='.jsonl':
            raise ValueError('Remaining-case policy scope requires an actual review parent session')
        with parent_path.open(encoding='utf-8') as stream:
            for line in stream:
                try:event=json.loads(line)
                except json.JSONDecodeError:continue
                if event.get('type')=='session_meta':
                    payload=event['payload'];source=payload.get('source',{})
                    ancestor=source.get('subagent',{}).get('thread_spawn',{}).get('parent_thread_id') if isinstance(source,dict) else None
                    scope_context=payload.get('id')==session_ids[0] or ancestor==session_ids[0]
                    break
    if not authorized_instruction(text,workspace,case_id,scope_context):
        raise ValueError('Human instruction must authorize targeted selfchecks and simplified packaging for this scope')
    return {'session_log':str(path),'user_message_sha256':value['user_message_sha256']}


def repair_binding(workspace,path,proof,excluded):
    """Authenticate actual repair spawn, child identity, latest final and scope."""
    import contracts
    from scheduler_repair import ReviewFreshness
    entry=proof['repair_dispatch'];agent=entry['agent_id']
    freshness=ReviewFreshness(agent,entry['call_id'])
    call,result,parent=contracts._dispatch_events(entry['session_log'],entry['call_id'],freshness.parent)
    payload=call['payload'];args=json.loads(payload['arguments'])
    output=result['payload'].get('output')
    if isinstance(output,str):output=json.loads(output)
    if (payload.get('name','').split('.')[-1]!='spawn_agent' or args.get('fork_turns')!='none'
            or args.get('model')!='gpt-6.1-sol' or args.get('reasoning_effort')!='ultra'
            or not isinstance(output,dict) or output.get('task_name')!=agent or agent in excluded
            or any(output.get(key) for key in ('error','isError','is_error'))):
        raise ValueError('Original repairer must have a distinct actual successful gpt-6.1-sol/ultra dispatch')
    child=no_links(entry['repair_session_log'])
    if no_links(contracts.SESSION_ROOT) not in child.parents or child.suffix.lower()!='.jsonl':
        raise ValueError('Actual original repairer child session required')
    identities=[];actual_model=False;attested=False
    with child.open(encoding='utf-8') as stream:
        for position,line in enumerate(stream):
            try:event=json.loads(line)
            except json.JSONDecodeError:continue
            freshness.child(event,position)
            value=event.get('payload',{})
            if event.get('type')=='session_meta':
                source=value.get('source',{})
                identities.append(source.get('subagent',{}).get('thread_spawn',{}) if isinstance(source,dict) else {})
            if event.get('type')=='turn_context':actual_model=value.get('model')=='gpt-6.1-sol' and value.get('effort')=='ultra'
            if (event.get('type')=='response_item' and value.get('type')=='message' and value.get('role')=='assistant'
                    and (value.get('phase')=='final_answer' or ('phase' not in value and value.get('channel')=='final'))):
                attested=False
                parts=value.get('content',[])
                if not parts or any(not isinstance(item.get('text'),str) or item.get('encrypted_content') for item in parts):continue
                raw=''.join(item['text'] for item in parts)
                raw=re.sub(r'\s*<oai-mem-citation>\s*<citation_entries>[\s\S]*?</citation_entries>\s*<rollout_ids>[\s\S]*?</rollout_ids>\s*</oai-mem-citation>\s*$','',raw)
                try:final=json.loads(raw)
                except json.JSONDecodeError:continue
                def matches(value):
                    if not isinstance(value,dict):return False
                    if value==proof:return True
                    if any(value.get(key)==digest(path) for key in ('repair_evidence_sha256','handoff_sha256','repair_handoff_sha256')):
                        declared=value.get('handoff') or value.get('repair_handoff')
                        return declared is None or (isinstance(declared,str) and no_links(declared)==path)
                    if value.get('sha256')==digest(path) and isinstance(value.get('path'),str) and no_links(value['path'])==path:return True
                    return any(matches(item) for item in value.values() if isinstance(item,dict))
                attested=(isinstance(final,dict) and actual_model and final.get('repairer_agent_id',agent)==agent and matches(final))
    if (len(identities)!=1 or identities[0].get('agent_path')!=agent
            or identities[0].get('parent_thread_id')!=parent or not attested):
        raise ValueError('Original repairer latest actual final must attest the exact current repair evidence SHA256')
    freshness.verify()
    return {'agent_id':agent,'call_id':entry['call_id'],'parent_session_id':parent,
            'dispatch_event_sha256':hashlib.sha256(json.dumps([call,result],sort_keys=True,ensure_ascii=False).encode()).hexdigest()}


def same_source_members(first,zip_rel,archive):
    """Only an authenticated first-review member snapshot can prove repacking."""
    from contracts import zip_member_hashes
    prior=first.get('source_package')
    if prior is None:return False  # Older first reviews keep their actual conservative scope.
    if (not isinstance(prior,dict) or prior.get('sha256')!=first.get('source_zip_sha256')
            or prior.get('sha256')!=first['reviewed_files'].get(zip_rel)
            or not isinstance(prior.get('files'),dict) or not prior['files']
            or any(not isinstance(key,str) or not isinstance(sha,str) or not re.fullmatch('[0-9a-f]{64}',sha)
                   for key,sha in prior['files'].items())):
        raise ValueError('First source member snapshot is missing its original ZIP binding')
    return prior['files']==zip_member_hashes(archive)


def word_caption_layout_fix(first,number,word):
    """Recognize only a diagnosed Word caption split and its actual keep-next."""
    from contracts import NS
    import xml.etree.ElementTree as ET
    review=next(item for item in first['chart_reviews'] if str(item['figure_id'])==number)
    diagnosis=review.get('layout',{}).get('evidence','')
    if (not re.search(r'Word|文档',diagnosis,re.I)
            or not re.search(r'caption|图题',diagnosis,re.I)
            or not re.search(r'split|across.pages|pagination|跨页|分页|分离',diagnosis,re.I)
            or not re.search(r'PNG\s*(?:is|already|remains|本来|本身|已|仍然)?\s*(?:clear|correct|readable|清晰|正确)',diagnosis,re.I)):
        return False
    expected=first['chart_snapshot']['figures'][number]
    with zipfile.ZipFile(word) as archive:
        document=ET.fromstring(archive.read('word/document.xml'))
        relations={item.attrib['Id']:item.attrib['Target'] for item in ET.fromstring(archive.read('word/_rels/document.xml.rels'))}
        matches=[]
        for paragraph in document.findall('.//w:p',NS):
            for blip in paragraph.findall('.//a:blip',NS):
                target=relations.get(blip.get('{'+NS['r']+'}embed'),'')
                member='word/'+target if not target.startswith('/') else target.lstrip('/')
                if member in archive.namelist() and hashlib.sha256(archive.read(member)).hexdigest()==expected:
                    keep=paragraph.find('w:pPr/w:keepNext',NS)
                    matches.append(keep is not None and keep.get('{'+NS['w']+'}val','true').casefold() not in {'0','false','off','no'})
    return bool(matches) and all(matches)


def repaired_chart_checks(first,charts,fixes,by_kind,word_name,changed,current,word):
    """Resolve known failed judgments using the original repairer's affected check."""
    from contracts import first_chart_failures,unread_visual_evidence
    for number,key in first_chart_failures(first,charts.get('chart_policy')):
        if word_name not in changed:
            raise ValueError('Failed first chart check cannot be reused unchanged: '+number+'/'+key)
        if (key in {'meaning','data','legibility','layout','no_title_header'}
                and charts.get('figures',{}).get(number)==first['chart_snapshot']['figures'][number]
                and not (key=='layout' and word_caption_layout_fix(first,number,word))):
            raise ValueError('Failed first chart check needs its actual corrected chart: '+number+'/'+key)
        resolved=False
        for fix in fixes:
            if word_name not in fix['affected_files']:continue
            for kind in fix['checks']:
                check=by_kind[kind]
                if (check.get('artifact_hashes',{}).get(word_name)!=current[word_name]
                        or not check.get('visual_notes') or unread_visual_evidence(check['visual_notes'])):continue
                reviews=check.get('chart_reviews',[])
                if not isinstance(reviews,list):continue
                matches=[item for item in reviews if isinstance(item,dict) and str(item.get('figure_id'))==number]
                if len(matches)!=1:continue
                item=matches[0]
                value=({'passed':item.get(key),'evidence':item.get(key+'_evidence')}
                       if key.startswith('no_') else item.get(key,{}))
                if (item.get('png_sha256')==charts.get('figures',{}).get(number)
                        and isinstance(value,dict) and value.get('passed') is True
                        and isinstance(value.get('evidence'),str) and value['evidence'].strip()
                        and not unread_visual_evidence(value['evidence'])):resolved=True
        if not resolved:
            raise ValueError('Failed first chart check lacks corresponding affected visual selfcheck: '+number+'/'+key)


def validate(workspace,path,output,run):
    import proflow
    from contracts import first_review_binding, delivery_layout, chart_snapshot
    proof=read_json(path)
    if not isinstance(proof,dict):raise ValueError('Targeted closure evidence must be a JSON object')
    if (proof.get('contract')!=CONTRACT or proof.get('run_id')!=run['run_id']
            or proof.get('workspace')!=str(workspace) or not proof.get('case_id')):
        raise ValueError('Targeted closure evidence belongs to a different run/case/workspace')
    if digest(no_links(run['source_docx']))!=run['source_docx_sha256']:
        raise ValueError('Original source document changed')
    first_path=bound(workspace,proof['first_review']);first=read_json(first_path)
    spec_path=bound(workspace,proof['first_dispatch'])
    spec=read_json(spec_path)
    auth=authorization(proof['authorization'],workspace,proof['case_id'],spec['stages']['review']['session_log'])
    if first.get('run_id')!=run['run_id']:
        raise ValueError('First independent review must name this exact run_id')
    first_dispatch=first_review_binding(workspace,first,first_path,spec_path)
    for item in first['checks']:
        log=inside(workspace,item['log'])
        if type(item.get('exit_code')) is not int or not item.get('command') or not log.stat().st_size or digest(log)!=item.get('sha256'):
            raise ValueError('First necessary independent execution evidence missing or changed')
    excluded={item['agent_id'] for item in first_dispatch.values() if isinstance(item,dict) and 'agent_id' in item}
    repair=repair_binding(workspace,path,proof,excluded)
    first_issues=first.get('issues',first.get('findings'))
    fixes=proof.get('resolutions')
    if (not isinstance(first_issues,list) or not first_issues or not isinstance(fixes,list)
            or any(not isinstance(item,dict) or not isinstance(item.get('id'),str) or not item['id'] for item in first_issues+fixes)
            or len({item['id'] for item in first_issues})!=len(first_issues)
            or len({item['id'] for item in fixes})!=len(fixes)
            or {item['id'] for item in first_issues}!={item['id'] for item in fixes}):
        raise ValueError('List all original independent issues once and resolve each original ID')
    current=file_map(output)
    if current!=proof.get('files'):raise ValueError('Current delivery files differ from repairer attested snapshot')
    old=first['reviewed_files']
    changed=sorted(key for key in set(current)|set(old) if current.get(key)!=old.get(key))
    if proof.get('changed_files')!=changed:raise ValueError('Exact changed artifact list required')
    checks=execution_checks(proof.get('checks'));by_kind={item['kind']:item for item in checks}
    affected_checks=proof.get('affected_checks',[])
    if (not isinstance(affected_checks,list) or any(not isinstance(item,dict) or not isinstance(item.get('kind'),str) for item in affected_checks)
            or len({item['kind'] for item in affected_checks})!=len(affected_checks)
            or any(item['kind'] in by_kind for item in affected_checks)):
        raise ValueError('Supplementary affected checks need distinct kinds, without replacing original six facts')
    by_kind.update({item['kind']:item for item in affected_checks})
    first_checks={item['kind']:item for item in first['checks']}
    for item in checks+affected_checks:
        log=inside(workspace,item['log'])
        if item.get('exit_code')!=0 or not item.get('command') or not log.stat().st_size or digest(log)!=item.get('sha256'):
            raise ValueError('Current successful execution evidence missing, failed or changed: '+item['kind'])
        for relative,sha in item.get('input_files',{}).items():
            if digest(inside(workspace,relative))!=sha:raise ValueError('Execution input changed: '+relative)
        artifacts=item.get('artifact_hashes',{})
        if not isinstance(artifacts,dict) or any(current.get(key)!=sha for key,sha in artifacts.items()):
            raise ValueError('Execution evidence belongs to an older artifact')
        prior=first_checks.get(item['kind'],{})
        if (item.get('log')==prior.get('log') and item.get('sha256')==prior.get('sha256')
                and any(item.get(key,{})!=prior.get(key,{}) for key in ('input_files','artifact_hashes'))):
            raise ValueError('Reused successful execution fact has changed dependencies; target only the affected check')
    paths=delivery_paths(run,output);zip_rel=paths['source_zip'].relative_to(output).as_posix()
    container_only=zip_rel in changed and same_source_members(first,zip_rel,paths['source_zip'])
    covered=set()
    original_by_id={item['id']:item for item in first_issues}
    for fix in fixes:
        if fix.get('status')!='resolved' or not fix.get('checks') or not fix.get('result'):
            raise ValueError('Unresolved original issue, including core defect, blocks closure')
        affected=fix.get('affected_files',[])
        if not isinstance(affected,list) or not affected or any(key not in current for key in affected):
            raise ValueError('Each original repair requires actual affected delivery paths')
        tested=set()
        for kind in fix['checks']:
            if kind not in by_kind:raise ValueError('Affected selfcheck kind missing')
            tested.update(by_kind[kind].get('artifact_hashes',{}))
        original=original_by_id[fix['id']]
        required=original.get('required_checks',[])
        if not set(required).issubset(set(fix['checks'])):
            raise ValueError('Original substantive issue lacks its required affected check coverage')
        if (original.get('core') is True or original.get('severity') in {'core','critical','P0','P1','实质','重大'}
                or original.get('priority') in {'P0','P1','0','1',0,1}
                or (zip_rel in affected and zip_rel in changed and not container_only)):
            if not set(fix['checks'])&{'algorithm','api','persistence','browser'}:
                raise ValueError('Core defect requires actual affected business evidence, not only packaging')
        if not set(affected).issubset(tested):raise ValueError('Affected selfchecks must bind the repaired artifacts')
        if run['word_name'] in affected and run['word_name'] in changed:
            if not any(by_kind[kind].get('visual_notes') for kind in fix['checks']):
                raise ValueError('Changed Word requires actual affected visual selfcheck evidence')
        covered.update(affected)
    if not set(changed).issubset(covered):raise ValueError('Changed delivery artifacts lack targeted issue/selfcheck coverage')
    if (proof.get('source_zip_sha256')!=current.get(zip_rel)
            or by_kind['package_startup'].get('artifact_hashes',{}).get(zip_rel)!=current.get(zip_rel)):
        raise ValueError('Actual package startup selfcheck must bind the current source ZIP')
    word=delivery_layout(output,run)
    for artifact in (word,paths['source_zip']):
        with zipfile.ZipFile(artifact) as archive:
            if archive.testzip() is not None:raise ValueError('Broken Word/source ZIP blocks closure')
    scanned=proflow.scan_delivery(output,run['word_name'],run)
    if not scanned['passed']:raise ValueError('Delivery scan failed: '+json.dumps(scanned['hits'][:10],ensure_ascii=False))
    proflow.check_data_quality(workspace,output)
    charts=chart_snapshot(workspace,word,run) if current.get(run['word_name'])!=old.get(run['word_name']) else first['chart_snapshot']
    if charts!=proof.get('chart_snapshot'):raise ValueError('Current chart snapshot differs from targeted selfcheck')
    repaired_chart_checks(first,charts,fixes,by_kind,run['word_name'],changed,current,word)
    for relative,sha in read_json(inside(workspace,'.product-v2/source-package.json'))['files'].items():
        if digest(inside(workspace,relative))!=sha:raise ValueError('Source changed after packaging')
    if read_json(inside(workspace,'.product-v2/source-package.json'))['sha256']!=current[zip_rel]:
        raise ValueError('Source package receipt differs from the delivered ZIP')
    recording=read_json(inside(workspace,'.product-v2/recording.json'))
    from media_evidence import validate_recording_duration
    validate_recording_duration(recording,run.get('recording_policy_version','legacy-fixed-v1'))
    if recording.get('passed') is not True or recording.get('sha256')!=digest(paths['video']):
        raise ValueError('Successful current recording required')
    controlled=read_json(inside(workspace,'.product-v2/controlled-video.json'))
    timeline=no_links(controlled['timeline'])
    if workspace not in timeline.parents or digest(timeline)!=controlled['sha256'] or proof.get('video_timeline_sha256')!=controlled['sha256']:
        raise ValueError('Controlled media evidence missing or changed')
    video_rel=paths['video'].relative_to(output).as_posix()
    if current[video_rel]==old.get(video_rel):
        if first.get('video_timeline_sha256')!=controlled['sha256']:
            raise ValueError('Unchanged video must reuse its original qualified timeline')
    else:
        from media_evidence import validate as validate_video
        proflow.completed_recording(workspace,recording,paths['video'])
        validate_video(workspace,timeline,paths['video'],workspace/'.product-v2/recording.json')
    provenance=read_json(inside(workspace,'.product-v2/data-provenance.json'))
    if any(not provenance.get(key) for key in ('nature','sources','validation')):
        raise ValueError('Original data nature and validation evidence missing')
    proflow.cleanup_ready(workspace)
    return {'schema_version':1,'kind':CONTRACT,'status':'complete','delivery_state':'simplified-candidate',
            'delivery_layout_version':paths['version'],'run_id':run['run_id'],'case_id':proof['case_id'],
            'workspace':str(workspace),'files':current,'chart_snapshot':charts,'source_docx_sha256':run['source_docx_sha256'],
            'first_review':reference(first_path),'first_dispatch':reference(spec_path),'verified_first_dispatch':first_dispatch,
            'first_independent_decision':'revise','independent_pass_claimed':False,'verified_repair_dispatch':repair,
            'execution_evidence':reference(path),'authorization':auth,'changed_files':changed,
            'reused_files':{key:sha for key,sha in current.items() if old.get(key)==sha},'at':proflow.utc()}


def whole_case(workspace,destination,archive,publication):
    """Recover a renamed ZIP only with its own frozen creation intent."""
    archive=no_links(archive)
    if (archive.suffix.lower()!='.zip' or archive==destination or destination in archive.parents
            or workspace in archive.parents):raise ValueError('Whole-case ZIP must be an explicit separate output file')
    members={destination.name+'/'+key:sha for key,sha in publication['files'].items()}
    intent_path=workspace/'.product-v2/whole-case-intent.json';receipt_path=workspace/'.product-v2/whole-case-package.json'
    intent={'archive':str(archive),'destination':str(destination),'members':members,
            'publication':reference(workspace/'.product-v2/publish-receipt.json')}
    if intent_path.exists():
        if read_json(intent_path)!=intent:raise ValueError('Whole-case archive intent changed')
    else:
        if archive.exists():raise ValueError('Existing unrelated whole-case ZIP will never be overwritten or adopted')
        write_json(intent_path,intent)
    def verify(target):
        with zipfile.ZipFile(target) as stream:
            if len(stream.namelist())!=len(members) or set(stream.namelist())!=set(members):
                raise ValueError('Whole-case ZIP members/CRC differ')
            for key,sha in members.items():
                h=hashlib.sha256()
                with stream.open(key) as source:
                    for block in iter(lambda:source.read(1024*1024),b''):h.update(block)
                if h.hexdigest()!=sha:raise ValueError('Whole-case ZIP member SHA256 differs')
    if receipt_path.exists():
        saved=read_json(receipt_path)
        if saved.get('archive')!=reference(archive) or saved.get('members')!=members:raise ValueError('Completed whole-case ZIP changed')
        return saved
    if not archive.exists():
        archive.parent.mkdir(parents=True,exist_ok=True)
        # A same-directory artifact draft allows atomic rename on any output volume.
        draft=archive.with_name(archive.name+'.new');no_links(draft)
        if not draft.exists():
            # Write directly beside the final archive. Reading every member to
            # EOF below checks both ZIP CRC and the publication SHA256 once.
            fd,temporary=tempfile.mkstemp(prefix='.scb-whole-',suffix='.tmp',dir=archive.parent)
            try:
                with os.fdopen(fd,'wb') as target:
                    with zipfile.ZipFile(target,'w',compression=zipfile.ZIP_DEFLATED,compresslevel=6) as stream:
                        for key in publication['files']:
                            source=inside(destination,key)
                            stream.write(source,destination.name+'/'+key,compress_type=zipfile.ZIP_STORED if source.suffix.lower() in {'.zip','.mp4','.docx'} else zipfile.ZIP_DEFLATED)
                    target.flush();os.fsync(target.fileno())
                if draft.exists():raise ValueError('Whole-case ZIP draft appeared concurrently')
                Path(temporary).rename(draft)
            finally:
                Path(temporary).unlink(missing_ok=True)
        verify(draft)
        if archive.exists():raise ValueError('Whole-case ZIP destination appeared concurrently')
        before=draft.stat()
        draft.rename(archive)
        after=archive.stat()
        if (before.st_dev,before.st_ino,before.st_size,before.st_mtime_ns)!=(after.st_dev,after.st_ino,after.st_size,after.st_mtime_ns):
            raise ValueError('Whole-case ZIP identity changed during atomic rename')
    else:
        # Recovery after rename has no in-memory verification result.
        verify(archive)
    if file_map(destination)!=publication['files']:raise ValueError('Published delivery changed while packaging')
    result={'schema_version':1,'status':'complete','archive':reference(archive),'members':members,
            'publication':intent['publication'],'crc_and_each_member_sha256_verified':True}
    write_json(receipt_path,result);return result


def close(workspace,evidence,destination,archive,owner_pid=None):
    import proflow
    from batch_control import transaction,media_binding,sync_simplified_delivery
    workspace=no_links(workspace);path=no_links(evidence);destination=no_links(destination);archive=no_links(archive)
    if workspace not in path.parents:raise ValueError('Closure evidence must be inside the original workspace')
    binding=media_binding(workspace)
    # Check owner and active tickets before touching any candidate or output.
    if binding:sync_simplified_delivery(workspace,owner_pid,preflight=True)
    with transaction(workspace/'.product-v2'):
        run=read_json(inside(workspace,'.product-v2/run.json'))
        receipt_path=workspace/'.product-v2/simplified-final-receipt.json'
        if receipt_path.exists():
            receipt=read_json(receipt_path)
            if (receipt.get('kind')!=CONTRACT or receipt.get('execution_evidence')!=reference(path)
                    or receipt.get('run_id')!=run['run_id'] or receipt.get('workspace')!=str(workspace)):
                raise ValueError('Frozen simplified closure evidence changed')
            for key in ('first_review','first_dispatch','execution_evidence'):bound(workspace,receipt[key])
            proof=read_json(path)
            excluded={item['agent_id'] for item in receipt['verified_first_dispatch'].values() if isinstance(item,dict) and 'agent_id' in item}
            if repair_binding(workspace,path,proof,excluded)!=receipt['verified_repair_dispatch']:
                raise ValueError('Frozen original repair dispatch changed')
            for check in proof['checks']+proof.get('affected_checks',[]):
                if digest(inside(workspace,check['log']))!=check['sha256']:raise ValueError('Frozen successful selfcheck log changed')
        else:
            if (workspace/'.product-v2/final-receipt.json').exists():raise ValueError('Existing complete acceptance remains frozen; use its ordinary publication route')
            receipt=validate(workspace,path,no_links(run['output']),run)
            write_json(receipt_path,receipt)
        publication=proflow.publish(workspace,destination,_simplified=True)
        if publication['source_receipt_sha256']!=digest(receipt_path) or publication['files']!=receipt['files']:
            raise ValueError('Publication differs from the frozen simplified closure')
        package=whole_case(workspace,destination,archive,publication)
        delivery_path=workspace/'.product-v2/simplified-delivery-receipt.json'
        result={'schema_version':1,'kind':CONTRACT,'status':'delivered','closure_label':'用户授权简化收尾',
                'run_id':receipt['run_id'],'case_id':receipt['case_id'],'workspace':str(workspace),
                'destination':str(destination),'files':publication['files'],'independent_pass_claimed':False,
                'first_independent_decision':'revise','closure':reference(receipt_path),
                'publication':reference(workspace/'.product-v2/publish-receipt.json'),
                'whole_case_package':reference(workspace/'.product-v2/whole-case-package.json'),'archive':package['archive']}
        if delivery_path.exists():
            if read_json(delivery_path)!=result:raise ValueError('Existing delivered receipt changed')
        else:write_json(delivery_path,result)
        if binding:sync_simplified_delivery(workspace,owner_pid)
        return result


def draft(workspace,manifest,evidence):
    """Derive mechanical fields within the existing repair, before its one final.

    Manifest supplies existing authorization/dispatch, original review paths,
    execution facts and issue resolutions. Output is unsigned; only the actual
    repairer's later final can authenticate it. No audit or business is run.
    """
    workspace=no_links(workspace);evidence=no_links(evidence)
    if workspace not in evidence.parents or evidence.exists():raise ValueError('Closure draft requires a new private workspace evidence file')
    value=read_json(manifest);run=read_json(inside(workspace,'.product-v2/run.json'));output=no_links(run['output'])
    for key in ('first_review','first_dispatch'):
        if isinstance(value.get(key),str):value[key]=reference(inside(workspace,value[key]) if not Path(value[key]).is_absolute() else value[key])
        bound(workspace,value[key])
    first=read_json(value['first_review']['path']);current=file_map(output)
    if 'execution' in value:
        execution=read_json(bound(workspace,value.pop('execution')))
        value['checks']=execution['checks']
    paths=delivery_paths(run,output)
    from contracts import chart_snapshot
    charts=first['chart_snapshot'] if current.get(run['word_name'])==first['reviewed_files'].get(run['word_name']) else chart_snapshot(workspace,paths['word'],run)
    value.update(contract=CONTRACT,workspace=str(workspace),run_id=run['run_id'],files=current,
                 changed_files=sorted(key for key in set(current)|set(first['reviewed_files']) if current.get(key)!=first['reviewed_files'].get(key)),
                 chart_snapshot=charts,source_zip_sha256=digest(paths['source_zip']),
                 video_timeline_sha256=read_json(inside(workspace,'.product-v2/controlled-video.json'))['sha256'])
    write_json(evidence,value)
    return {'status':'unsigned-draft','evidence':reference(evidence),'scope':'Mechanical metadata only. Original repairer must complete real affected checks and attest this SHA256 in its existing final.'}


def delivery_status(workspace,output,run):
    """Bounded receipt/hash summary, with the original revise explicitly visible."""
    result={'kind':'workflow-status','workspace':str(workspace),'run_id':run['run_id'],
            'state':'closure_incomplete','next_actions':['close-simplified'],
            'independent_visual_review':'first-revise-targeted-selfchecks','independent_pass_claimed':False,
            'verification_scope':'Recorded simplified closure and current artifact/archive hashes only; no stage or frame scan repeated.'}
    try:
        closure_path=inside(workspace,'.product-v2/simplified-final-receipt.json');closure=read_json(closure_path)
        if (closure.get('kind')!=CONTRACT or closure.get('run_id')!=run['run_id']
                or closure.get('workspace')!=str(workspace) or file_map(output)!=closure.get('files')):
            raise ValueError('Simplified candidate identity or artifact snapshot changed')
        for key in ('first_review','first_dispatch','execution_evidence'):bound(workspace,closure[key])
        path=workspace/'.product-v2/simplified-delivery-receipt.json'
        if not path.exists():return result
        value=read_json(path)
        if (value.get('status')!='delivered' or value.get('closure')!=reference(closure_path)
                or value.get('files')!=closure['files'] or value.get('destination')!=str(output)
                or value.get('independent_pass_claimed') is not False):raise ValueError('Simplified delivery receipt changed')
        for key in ('publication','whole_case_package'):bound(workspace,value[key])
        if value['archive']!=reference(value['archive']['path']):raise ValueError('Whole-case ZIP changed or missing')
        result.update(state='published',next_actions=[],last_completed='published',receipt=str(path),closure_label='用户授权简化收尾')
    except (ValueError,OSError,KeyError,TypeError) as exc:
        result.update(state='unknown',reason=str(exc),next_actions=['inspect-simplified-closure-receipts'])
    return result
