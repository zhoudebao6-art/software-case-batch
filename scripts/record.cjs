'use strict';
// Continuous browser recording with declared UI actions and observed assertions.
const fs = require('node:fs');
const path = require('node:path');
const crypto = require('node:crypto');
const { spawnSync } = require('node:child_process');
const { performance } = require('node:perf_hooks');
const uiPolicy=JSON.parse(fs.readFileSync(path.join(__dirname,'../references/ui-policy.json'),'utf8').replace(/^\uFEFF/,''));
function auditUiText(value){
  return [...uiPolicy.chinese.filter(term=>value.includes(term)),...uiPolicy.english_patterns.filter(pattern=>new RegExp(pattern,'i').test(value))];
}
const sha = data => crypto.createHash('sha256').update(data).digest('hex');
function parseIdentityJson(text) {
  return JSON.parse(text.replace(/^\uFEFF/,''),(key,value,context)=>{
    if(key!=='created_ticks')return value;
    // Use the source token, never a rounded Number, for Python/Windows FILETIME.
    // Missing source support fails closed instead of reconstructing lost digits.
    const exact=typeof value==='number'?context?.source:value;
    if(typeof exact!=='string'||!/^(0|[1-9]\d*)$/.test(exact))throw Error('Process creation ticks require an exact decimal integer');
    return exact;
  });
}
const load = p => parseIdentityJson(fs.readFileSync(p,'utf8'));
const save = (p,v) => fs.writeFileSync(p,JSON.stringify(v,null,2),'utf8');
const pause = (ms,signal) => new Promise((resolve,reject)=>{
  const finish=()=>{signal?.removeEventListener('abort',abort);resolve();};
  const timer=setTimeout(finish,ms),abort=()=>{clearTimeout(timer);signal?.removeEventListener('abort',abort);reject(Error('Recording runtime timeout exceeded before flow completion'));};
  signal?.addEventListener('abort',abort,{once:true});if(signal?.aborted)abort();
});
const LEGACY_POLICY='legacy-fixed-v1',FLOW_POLICY='flow-complete-v1';
function policyVersion(value=LEGACY_POLICY) {
  if(![LEGACY_POLICY,FLOW_POLICY].includes(value))throw Error('Unknown recording policy');
  return value;
}
function boundPolicy(plan,run) {
  const frozen=policyVersion(run.recording_policy_version),declared=policyVersion(plan.recording_policy_version);
  if(frozen!==declared)throw Error('Recording policy differs from frozen run');
  return frozen;
}
function validateMeasuredDuration(proof,runPolicy) {
  const version=policyVersion(proof.recording_policy_version);
  if(runPolicy!==undefined&&version!==policyVersion(runPolicy))throw Error('Recording policy differs from frozen run');
  const seconds=proof.duration;
  if(!Number.isFinite(seconds)||(version===LEGACY_POLICY?(seconds<55||seconds>75):seconds<=60))throw Error('Video duration violates frozen recording policy');
  if(version===FLOW_POLICY) {
    const end=proof.final_result_completion,events=proof.events??[];
    if(!Number.isFinite(proof.estimated_duration_seconds)||proof.estimated_duration_seconds<=60||
       !Number.isFinite(proof.timeout_seconds)||proof.timeout_seconds<=proof.estimated_duration_seconds||seconds>proof.timeout_seconds+.12||
       !Number.isInteger(proof.planned_step_count)||proof.planned_step_count<6||proof.completed_step_count!==proof.planned_step_count||events.length!==proof.completed_step_count||new Set(events.map(e=>e.action)).size<3||
       !end?.completed||!end.selector||!Number.isFinite(end.observed_at)||!Number.isFinite(end.completed_at)||
       end.observed_at<(events.at(-1)?.reading_completed??events.at(-1)?.completed??Infinity)||end.completed_at<end.observed_at||
       end.completed_at>seconds+.12||end.completed_at<seconds-.12||
       !Number.isFinite(end.reading_seconds)||end.reading_seconds<=0||end.completed_at-end.observed_at<end.reading_seconds-.12||
       typeof end.reading_reason!=='string'||!end.reading_reason.trim())throw Error('Completed operations and final business result reading evidence required');
    let last=0;
    for(const event of events) {
      if(!Number.isFinite(event.started)||!Number.isFinite(event.completed)||event.started<last||event.completed<event.started||event.completed>seconds+.12)throw Error('Operation timing falls outside continuous capture');
      last=event.completed;
      if(event.reading_seconds) {
        if(!Number.isFinite(event.reading_seconds)||event.reading_seconds<=0||!Number.isFinite(event.reading_started)||!Number.isFinite(event.reading_completed)||event.reading_started<event.completed||event.reading_completed-event.reading_started<event.reading_seconds-.12||event.reading_completed>seconds+.12||typeof event.reading_reason!=='string'||!event.reading_reason.trim())throw Error('Meaningful observed operation reading evidence required');
        last=event.reading_completed;
      }
    }
  }
  return seconds;
}
function reading(value,required=false) {
  const seconds=value.reading_seconds??0;
  if(!Number.isFinite(seconds)||seconds<0||(required&&seconds<=0)||
     (seconds>0&&(typeof value.reading_reason!=='string'||!value.reading_reason.trim())))throw Error('Meaningful result reading duration and reason required');
  return seconds;
}

