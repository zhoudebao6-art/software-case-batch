"""Two delivery PNGs in the existing layout check; no separate review workflow."""
from common import inside, delivery_paths, digest, SYSTEM_CODE_LAYOUT
LEGACY_POLICY = 'source-system-png-v1'
POLICY = 'source-system-png-v2'
NAMES = ('时序图', '设计图')

def enabled(run):
    policy=run.get('system_diagram_policy')
    if policy is not None and policy not in {LEGACY_POLICY,POLICY}:raise ValueError('Unknown system diagram policy')
    return policy in {LEGACY_POLICY,POLICY} or run.get('delivery_layout_version')==SYSTEM_CODE_LAYOUT

def review_artifacts(run, artifacts):
    """Current two PNGs join the existing first review; frozen v1 is unchanged."""
    if run.get('system_diagram_policy') != POLICY or run.get('revision_of'):
        return {}
    system = delivery_paths(run)['system_name']
    result = {system+'/'+name+'.png': artifacts.get(system+'/'+name+'.png') for name in NAMES}
    if any(not isinstance(sha,str) or len(sha)!=64 for sha in result.values()):
        raise ValueError('Current system diagram artifact hashes required')
    return result

def required_review_paths(run, artifacts, indexed, required_ids=None):
    """Bind existing rendered workspace PNGs by final bytes, never mark them read."""
    required=set()
    for name,sha in review_artifacts(run,artifacts).items():
        matches=[path for path,row in indexed.items() if row['sha256']==sha
                 and (required_ids is None or row['id'] in required_ids)]
        if not matches:
            raise ValueError('System diagram missing from required visual evidence: '+name+
                             '; include its byte-identical rendered workspace PNG in existing manifest.files')
        required.add(sorted(matches)[0])
    return required

def actual_notes(value):
    return ((isinstance(value,str) and bool(value.strip())) or
            (isinstance(value,list) and bool(value) and
             all(isinstance(note,str) and bool(note.strip()) for note in value)))

def validate_first_notes(run, notes):
    if run.get('system_diagram_policy') == POLICY and not run.get('revision_of') and not actual_notes(notes):
        raise ValueError('System diagram first review requires actual textual visual_notes')

def validate_affected_review(run, current, changed, checks):
    """Only changed diagrams need the original repairer's targeted visual check."""
    from contracts import unread_visual_evidence
    for name,sha in review_artifacts(run,current).items():
        if name not in changed:continue
        if not any(item.get('artifact_hashes',{}).get(name)==sha and item.get('exit_code')==0
                   and actual_notes(item.get('visual_notes')) and not unread_visual_evidence(item['visual_notes'])
                   for item in checks.values()):
            raise ValueError('Changed system diagram needs affected visual selfcheck: '+name)

def validate(workspace, output, run):
    if not enabled(run):return {}
    from PIL import Image
    system=delivery_paths(run,output)['system']; result={}
    for name in NAMES:
        png=inside(system,name+'.png')
        with Image.open(png) as image:
            if image.format!='PNG':raise ValueError('Actual system PNG required: '+name)
            image.load()
            result[name]={'sha256':digest(png),'width':image.width,'height':image.height}
    return result