function relativeInput(value) {
  if(typeof value!=='string'||!value.trim()||path.isAbsolute(value)||path.win32.isAbsolute(value)||
     path.posix.isAbsolute(value)||value.includes(':')||value.split(/[\\/]/).includes('..')) throw Error('Unsafe relative input');
  return value;
}
function safeFile(root, relative) {
  relativeInput(relative);
  const full=path.resolve(root,relative), realRoot=fs.realpathSync(root), real=fs.realpathSync(full);
  if(!real.startsWith(realRoot+path.sep) || !fs.statSync(real).isFile()) throw Error('Input outside workspace');
  for(let p=full; p!==path.dirname(p);p=path.dirname(p)) if(fs.lstatSync(p).isSymbolicLink()) throw Error('Linked input rejected');
  return full;
}
function localUrl(value) {
  const u=new URL(value);
  return ['http:','https:'].includes(u.protocol) && ['127.0.0.1','localhost','[::1]'].includes(u.hostname) && !u.username && !u.password;
}
function validatePlan(plan) {
  if(!localUrl(plan.url)) throw Error('Recording URL must be local');
  if(typeof plan.health_path!=='string'||!plan.health_path.startsWith('/')||plan.health_path.startsWith('//')||!plan.version) throw Error('Health path and frozen service version required');
  if(!plan.ready || !Array.isArray(plan.steps) || plan.steps.length<6) throw Error('Ready selector and at least six actions required');
  const flexible=policyVersion(plan.recording_policy_version)===FLOW_POLICY;
  const duration=flexible?plan.estimated_duration_seconds:(plan.duration_seconds ?? 60);
  if(flexible) {
    if('duration_seconds' in plan||!Number.isFinite(duration)||duration<=60)throw Error('Flow recording needs a one-minute-plus estimate, not a fixed duration');
    if(!Number.isFinite(plan.timeout_seconds)||plan.timeout_seconds<=duration)throw Error('Runtime timeout must be separate and exceed the estimate');
    if(!plan.final_result?.selector)throw Error('Final business result selector required');
    reading(plan.final_result,true);
  } else if(duration<55 || duration>75) throw Error('Legacy duration must be 55–75 seconds');
  if(!Array.isArray(plan.input_files) || !plan.input_files.length || new Set(plan.input_files).size!==plan.input_files.length) throw Error('Unique immutable input files required');
  for(const input of plan.input_files)relativeInput(input);
  if('storage_state' in plan)relativeInput(plan.storage_state);
  const actions=new Set(['click','fill','select','press','download']);let last=0;
  for(const step of plan.steps) {
    if(flexible) {
      if(step.at!==undefined&&(!Number.isFinite(step.at)||step.at<last||step.at<0))throw Error('Invalid estimated action timeline');
      reading(step);
    } else if(!Number.isFinite(step.at) || step.at<last || step.at<0 || step.at>=duration-1 || step.at-last>15) throw Error('Invalid or idle action timeline');
    if(!actions.has(step.action) || !step.selector || !step.expect) throw Error('Unsupported action or missing observed assertion');
    if(['fill','select','press'].includes(step.action) && typeof step.value!=='string') throw Error('Action value must be a string');
    if(step.at!==undefined)last=step.at;
  }
  if((!flexible&&duration-last>10) || new Set(plan.steps.map(s=>s.action)).size<3) throw Error('Need varied real operations; legacy timeline must reach the final ten seconds');
  return duration;
}
async function executeTimeline(plan,perform,observeFinal,{now,wait=pause}={}) {
  const flexible=policyVersion(plan.recording_policy_version)===FLOW_POLICY;
  let timer,aborted=false;const controller=new AbortController();
  const cancel=new Promise((_,reject)=>{
    if(flexible)timer=setTimeout(()=>{aborted=true;controller.abort();reject(Error('Recording runtime timeout exceeded before flow completion'));},Math.max(0,plan.timeout_seconds-now())*1000);
  });
  const check=()=>{if(aborted||(flexible&&now()>plan.timeout_seconds))throw Error('Recording runtime timeout exceeded before flow completion');};
  const sleep=async seconds=>{check();await Promise.race([wait(seconds*1000,controller.signal),cancel]);check();};
  try {
    for(let i=0;i<plan.steps.length;i++) {
      check();const step=plan.steps[i];
      if(!flexible) {
        const remaining=step.at-now();if(remaining>0)await sleep(remaining);
        if(now()-step.at>5)throw Error('Action schedule overran by more than five seconds');
      }
      const event=await Promise.race([perform(step,i),cancel]);check();
      if(flexible&&reading(step)>0) {
        event.reading_started=now();event.reading_seconds=step.reading_seconds;event.reading_reason=step.reading_reason;
        await sleep(step.reading_seconds);event.reading_completed=now();
      }
    }
    if(!flexible) {
      const remaining=(plan.duration_seconds??60)-now();if(remaining<0)throw Error('Actual actions exceed legacy recording duration');
      await sleep(remaining);return {duration:plan.duration_seconds??60};
    }
    check();await Promise.race([observeFinal(plan.final_result),cancel]);check();
    const observed_at=now();await sleep(plan.final_result.reading_seconds);
    await Promise.race([observeFinal(plan.final_result),cancel]);check();
    const completed_at=now();
    if(completed_at<=60)throw Error('Complete meaningful flow is shorter than one-minute-plus; revise the flow, never pad the capture');
    return {duration:completed_at,final_result_completion:{...plan.final_result,observed_at,completed_at,completed:true}};
  } finally {if(timer)clearTimeout(timer);}
}
function commandFailure(exe,args,result) {
  const secrets=[];
  const sensitive=/^(?:--?)?(?:password|passwd|token|access[-_]?token|refresh[-_]?token|api[-_]?key|secret|authorization|cookie|credential|media[-_]?token|record[-_]?token|lease)(?:=|$)/i;
  for(let i=0;i<args.length;i++) {
    const arg=String(args[i]);
    if(sensitive.test(arg))secrets.push(arg.includes('=')?arg.slice(arg.indexOf('=')+1):String(args[i+1]??''));
    if(/^(?:https?|ftp):\/\//i.test(arg))secrets.push(arg);
    if(arg.startsWith('{')||arg.startsWith('['))secrets.push(arg);
    // A tool may echo a positional credential or full input path on failure.
    if(arg.length>=6&&!arg.startsWith('-'))secrets.push(arg);
  }
  function tail(value) {
    let text=String(value??'');
    for(const secret of secrets.filter(Boolean).sort((a,b)=>b.length-a.length))text=text.split(secret).join('[REDACTED]');
    text=text.replace(/\b(?:https?|ftp):\/\/[^\s"'<>]+/gi,'[URL REDACTED]')
      .replace(/\bBearer\s+\S+/gi,'Bearer [REDACTED]')
      .replace(/((?:password|passwd|token|api[-_]?key|secret|authorization|cookie|credential)["']?\s*[=:]\s*["']?)[^\s,;"'}]+/gi,'$1[REDACTED]')
      .replace(/((?:password|passwd|token|api[-_]?key|secret|authorization|cookie|credential)\s*[=:]\s*)[^\s,;]+/gi,'$1[REDACTED]')
      .replace(/[\u0000-\u0008\u000b\u000c\u000e-\u001f\u007f]/g,'');
    return text.slice(-1200)||'(empty)';
  }
  const tool=path.win32.basename(path.basename(String(exe))).replace(/[^\w. -]/g,'_').slice(-100);
  return 'Media tool failed: '+tool+'; exit='+String(result.status??'none')+'; signal='+String(result.signal??'none')+
    (result.error?'; error='+tail(result.error.code||result.error.message):'')+
    '; stdout tail: '+tail(result.stdout)+'; stderr tail: '+tail(result.stderr);
}
function command(exe,args,runner=spawnSync) {
  const result=runner(exe,args,{encoding:'utf8',windowsHide:true,maxBuffer:16*1024*1024});
  if(result.error || result.status!==0) throw Error(commandFailure(exe,args,result));
  return result.stdout;
}
function batchBinding(workspace) {
  const file=path.join(workspace,'.product-v2/batch-binding.json');
  if(!fs.existsSync(file))return null;
  const binding=load(file),manifestPath=path.join(binding.root,binding.batch_id,'manifest.json');
  const manifest=load(manifestPath),registered=manifest.cases.find(c=>c.case_id===binding.case_id);
  if(binding.contract!=='windows-job-v1'||manifest.media_lease_contract!=='windows-job-v1'||
    sha(fs.readFileSync(manifestPath))!==binding.manifest_sha256||!registered||
    fs.realpathSync(registered.workspace).toLowerCase()!==fs.realpathSync(workspace).toLowerCase())throw Error('Frozen batch/workspace media binding changed');
  return binding;
}
function validateBatchPhase(workspace,phase,lease) {
  if(lease&&phase==='full')throw Error('Batch media leases require capture or evidence phase');
  leaseArgs(lease,workspace,phase);
  const binding=batchBinding(workspace);
  if(binding&&(!lease||phase==='full'))throw Error('Registered batch workspace requires its capture/evidence lease');
  if(binding&&(fs.realpathSync(lease.root).toLowerCase()!==fs.realpathSync(binding.root).toLowerCase()||
     lease.batchId!==binding.batch_id||lease.caseId!==binding.case_id))throw Error('Lease differs from frozen workspace binding');
  return binding;
}
function leaseArgs(lease,workspace,phase='capture',runtimePid=null) {
  if(!lease) return null;
  if(!lease.root||!lease.batchId||!lease.caseId||!lease.token||!Number.isInteger(lease.ownerPid)||lease.ownerPid<1) throw Error('Complete batch media lease required');
  if(!['capture','evidence'].includes(phase))throw Error('Batch media leases require capture or evidence phase');
  const args=[path.join(__dirname,'batch_control.py'),phase==='evidence'?'verify-evidence':'verify-record','--root',lease.root,'--batch-id',lease.batchId,
    '--case-id',lease.caseId,'--pid',String(lease.ownerPid),'--token',lease.token,'--value',workspace];
  if(runtimePid!==null)args.push('--runtime-pid',String(runtimePid));return args;
}
function verifyLease(lease,workspace,phase='capture',runtimePid=null) {
  const args=leaseArgs(lease,workspace,phase,runtimePid);if(!args)return null;
  const result=parseIdentityJson(command(process.env.SCB_PRO_PYTHON,args));
  if(!result.acquired)throw Error('Recording launch admission failed: '+result.reason);
  return result;
}
function isolatedBrowserOptions(tempRoot,downloads) {
  return {headless:true,downloadsPath:downloads,env:{...process.env,TEMP:tempRoot,TMP:tempRoot,TMPDIR:tempRoot}};
}
async function movePointer(page,mouse,point,remaining=()=>{}) {
  const start={...mouse},begin=performance.now();
  while(Math.hypot(point.x-mouse.x,point.y-mouse.y)>.01) {
    remaining();const t=Math.min(1,(performance.now()-begin)/650),u=t*t*(3-2*t);
    const dx=start.x+(point.x-start.x)*u-mouse.x,dy=start.y+(point.y-start.y)*u-mouse.y;
    // Bound each actual move even if a browser call or event-loop turn stalls.
    const scale=Math.min(1,64/Math.hypot(dx,dy)),next={x:mouse.x+dx*scale,y:mouse.y+dy*scale};
    await page.mouse.move(next.x,next.y);Object.assign(mouse,next);
    if(Math.hypot(point.x-mouse.x,point.y-mouse.y)>.01)await pause(16);
  }
  await page.mouse.move(point.x,point.y);Object.assign(mouse,point);
}
async function withActionableTarget(page,locator,mouse,perform,{timeout=10000,editable=false}={}) {
  const deadline=performance.now()+timeout;
  const remaining=()=>{const ms=Math.ceil(deadline-performance.now());if(ms<=0)throw Error('Action target timeout: '+reason);return ms;};
  let reason='target did not become interactive';
  while(true) {
    let target,ready=false;
    try {
      target=await locator.elementHandle({timeout:remaining()});
      // State/scroll APIs do not move the pointer. A trial click does move it in
      // Playwright 1.62, so actual endpoint receipt is checked by pure hit-test.
      const waitStates=async()=>{
        await target.waitForElementState('visible',{timeout:remaining()});
        await target.waitForElementState('stable',{timeout:remaining()});
        await target.waitForElementState('enabled',{timeout:remaining()});
        if(editable)await target.waitForElementState('editable',{timeout:remaining()});
      };
      await waitStates();await target.scrollIntoViewIfNeeded({timeout:remaining()});
        const box=await target.boundingBox(),viewport=page.viewportSize()??await page.evaluate(()=>({width:innerWidth,height:innerHeight}));
        if(!box)reason='target has no visible bounds';
        else {
          const left=Math.max(0,box.x),top=Math.max(0,box.y),right=Math.min(viewport.width,box.x+box.width),bottom=Math.min(viewport.height,box.y+box.height);
          if(right<=left||bottom<=top)reason='target remains outside viewport';
          else {
            const point={x:left+(right-left)*.46,y:top+(bottom-top)*.53};
            const checkPoint=()=>locator.evaluate((current,{target,box,point})=>{
              if(current!==target||!target.isConnected)return 'locator target changed during pointer movement';
              const rect=target.getBoundingClientRect();
              if(Math.abs(rect.x-box.x)>1||Math.abs(rect.y-box.y)>1||Math.abs(rect.width-box.width)>1||Math.abs(rect.height-box.height)>1)return 'target bounds changed during pointer movement';
              let hit=target.ownerDocument.elementFromPoint(point.x,point.y);
              while(hit?.shadowRoot){const inner=hit.shadowRoot.elementFromPoint(point.x,point.y);if(!inner||inner===hit)break;hit=inner;}
              for(let node=hit;node;node=node.assignedSlot??node.parentNode??node.host)if(node===target)return '';
              return 'pointer point is intercepted by '+(hit?hit.tagName.toLowerCase()+(hit.id?'#'+hit.id:''):'no element');
            },{target,box,point},{timeout:remaining()});
            reason=await checkPoint();
            if(!reason) {
              if(Math.hypot(point.x-mouse.x,point.y-mouse.y)>1){await movePointer(page,mouse,point,remaining);await pause(130);}
              // Hover may change state, overlay, layout or the original node.
              await waitStates();reason=await checkPoint();
            }
            if(!reason) {
              remaining();ready=true;
              // Never retry after real input: a partially completed operation
              // must fail rather than submit or download a second time.
              return await perform(target,point);
            }
          }
        }
    } catch(error) {
      if(!ready&&error.name==='TimeoutError'&&reason!=='target did not become interactive')throw Error('Action target timeout: '+reason+'; '+error.message,{cause:error});
      if(ready||!/not attached|detached|resolved to null/i.test(String(error)))throw error;
      reason='target detached during pointer preparation';
    } finally {if(target)await target.dispose().catch(()=>{});}
    await pause(Math.min(50,remaining()));
  }
}
async function performRecordedAction(page,step,mouse,{requestGuard,dir,index,timeout=10000}={}) {
  try {
    return await withActionableTarget(page,page.locator(step.selector),mouse,async(target,point)=>{
      if(step.action==='click')await page.mouse.click(point.x,point.y,{delay:85});
      if(step.action==='fill') {
        await page.mouse.click(point.x,point.y,{delay:65});
        if(!await target.evaluate(element=>element.matches(':focus')))throw Error('Real pointer click did not focus the editable target');
        await target.press('ControlOrMeta+A');await target.type(step.value,{delay:110});
      }
      if(step.action==='select')await target.selectOption(step.value,{timeout});
      if(step.action==='press')await target.press(step.value,{timeout});
      if(step.action==='download') {
        const attempt=requestGuard.begin();
        try {
          // Promise.all consumes both outcomes, including when mouse input fails.
          const [download]=await Promise.all([page.waitForEvent('download',{timeout:15000}),page.mouse.click(point.x,point.y,{delay:85})]);
          const name=path.basename(download.suggestedFilename()),targetPath=path.join(dir,`download-${index}-${name}`);
          return await requestGuard.save(attempt,download,targetPath);
        } finally {requestGuard.end(attempt);}
      }
    },{timeout,editable:step.action==='fill'});
  } catch(error) {throw Error(`Cannot perform ${step.action} on ${step.selector}: ${error.message}`,{cause:error});}
}
function recordingSetup(workspace,planPath) {
  workspace=fs.realpathSync(workspace);
  const runBytes=fs.readFileSync(path.join(workspace,'.product-v2/run.json')),planBytes=fs.readFileSync(planPath);
  const parse=bytes=>parseIdentityJson(bytes.toString('utf8')),run=parse(runBytes),plan=parse(planBytes);
  const estimatedDuration=validatePlan(plan),recordingPolicy=boundPolicy(plan,run);
  if(typeof run.workspace!=='string'||run.workspace.toLowerCase()!==workspace.toLowerCase()||
     typeof run.run_id!=='string'||!run.run_id.trim())throw Error('Workspace/run identity differs');
  const inputs=Object.fromEntries(plan.input_files.map(rel=>[rel,sha(fs.readFileSync(safeFile(workspace,rel)))]));
  const storageState='storage_state' in plan?safeFile(workspace,plan.storage_state):undefined;
  const storageStateHash=storageState?sha(fs.readFileSync(storageState)):null;
  const constructionChecks='construction_check_policy_version' in run?
    JSON.parse(command(process.env.SCB_PRO_PYTHON,[path.join(__dirname,'proflow.py'),'check-build','--workspace',workspace,'--plan',planPath])):
    {required:false,status:'historical-contract'};
  if('construction_check_policy_version' in run&&(constructionChecks.status!=='ready'||constructionChecks.required!==true))throw Error('Current construction self-check admission required');
  return {workspace,run,plan,estimatedDuration,recordingPolicy,planSha:sha(planBytes),runSha:sha(runBytes),inputs,storageState,storageStateHash,constructionChecks};
}
async function healthIdentity(workspace,run,plan,request=null) {
  const origin=new URL(plan.url),url=new URL(plan.health_path,origin.origin);
  if(url.origin!==origin.origin||!localUrl(url.href))throw Error('Health endpoint must stay on the recording origin');
  const response=request?await request.get(url.href,{maxRedirects:0,timeout:10000}):
    await fetch(url.href,{method:'GET',redirect:'error',signal:AbortSignal.timeout(10000)});
  if(!(request?response.ok():response.ok))throw Error('Health endpoint failed');
  const value=await response.json();
  if(value.run_id!==run.run_id||value.version!==plan.version||String(value.workspace).toLowerCase()!==workspace.toLowerCase()||
     !Number.isInteger(value.pid)||value.pid<1)throw Error('Health endpoint belongs to a different case/version');
  const current=parseIdentityJson(command(process.env.SCB_PRO_PYTHON,[path.join(__dirname,'process_guard.py'),'inspect','--workspace',workspace]));
  const registry=load(path.join(workspace,'.product-v2/processes.json'));
  if(typeof registry.workspace!=='string'||registry.workspace.toLowerCase()!==workspace.toLowerCase())throw Error('Registry workspace identity differs');
  const port=Number(origin.port||(origin.protocol==='https:'?443:80));
  const live=current.owned.find(p=>p.pid===value.pid&&p.ports.includes(port)),saved=registry.processes.find(p=>p.pid===value.pid);
  if(!live||!saved||typeof live.created_ticks!=='string'||! /^[1-9]\d*$/.test(live.created_ticks)||live.created_ticks!==saved.created_ticks||live.command_sha256!==saved.command_sha256)throw Error('No current registered listener identity for this case');
  return {pid:live.pid,created_ticks:live.created_ticks,command_sha256:live.command_sha256,ports:live.ports};
}
async function checkReady(workspace,planPath) {
  const setup=recordingSetup(workspace,planPath),identity=await healthIdentity(setup.workspace,setup.run,setup.plan);
  return {kind:'recording-readiness-check',status:'ready',capture_performed:false,visual_review:'not performed',
    workspace:setup.workspace,run_id:setup.run.run_id,version:setup.plan.version,recording_policy_version:setup.recordingPolicy,
    run_sha256:setup.runSha,plan_sha256:setup.planSha,input_files:setup.inputs,
    storage_state:setup.storageState?{relative_path:setup.plan.storage_state,sha256:setup.storageStateHash}:null,service_identity:identity,
    construction_checks:setup.constructionChecks};
}
function downloadRequestGuard(page) {
  const failures=[],successful=new Map(),ids=new WeakMap();let active=null,serial=0;
  const requestId=request=>{if(!ids.has(request))ids.set(request,++serial);return ids.get(request);};
  const navigation=request=>{try{return request.isNavigationRequest()&&request.frame()===page.mainFrame();}catch{return false;}};
  const verified=proof=>{try{return fs.statSync(proof.path).isFile()&&sha(fs.readFileSync(proof.path))===proof.sha256;}catch{return false;}};
  const audit=()=>failures.map(failure=>{
    const proof=successful.get(failure.request),exempt=failure.error_text==='net::ERR_ABORTED'&&navigation(failure.request)&&proof&&verified(proof);
    return {request_id:requestId(failure.request),url:failure.request.url(),error_text:failure.error_text,
      main_frame_navigation:navigation(failure.request),classification:exempt?'successful_download_navigation_abort':'blocking_request_failure',
      successful_download:proof||null};
  });
  return {
    begin:()=>{if(active)throw Error('Overlapping download attempts');active={requests:new Set()};return active;},
    track:request=>{requestId(request);if(active&&navigation(request))active.requests.add(request);},
    failed:request=>failures.push({request,error_text:request.failure()?.errorText??null}),
    save:async(attempt,download,target)=>{
      if(attempt!==active)throw Error('Download attempt identity differs');
      await download.saveAs(target);if(await download.failure())throw Error('Browser download failed');
      const proof={name:path.basename(download.suggestedFilename()),path:target,sha256:sha(fs.readFileSync(target)),url:download.url(),request_id:null};
      const matching=[...attempt.requests].filter(request=>navigation(request)&&request.url()===download.url());
      if(download.page()===page&&matching.length===1){proof.request_id=requestId(matching[0]);successful.set(matching[0],proof);}
      return proof;
    },
    end:attempt=>{if(attempt!==active)throw Error('Download attempt identity differs');active=null;},
    audit,errors:()=>audit().filter(item=>item.classification==='blocking_request_failure').map(item=>'Request failed '+item.url+(item.error_text?' ('+item.error_text+')':''))
  };
}
async function record(workspace, planPath, phase='full',lease=null) {
  const binding=validateBatchPhase(workspace,phase,lease);
  if(binding)verifyLease(lease,workspace,phase,process.pid);
  workspace=fs.realpathSync(workspace);
  const lock=path.join(workspace,'.product-v2/recording-stage.lock');
  const fd=fs.openSync(lock,'wx');
  fs.writeFileSync(fd,JSON.stringify({pid:process.pid,started:new Date().toISOString(),phase}));fs.closeSync(fd);
  try {return await recordPhase(workspace,planPath,phase,lease);} finally {fs.unlinkSync(lock);}
}
async function recordPhase(workspace, planPath, phase='full',lease=null) {
  if(!['full','capture','evidence'].includes(phase)) throw Error('Unknown recording phase');
  workspace=fs.realpathSync(workspace);
  if(phase==='evidence') return finishRecording(workspace,lease);
  const setup=recordingSetup(workspace,planPath),{run,plan,estimatedDuration,recordingPolicy,planSha,inputs,storageState}=setup;
  let duration=estimatedDuration,finalResultCompletion;
  const final=run.video;
  if(fs.existsSync(final)) throw Error('Final video already exists; preserve it before making a new version');
  const ffmpeg=process.env.SCB_PRO_FFMPEG, ffprobe=process.env.SCB_PRO_FFPROBE;
  if(!ffmpeg || !ffprobe || !process.env.SCB_PRO_PLAYWRIGHT || !process.env.TEMP?.toLowerCase().startsWith('d:\\codex+\\')) throw Error('Load Enter-Environment.ps1 first');
  let identity=await healthIdentity(workspace,run,plan),launchAdmission;
  const {chromium}=require(process.env.SCB_PRO_PLAYWRIGHT);
  const dir=path.join(workspace,'.product-v2','recordings',Date.now()+'-'+crypto.randomUUID());fs.mkdirSync(dir,{recursive:true});
  const browserTemp=path.join(process.env.TEMP,'scb-pro-browser',crypto.randomUUID());fs.mkdirSync(browserTemp,{recursive:true});
  const downloads=path.join(browserTemp,'downloads');fs.mkdirSync(downloads);
  save(path.join(workspace,'.product-v2/capture-pending.json'),{status:'capturing',path:path.join(dir,'capture.json'),sha256:null});
  const errors=[],events=[],texts=[];let browser,context,video,prelude,rawPath,capturedStartUtc,capturedEndUtc,requestGuard,failedStep;
  const rawStart=performance.now();let captureStart=rawStart;
  try {
    launchAdmission=verifyLease(lease,workspace,'capture',batchBinding(workspace)?process.pid:null);
    browser=await chromium.launch(isolatedBrowserOptions(browserTemp,downloads));
    if(storageState&&(safeFile(workspace,plan.storage_state)!==storageState||sha(fs.readFileSync(storageState))!==setup.storageStateHash))throw Error('Storage state changed before recording');
    context=await browser.newContext({viewport:{width:1920,height:1080},recordVideo:{dir,size:{width:1920,height:1080}},acceptDownloads:true,locale:'zh-CN',timezoneId:'Asia/Shanghai',storageState});
    const beforeIdentity=await healthIdentity(workspace,run,plan,context.request);
    if(JSON.stringify(beforeIdentity)!==JSON.stringify(identity))throw Error('Service identity changed before recording');
    const beforePage=performance.now();
    const page=await context.newPage();video=page.video();
    requestGuard=downloadRequestGuard(page);
    page.on('pageerror',err=>errors.push(String(err)));
    page.on('console',msg=>{if(msg.type()==='error') errors.push(msg.text());});
    page.on('response',response=>{if(response.status()>=400) errors.push('HTTP '+response.status()+' '+response.url());});
    page.on('request',requestGuard.track);
    page.on('requestfailed',requestGuard.failed);
    await page.goto(plan.url,{waitUntil:'networkidle',timeout:30000});
    await page.locator(plan.ready).waitFor({state:'visible',timeout:15000});
    // Cursor overlay follows real pointer events; it cannot change application state.
    await page.evaluate(()=>{const pointer=document.createElement('div');pointer.id='operation-pointer';pointer.setAttribute('aria-hidden','true');pointer.style.cssText='position:fixed;left:0;top:0;width:18px;height:24px;z-index:2147483647;pointer-events:none;filter:drop-shadow(1px 2px 2px #5558);clip-path:polygon(0 0,0 92%,25% 70%,43% 100%,59% 91%,41% 61%,78% 61%);background:#162438;border:1px solid white;';document.body.append(pointer);document.addEventListener('mousemove',event=>{pointer.style.left=event.clientX+'px';pointer.style.top=event.clientY+'px';});});
    const mouse={x:930,y:550};await page.mouse.move(mouse.x,mouse.y);
    await pause(1000);
    captureStart=performance.now();capturedStartUtc=new Date().toISOString();prelude=(captureStart-beforePage)/1000;
    await page.evaluate(()=>{
      window.__scbTiming={intervals:[],last:0};
      const tick=t=>{const v=window.__scbTiming;if(!v)return;if(v.last)v.intervals.push(t-v.last);v.last=t;requestAnimationFrame(tick);};requestAnimationFrame(tick);
    });
    async function observe(label) {
      if(!localUrl(page.url())) throw Error('Navigation left local application');
      const text=await page.locator('body').innerText();
      const hits=auditUiText(text);
      if(hits.length) throw Error('Visible restricted words: '+hits.join(', '));
      if(await page.locator('math,.katex,.MathJax').count()) throw Error('Visible mathematical rendering is outside the UI brief');
      const screenshot=path.join(dir,label+'.png');await page.screenshot({path:screenshot});
      const latin=(text.match(/[A-Za-z]{3,}/g)||[]).length;
      texts.push({label,url:page.url(),text,english_tokens:latin,screenshot,sha256:sha(fs.readFileSync(screenshot))});
      return screenshot;
    }
    await observe('start');
    const flow=await executeTimeline(plan,async (step,i)=>{
      const started=(performance.now()-captureStart)/1000;
      try {
      const downloadProof=await performRecordedAction(page,step,mouse,{requestGuard,dir,index:i});
      const expected=page.locator(step.expect);await expected.waitFor({state:'visible',timeout:10000});
      if(step.text) await page.waitForFunction(({selector,text})=>document.querySelector(selector)?.innerText.includes(text),{selector:step.expect,text:step.text},{timeout:10000});
      const event={index:i,action:step.action,scheduled:step.at,started,completed:(performance.now()-captureStart)/1000,screenshot:await observe('step-'+String(i+1).padStart(2,'0')),download:downloadProof};
      events.push(event);return event;
      } catch(error) {
        const screenshot=path.join(dir,'failed-step-'+String(i+1).padStart(2,'0')+'.png');
        failedStep={index:i,action:step.action,selector:step.selector,expect:step.expect,started,failed_at:(performance.now()-captureStart)/1000,error:String(error)};
        try {await page.screenshot({path:screenshot});failedStep.screenshot=screenshot;failedStep.sha256=sha(fs.readFileSync(screenshot));}catch{}
        errors.push(String(error));throw error;
      }
    },async result=>{
      await page.locator(result.selector).waitFor({state:'visible',timeout:10000});
      if(result.text)await page.waitForFunction(({selector,text})=>document.querySelector(selector)?.innerText.includes(text),{selector:result.selector,text:result.text},{timeout:10000});
    },{now:()=>(performance.now()-captureStart)/1000});
    duration=flow.duration;finalResultCompletion=flow.final_result_completion;
    capturedEndUtc=new Date().toISOString();await observe('end');
    const timing=await page.evaluate(()=>{const v=window.__scbTiming;delete window.__scbTiming;return v;});
    save(path.join(dir,'browser-timing.json'),{note:'Main thread animation timing supplements encoded source timestamps; it does not measure every captured compositor frame.',...timing});
    // A short recorded tail prevents requesting frames beyond the source end.
    await pause(750);
    const afterIdentity=await healthIdentity(workspace,run,plan,context.request);
    if(JSON.stringify(afterIdentity)!==JSON.stringify(identity)) throw Error('Service identity changed during recording');
    await context.close();context=null;rawPath=await video.path();
  } finally {
    if(context) await context.close().catch(()=>{});
    if(browser) await browser.close().catch(()=>{});
    if(video&&!rawPath)rawPath=await video.path().catch(()=>undefined);
    if(requestGuard)errors.push(...requestGuard.errors());
    save(path.join(dir,'observed.json'),{events,texts,errors,failed_step:failedStep,request_failures:requestGuard?.audit()??[],input_files:inputs,prelude_seconds:prelude,raw_video:rawPath,browser_temp:browserTemp,launch_admission:launchAdmission,captured_start_utc:capturedStartUtc,captured_end_utc:capturedEndUtc,
      recording_policy_version:recordingPolicy,plan_sha256:planSha,estimated_duration_seconds:estimatedDuration,timeout_seconds:plan.timeout_seconds,final_result_completion:finalResultCompletion});
  }
  if(errors.length) throw Error('Browser errors: '+errors.join('; ').slice(0,1600));
  for(const [rel,hash] of Object.entries(inputs)) if(sha(fs.readFileSync(safeFile(workspace,rel)))!==hash) throw Error('Application input changed: '+rel);
  if(sha(fs.readFileSync(planPath))!==planSha)throw Error('Recording plan changed during capture');
  const capture={schema_version:1,status:'captured',passed:false,workspace,run_id:run.run_id,final,dir,rawPath,raw_sha256:sha(fs.readFileSync(rawPath)),prelude,duration,inputs,identity,events,texts,errors,request_failures:requestGuard?.audit()??[],downloads,browser_temp:browserTemp,launch_admission:launchAdmission,captured_start_utc:capturedStartUtc,captured_end_utc:capturedEndUtc,construction_checks:setup.constructionChecks,plan_path:planPath,
    recording_policy_version:recordingPolicy,plan_sha256:planSha,estimated_duration_seconds:estimatedDuration,timeout_seconds:plan.timeout_seconds,planned_step_count:plan.steps.length,completed_step_count:events.length,final_result_completion:finalResultCompletion};
  save(path.join(dir,'capture.json'),capture);
  save(path.join(workspace,'.product-v2/capture-pending.json'),{path:path.join(dir,'capture.json'),sha256:sha(fs.readFileSync(path.join(dir,'capture.json')))});
  if(phase==='capture') return {status:'captured',visual_review_required:true,evidence_pending:true,capture:path.join(dir,'capture.json'),raw_video:rawPath,operations:events.length};
  return finishRecording(workspace);
}
function finishRecording(workspace,lease=null) {
  const binding=validateBatchPhase(workspace,'evidence',lease);
  if(binding)verifyLease(lease,workspace,'evidence',process.pid);
  const pending=load(path.join(workspace,'.product-v2/capture-pending.json'));
  const capturePath=safeFile(workspace,path.relative(workspace,pending.path));
  if(sha(fs.readFileSync(capturePath))!==pending.sha256) throw Error('Capture receipt changed');
  const c=load(capturePath),run=load(path.join(workspace,'.product-v2/run.json'));
  if(!fs.existsSync(c.final)&&'construction_check_policy_version' in run){
    const current=JSON.parse(command(process.env.SCB_PRO_PYTHON,[path.join(__dirname,'proflow.py'),'check-build','--workspace',workspace,
      ...(c.plan_path?['--plan',c.plan_path]:[])]));
    if(current.status!=='ready'||current.required!==true||c.construction_checks?.status!=='ready'||c.construction_checks?.run_id!==run.run_id)throw Error('Current construction admission required before evidence');
  }
  const {final,dir,rawPath,prelude,duration,inputs,identity,events,texts}=c;
  if(c.status!=='captured'||c.workspace!==workspace||c.run_id!==run.run_id||final!==run.video||c.errors.length) throw Error('Capture belongs to a different or failed run');
  if('construction_check_policy_version' in run&&(c.construction_checks?.status!=='ready'||c.construction_checks?.run_id!==run.run_id))throw Error('Original construction admission required');
  const checksPath=path.join(workspace,'.product-v2/build-checks.json');
  if(fs.existsSync(final)&&fs.existsSync(checksPath)&&load(checksPath).video_material_change)throw Error('Video requires replacement for recorded major system/operation change');
  if(sha(fs.readFileSync(safeFile(workspace,path.relative(workspace,rawPath))))!==c.raw_sha256) throw Error('Original capture changed');
  // Completed videos keep their original evidence. Later code/data edits are
  // checked by current software gates; unfinished captures still bind inputs.
  if(!fs.existsSync(final))for(const [rel,hash] of Object.entries(inputs)) if(sha(fs.readFileSync(safeFile(workspace,rel)))!==hash) throw Error('Application input changed: '+rel);
  validateMeasuredDuration(c,policyVersion(run.recording_policy_version));
  const ffmpeg=process.env.SCB_PRO_FFMPEG,ffprobe=process.env.SCB_PRO_FFPROBE;
  if(!ffmpeg||!ffprobe||!process.env.SCB_PRO_PYTHON) throw Error('Load Enter-Environment.ps1 first');
  const existingReceipt=path.join(workspace,'.product-v2/recording.json');
  if(fs.existsSync(final)) {
    const prior=fs.existsSync(existingReceipt)?load(existingReceipt):{};
    if(prior.capture_receipt_sha256!==pending.sha256||prior.sha256!==sha(fs.readFileSync(final))) throw Error('Unrelated final video exists');
    // A completed technical timeline is reusable only when its receipt, video
    // and every frame still bind the same capture. Validation never approves
    // visuals; the current independent review remains a separate gate.
    const controlled=path.join(workspace,'.product-v2/controlled-video.json');
    if(fs.existsSync(controlled)) {
      const priorEvidence=load(controlled);
      if(priorEvidence.timeline&&fs.existsSync(priorEvidence.timeline)&&sha(fs.readFileSync(priorEvidence.timeline))===priorEvidence.sha256) {
        try {
          validateMeasuredDuration(prior,policyVersion(run.recording_policy_version));
          if(prior.width!==1920||prior.height!==1080)throw Error('Existing recording geometry differs');
          JSON.parse(command(process.env.SCB_PRO_PYTHON,[path.join(__dirname,'media_evidence.py'),'validate','--workspace',workspace,'--video',final,'--recording',existingReceipt,'--timeline',priorEvidence.timeline]));
          return {video:final,duration:prior.duration,operations:prior.events.length,frames:prior.frames,controlled_video_evidence:priorEvidence,reused_existing_evidence:true,visual_review_required:true};
        } catch { /* Changed/failed technical evidence gets a new directory. */ }
      }
    }
  }
  const staged=path.join(dir,'final.mp4');
  if(!fs.existsSync(final)) command(ffmpeg,['-y','-hide_banner','-loglevel','error','-threads','2','-filter_threads','2','-ss',String(prelude),'-i',rawPath,'-t',String(duration),'-an','-c:v','libx264','-threads','2','-preset','fast','-crf','20','-pix_fmt','yuv420p','-movflags','+faststart',staged]);
  const encoded=fs.existsSync(final)?final:staged;
  const metadata=JSON.parse(command(ffprobe,['-v','error','-show_entries','format=duration:stream=width,height,codec_name','-of','json',encoded]));
  const seconds=Number(metadata.format.duration),stream=metadata.streams[0];
  validateMeasuredDuration({...c,duration:seconds},policyVersion(run.recording_policy_version));
  if(stream.width!==1920||stream.height!==1080) throw Error('Video geometry check failed');
  fs.mkdirSync(path.dirname(final),{recursive:true});if(!fs.existsSync(final)) fs.copyFileSync(staged,final,fs.constants.COPYFILE_EXCL);
  const evidenceDir=path.join(dir,'controlled-video-'+crypto.randomUUID()),frames=path.join(evidenceDir,'frames');
  const report={passed:true,duration:seconds,width:1920,height:1080,sha256:sha(fs.readFileSync(final)),video:final,raw_video:rawPath,prelude_seconds:prelude,input_files:inputs,service_identity:identity,events,texts,frames,visual_review_required:true,capture_receipt_sha256:pending.sha256,encoding_threads:2,construction_checks:c.construction_checks,plan_path:c.plan_path,
    recording_policy_version:policyVersion(c.recording_policy_version),plan_sha256:c.plan_sha256,estimated_duration_seconds:c.estimated_duration_seconds,timeout_seconds:c.timeout_seconds,planned_step_count:c.planned_step_count,completed_step_count:c.completed_step_count,final_result_completion:c.final_result_completion};
  save(path.join(workspace,'.product-v2/recording.json'),report);
  // Fixed evidence wrapper produces the complete sampled timeline, mapped
  // contact sheets and original interaction frames. It never signs a review.
  const mediaArgs=[path.join(__dirname,'media_evidence.py'),'generate','--workspace',workspace,'--video',final,'--recording',path.join(workspace,'.product-v2/recording.json'),'--output',evidenceDir];
  if(binding)mediaArgs.push('--media-token',lease.token,'--owner-pid',String(lease.ownerPid),'--runtime-pid',String(process.pid));
  const media=JSON.parse(command(process.env.SCB_PRO_PYTHON,mediaArgs));
  save(path.join(workspace,'.product-v2/controlled-video.json'),media);
  return {video:final,duration:seconds,operations:events.length,frames,controlled_video_evidence:media};
}
if(require.main===module) {
  const args=process.argv.slice(2),value=name=>args.includes(name)?args[args.indexOf(name)+1]:undefined;
  if(args.includes('--check-ready')) {
    if(!value('--workspace')||!value('--plan')){console.error('Expected --workspace and --plan for --check-ready');process.exitCode=2;}
    else checkReady(value('--workspace'),value('--plan')).then(result=>console.log(JSON.stringify(result))).catch(error=>{console.error(String(error));process.exitCode=2;});
  }
  else if(!args.includes('--workspace')||(!args.includes('--plan')&&value('--phase')!=='evidence')) {console.error('Expected --workspace and --plan (except evidence phase)');process.exitCode=2;}
  else {
    const names=['--batch-root','--batch-id','--case-id','--record-token','--media-token','--owner-pid'];
    const lease=names.some(name=>args.includes(name))?{root:value('--batch-root'),batchId:value('--batch-id'),caseId:value('--case-id'),token:value('--media-token')||value('--record-token'),ownerPid:Number(value('--owner-pid'))}:null;
    const phase=args.includes('--phase')?value('--phase'):'full';
    try{
      const binding=validateBatchPhase(value('--workspace'),phase,lease);
      if(binding&&!process.env.SCB_PRO_MEDIA_JOB){
        // Supervisor assigns the inner Node while suspended, before browser or
        // encoder creation. An environment marker alone never proves membership.
        const result=spawnSync(process.env.SCB_PRO_PYTHON,[path.join(__dirname,'media_job.py'),'--workspace',value('--workspace'),'--phase',phase,'--lease',JSON.stringify(lease),'--',...args],{stdio:'inherit',windowsHide:true});
        if(result.error)throw result.error;process.exitCode=result.status??2;
      }else record(value('--workspace'),value('--plan'),phase,lease).then(result=>console.log(JSON.stringify(result))).catch(error=>{console.error(String(error));process.exitCode=2;});
    }catch(error){console.error(String(error));process.exitCode=2;}
  }
}
module.exports={validatePlan,checkReady,downloadRequestGuard,record,localUrl,auditUiText,finishRecording,leaseArgs,isolatedBrowserOptions,batchBinding,validateBatchPhase,executeTimeline,boundPolicy,validateMeasuredDuration,withActionableTarget,performRecordedAction,movePointer,command,commandFailure};
