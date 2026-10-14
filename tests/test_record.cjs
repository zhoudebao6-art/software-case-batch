const {test}=require('node:test');
const assert=require('node:assert/strict');
const {validatePlan,downloadRequestGuard,localUrl,auditUiText,record,leaseArgs,isolatedBrowserOptions,validateBatchPhase,finishRecording,executeTimeline,boundPolicy,validateMeasuredDuration,performRecordedAction,movePointer}=require('../scripts/record.cjs');
function valid(){return {url:'http://127.0.0.1:8123',ready:'#ready',health_path:'/api/health',version:'v1',input_files:['app.py'],steps:[
  {at:1,action:'fill',value:'x',selector:'#search',expect:'#search'},
  {at:10,action:'click',selector:'#query',expect:'#table'},
  {at:20,action:'click',selector:'#detail',expect:'#panel'},
  {at:30,action:'select',value:'x',selector:'#status',expect:'#status'},
  {at:40,action:'click',selector:'#save',expect:'#saved'},
  {at:53,action:'download',selector:'#download',expect:'#saved'}]};}
function pointerFixture({blocked=false,clickError=false,downloadError=false}={}) {
 const counts={states:[],moves:0,clicks:0,disposed:0,waiters:0,begun:0,ended:0};
 const target={click:async()=>{throw Error('Pointer-moving trial is forbidden during preparation');},
  waitForElementState:async(state,options)=>{assert.ok(options.timeout>0);counts.states.push(state);if(blocked)throw Error('toast intercepts pointer events');},scrollIntoViewIfNeeded:async()=>{},
  boundingBox:async()=>({x:90,y:90,width:100,height:40}),dispose:async()=>{counts.disposed++;}};
 const page={locator:()=>({elementHandle:async()=>target,evaluate:async()=>''}),viewportSize:()=>({width:1280,height:720}),
  mouse:{move:async()=>{counts.moves++;},click:async()=>{counts.clicks++;if(clickError)throw Error('Real mouse input failed');}},
  waitForEvent:()=>{counts.waiters++;return new Promise((resolve,reject)=>setTimeout(()=>downloadError?reject(Error('No download event')):resolve({}),20));}};
 const requestGuard={begin:()=>{counts.begun++;return 'attempt';},end:()=>{counts.ended++;},save:()=>{throw Error('Failed input cannot prove a download');}};
 return {page,counts,requestGuard,mouse:{x:10,y:10}};
}
test('actionability rejection reports the target and prevents input or download listeners',async()=>{
 for(const action of ['click','fill','download','select','press']) {
  const f=pointerFixture({blocked:true});
  await assert.rejects(performRecordedAction(f.page,{action,selector:'#under-toast',value:'x'},f.mouse,{requestGuard:f.requestGuard}),new RegExp('Cannot perform '+action+' on #under-toast: toast intercepts pointer events'));
  assert.equal(f.counts.clicks,0);assert.equal(f.counts.waiters,0);assert.equal(f.counts.begun,0);assert.equal(f.counts.disposed,1);
 }
});
test('a real mouse input failure is never retried as a second business action',async()=>{
 const f=pointerFixture({clickError:true});
 await assert.rejects(performRecordedAction(f.page,{action:'click',selector:'#submit'},f.mouse),/Cannot perform click on #submit: Real mouse input failed/);
 assert.equal(f.counts.clicks,1);assert.deepEqual(f.counts.states,['visible','stable','enabled','visible','stable','enabled']);assert.ok(f.counts.moves>10);assert.equal(f.counts.disposed,1);
});
test('first and reverse pointer paths bound each move and retain timing even after a stalled browser call',async()=>{
 const mouse={x:930,y:550},trace=[{...mouse,at:performance.now()}];let stalled=false;
 const page={mouse:{move:async(x,y)=>{
  if(!stalled&&Math.hypot(x-trace.at(-1).x,y-trace.at(-1).y)>1){stalled=true;await new Promise(resolve=>setTimeout(resolve,140));}
  trace.push({x,y,at:performance.now()});
 }}};
 for(const point of [{x:173.6,y:123.85},{x:1800,y:940}]) {
  const begin=trace.length-1,origin={...mouse},started=performance.now();await movePointer(page,mouse,point);
  assert.ok(performance.now()-started>=630);assert.deepEqual(mouse,point);
  for(let i=begin+1;i<trace.length;i++) {
   const prev=trace[i-1],next=trace[i],distance=Math.hypot(next.x-prev.x,next.y-prev.y);
   assert.ok(Number.isFinite(distance)&&distance<=64.000001,'native move must not jump to trial center or stale start');
   assert.ok(next.at>=prev.at);if(distance>1)assert.ok(next.at-prev.at>=12,'meaningful movement retains paced timing');
   assert.ok((next.x-prev.x)*(point.x-origin.x)>=-.001);assert.ok((next.y-prev.y)*(point.y-origin.y)>=-.001);
  }
 }
 assert.equal(stalled,true);
});
test('failed mouse download consumes a later event rejection and ends its single guard attempt',async()=>{
 const f=pointerFixture({clickError:true,downloadError:true}),unhandled=[];const listener=error=>unhandled.push(error);process.on('unhandledRejection',listener);
 try {
  await assert.rejects(performRecordedAction(f.page,{action:'download',selector:'#export'},f.mouse,{requestGuard:f.requestGuard}),/Real mouse input failed/);
  await new Promise(resolve=>setTimeout(resolve,50));assert.deepEqual(unhandled,[]);
  assert.equal(f.counts.clicks,1);assert.equal(f.counts.waiters,1);assert.equal(f.counts.begun,1);assert.equal(f.counts.ended,1);
 } finally {process.removeListener('unhandledRejection',listener);}
});
test('default is a minute',()=>assert.equal(validatePlan(valid()),60));
test('path preflight accepts workspace relative declarations without resolving files and storage state may be omitted',()=>{
 for(const factory of [valid,flexible]){
  const plan=factory(),duration=plan.estimated_duration_seconds??60;
  plan.input_files=['app.py','web/assets/chart.v2.js','配置/当前 参数.json',String.raw`web\app.js`];
  assert.equal(validatePlan(plan),duration);
  plan.storage_state='.product-v2/browser-state.json';assert.equal(validatePlan(plan),duration);
  plan.storage_state=String.raw`.product-v2\browser-state.json`;assert.equal(validatePlan(plan),duration);
 }
});
test('path preflight rejects actual invalid declarations in every input and optional storage state',()=>{
 const invalid=[String.raw`D:\case\.product-v2\browser-state.json`,'D:/case/browser-state.json','D:browser-state.json',
  '/tmp/browser-state.json',String.raw`\\server\share\browser-state.json`,String.raw`\browser-state.json`,
  '../browser-state.json','nested/../browser-state.json',String.raw`nested\..\browser-state.json`,
  'state.json:stream','', ' \t',null,undefined,17,{},[]];
 for(const factory of [valid,flexible])for(const value of invalid){
  for(const input_files of [[value],['app.py',value]])assert.throws(()=>validatePlan({...factory(),input_files}),/Unsafe relative input/);
  assert.throws(()=>validatePlan({...factory(),storage_state:value}),/Unsafe relative input/);
 }
});
test('capture rejects invalid declared paths before Playwright load or browser launch and releases its lock',async()=>{
 const fs=require('node:fs'),path=require('node:path'),os=require('node:os'),vm=require('node:vm');
 const root=fs.mkdtempSync(path.join(os.tmpdir(),'scb-path-preflight-'));fs.mkdirSync(path.join(root,'.product-v2'));
 const script=path.resolve(__dirname,'../scripts/record.cjs');let browserLoads=0,browserLaunches=0,commands=0;
 const browserRequire=name=>{
  if(name==='fixture-playwright'){
   browserLoads++;return {chromium:{launch:async()=>{browserLaunches++;throw Error('Browser must not launch for invalid declared paths');}}};
  }
  if(name==='node:child_process')return {spawnSync:()=>{commands++;throw Error('No external process is needed for invalid declared paths');}};
  return require(name);
 };
 const sandbox={require:browserRequire,module:{exports:{}},__dirname:path.dirname(script),
  process:{env:{...process.env,SCB_PRO_PLAYWRIGHT:'fixture-playwright',SCB_PRO_FFMPEG:'fixture-encoder',SCB_PRO_FFPROBE:'fixture-probe'},pid:process.pid},
  console,setTimeout,clearTimeout,AbortController,URL};
 vm.runInNewContext(fs.readFileSync(script,'utf8'),sandbox,{filename:script});
 try{
  const run={workspace:root,run_id:'fixture',video:path.join(root,'final.mp4'),recording_policy_version:'flow-complete-v1'};
  fs.writeFileSync(path.join(root,'.product-v2/run.json'),JSON.stringify(run));fs.writeFileSync(path.join(root,'app.py'),'frozen input');
  const state=path.join(root,'.product-v2/browser-state.json');fs.writeFileSync(state,'{}');
  const planPath=path.join(root,'.product-v2/record-plan.json');
  for(const plan of [{...flexible(),storage_state:state},{...flexible(),input_files:['app.py','../outside.py']}]){
   fs.writeFileSync(planPath,JSON.stringify(plan));
   await assert.rejects(sandbox.module.exports.record(root,planPath,'capture'),/Unsafe relative input/);
   assert.equal(browserLoads,0);assert.equal(browserLaunches,0);assert.equal(commands,0);
   for(const name of ['recording-stage.lock','capture-pending.json','recordings'])assert.equal(fs.existsSync(path.join(root,'.product-v2',name)),false);
   assert.equal(fs.existsSync(run.video),false);assert.equal(fs.readFileSync(state,'utf8'),'{}');
  }
 }finally{
  assert.equal(path.dirname(fs.realpathSync(root)),fs.realpathSync(os.tmpdir()));fs.rmSync(root,{recursive:true,force:true});
 }
});
function readinessFixture(){
 const fs=require('node:fs'),path=require('node:path'),os=require('node:os'),vm=require('node:vm'),crypto=require('node:crypto');
 const root=fs.realpathSync(fs.mkdtempSync(path.join(os.tmpdir(),'scb-ready-test-'))),control=path.join(root,'.product-v2');fs.mkdirSync(control);
 const save=(p,value)=>fs.writeFileSync(p,JSON.stringify(value)),hash=p=>crypto.createHash('sha256').update(fs.readFileSync(p)).digest('hex');
 const run={workspace:root,run_id:'readiness-fixture',video:path.join(root,'final.mp4'),recording_policy_version:'flow-complete-v1'};
 const plan={...flexible(),storage_state:'.product-v2/browser-state.json'},planPath=path.join(control,'record-plan.json');
 const listener={pid:41001,created_ticks:1000,command_sha256:'verified-command-hash',ports:[8123]};
 const state={health:{run_id:run.run_id,workspace:root,version:plan.version,pid:listener.pid},owned:[{...listener}],
  requests:[],commands:[],browserLoads:0,browserLaunches:0,httpOK:true,invalidJSON:false,fetchError:null};
 const registryPath=path.join(control,'processes.json'),runPath=path.join(control,'run.json');
 const registry=processes=>save(registryPath,{workspace:root,processes});registry([{...listener}]);
 save(runPath,run);save(planPath,plan);fs.writeFileSync(path.join(root,'app.py'),'frozen application');
 const secret='private-login-token-fixture';save(path.join(control,'browser-state.json'),{cookies:[{value:secret}],origins:[]});
 const script=path.resolve(__dirname,'../scripts/record.cjs');
 const checkedRequire=name=>{
  if(name==='fixture-playwright'){
   state.browserLoads++;return {chromium:{launch:async()=>{state.browserLaunches++;throw Error('Readiness rejection must precede browser launch');}}};
  }
  if(name==='node:child_process')return {spawnSync:(exe,args)=>{
   assert.equal(exe,'fixture-python');
   if(path.basename(args[0])==='proflow.py'){
    assert.equal(args[1],'check-build');assert.equal(args[args.indexOf('--workspace')+1],root);
    assert.equal(args[args.indexOf('--plan')+1],planPath);state.commands.push(args);
    return state.constructionError?{status:2,stdout:'',stderr:state.constructionError}:
      {status:0,stdout:JSON.stringify(state.constructionResult??{required:true,status:'ready',run_id:run.run_id})};
   }
   assert.equal(path.basename(args[0]),'process_guard.py');assert.equal(args[1],'inspect');
   assert.equal(args[args.indexOf('--workspace')+1],root);state.commands.push(args);return {status:0,stdout:state.inspectRaw??JSON.stringify({owned:state.owned})};
  }};
  return require(name);
 };
 const sandbox={require:checkedRequire,module:{exports:{}},__dirname:path.dirname(script),
  process:{pid:process.pid,env:{...process.env,SCB_PRO_PYTHON:'fixture-python',SCB_PRO_PLAYWRIGHT:'fixture-playwright',SCB_PRO_FFMPEG:'fixture-encoder',SCB_PRO_FFPROBE:'fixture-probe'}},
  console,setTimeout,clearTimeout,AbortController,AbortSignal,URL,
  fetch:async(url,options)=>{
   assert.equal(url,'http://127.0.0.1:8123/api/health');assert.equal(options.method,'GET');assert.equal(options.redirect,'error');
   assert.ok(options.signal instanceof AbortSignal);state.requests.push(url);
   if(state.fetchError)throw state.fetchError;
   return {ok:state.httpOK,json:async()=>{if(state.invalidJSON)throw new SyntaxError('Invalid health JSON fixture');return state.health;}};
  }};
 vm.runInNewContext(fs.readFileSync(script,'utf8'),sandbox,{filename:script});
 const snapshot=()=>{
  const result={},pending=[root];
  while(pending.length){const folder=pending.pop();for(const entry of fs.readdirSync(folder,{withFileTypes:true})){
   const full=path.join(folder,entry.name),relative=path.relative(root,full);
   if(entry.isSymbolicLink())result[relative]='link:'+fs.readlinkSync(full);
   else if(entry.isDirectory()){result[relative]='directory';pending.push(full);}else result[relative]=hash(full);
  }}
  return result;
 };
 return {fs,path,root,control,run,runPath,plan,planPath,listener,state,secret,save,hash,registry,registryPath,snapshot,api:sandbox.module.exports,
  close:()=>{assert.equal(path.dirname(fs.realpathSync(root)),fs.realpathSync(os.tmpdir()));fs.rmSync(root,{recursive:true,force:true});}};
}
test('current-run readiness and direct capture share the construction gate before health and browser work',async()=>{
 const f=readinessFixture();
 try{
  f.run.construction_check_policy_version='dependency-bound-v1';f.save(f.runPath,f.run);
  const before=f.snapshot();f.state.constructionError='Construction dependency changed: algorithm / app.py';
  await assert.rejects(f.api.checkReady(f.root,f.planPath),/Construction dependency changed/);
  await assert.rejects(f.api.record(f.root,f.planPath,'capture'),/Construction dependency changed/);
  assert.deepEqual(f.snapshot(),before);assert.equal(f.state.requests.length,0);
  assert.equal(f.state.browserLoads,0);assert.equal(f.state.browserLaunches,0);
  f.state.constructionError=null;const facts=await f.api.checkReady(f.root,f.planPath);
  assert.equal(facts.construction_checks.required,true);assert.equal(facts.construction_checks.status,'ready');
  assert.deepEqual(f.snapshot(),before);assert.equal(f.state.browserLoads,0);
  f.state.constructionResult={required:false,status:'historical-contract'};
  await assert.rejects(f.api.checkReady(f.root,f.planPath),/self-check admission required/);
 }finally{f.close();}
});
test('read-only readiness returns current neutral hashes and listener facts without acquiring a lock or exposing session contents',async()=>{
 const f=readinessFixture();
 try{
  f.fs.writeFileSync(f.path.join(f.control,'recording-stage.lock'),'existing active lock');
  f.fs.writeFileSync(f.run.video,'existing video bytes; not a media claim');
  const before=f.snapshot(),facts=JSON.parse(JSON.stringify(await f.api.checkReady(f.root,f.planPath)));
  assert.equal(facts.status,'ready');assert.equal(facts.capture_performed,false);assert.equal(facts.visual_review,'not performed');
  assert.equal(facts.run_sha256,f.hash(f.runPath));assert.equal(facts.plan_sha256,f.hash(f.planPath));
  assert.deepEqual(facts.input_files,{'app.py':f.hash(f.path.join(f.root,'app.py'))});
  assert.equal(facts.storage_state.sha256,f.hash(f.path.join(f.control,'browser-state.json')));assert.deepEqual(facts.service_identity,{...f.listener,created_ticks:String(f.listener.created_ticks)});
  assert.equal(JSON.stringify(facts).includes(f.secret),false);assert.equal('passed' in facts,false);assert.deepEqual(f.snapshot(),before);
  assert.equal(f.state.browserLoads,0);assert.equal(f.state.browserLaunches,0);assert.equal(f.state.commands.length,1);
  delete f.plan.storage_state;f.save(f.planPath,f.plan);assert.equal((await f.api.checkReady(f.root,f.planPath)).storage_state,null);
 }finally{f.close();}
});
test('new-run evidence rejects stale construction dependencies before any encoder or decoder command',()=>{
 const f=readinessFixture();
 try{
  f.run.construction_check_policy_version='dependency-bound-v1';f.save(f.runPath,f.run);
  const capture=f.path.join(f.control,'capture.json');f.save(capture,{plan_path:f.planPath,construction_checks:{status:'ready',run_id:f.run.run_id}});
  f.save(f.path.join(f.control,'capture-pending.json'),{path:capture,sha256:f.hash(capture)});
  const before=f.snapshot();f.state.constructionError='Construction dependency changed: api / shared.py';
  assert.throws(()=>f.api.finishRecording(f.root),/Construction dependency changed: api/);
  assert.deepEqual(f.snapshot(),before);assert.equal(f.state.commands.length,1);
  assert.equal(f.path.basename(f.state.commands[0][0]),'proflow.py');assert.equal(f.state.commands[0][1],'check-build');
  assert.equal(f.state.requests.length,0);assert.equal(f.state.browserLoads,0);
 }finally{f.close();}
});
test('readiness keeps Python integer creation ticks above 2^53 exact and normalizes integer and string registries',async()=>{
 const f=readinessFixture(),ticks='134363897283128250';
 const raw=(value,token)=>JSON.stringify(value).replace('"created_ticks":1000','"created_ticks":'+token);
 try{
  assert.ok(BigInt(ticks)>BigInt(Number.MAX_SAFE_INTEGER));
  for(const [live,saved] of [[ticks,ticks],[ticks,JSON.stringify(ticks)],[JSON.stringify(ticks),ticks]]){
   // Emit numeric JSON literals directly, as Python does, before Node can round them.
   f.state.inspectRaw=raw({owned:[f.listener]},live);
   f.fs.writeFileSync(f.registryPath,raw({workspace:f.root,processes:[f.listener]},saved));
   const before=f.snapshot(),facts=await f.api.checkReady(f.root,f.planPath),encoded=JSON.stringify(facts);
   assert.equal(facts.service_identity.created_ticks,ticks);assert.equal(JSON.parse(encoded).service_identity.created_ticks,ticks);
   assert.ok(encoded.includes('"created_ticks":"'+ticks+'"'));assert.deepEqual(f.snapshot(),before);
  }
  assert.equal(f.state.browserLoads,0);assert.equal(f.state.browserLaunches,0);
 }finally{f.close();}
});
test('adjacent creation ticks that collapse to one Number reject readiness and capture before browser creation',async()=>{
 const f=readinessFixture(),ticks='134363897283128250',adjacent='134363897283128251';
 const raw=(value,token)=>JSON.stringify(value).replace('"created_ticks":1000','"created_ticks":'+token);
 try{
  assert.notEqual(BigInt(ticks),BigInt(adjacent));assert.equal(Number(ticks),Number(adjacent));
  for(const [live,saved] of [[ticks,adjacent],[adjacent,ticks],[ticks,JSON.stringify(adjacent)]]){
   f.state.inspectRaw=raw({owned:[f.listener]},live);
   f.fs.writeFileSync(f.registryPath,raw({workspace:f.root,processes:[f.listener]},saved));const before=f.snapshot();
   await assert.rejects(f.api.checkReady(f.root,f.planPath),/registered listener identity/);
   await assert.rejects(f.api.record(f.root,f.planPath,'capture'),/registered listener identity/);
   assert.deepEqual(f.snapshot(),before);assert.equal(f.state.browserLoads,0);assert.equal(f.state.browserLaunches,0);
  }
 }finally{f.close();}
});
test('creation identity rejects noncanonical or absent ticks instead of accepting equal invalid values',async()=>{
 const f=readinessFixture(),raw=(value,token)=>JSON.stringify(value).replace('"created_ticks":1000','"created_ticks":'+token);
 try{
  for(const token of ['0','-1','1000.0','1e3','null','""','"01000"']){
   f.state.inspectRaw=raw({owned:[f.listener]},token);f.fs.writeFileSync(f.registryPath,raw({workspace:f.root,processes:[f.listener]},token));
   const before=f.snapshot();await assert.rejects(f.api.checkReady(f.root,f.planPath),/exact decimal integer|registered listener identity/);assert.deepEqual(f.snapshot(),before);
  }
  const absent={...f.listener};delete absent.created_ticks;f.state.inspectRaw=JSON.stringify({owned:[absent]});f.registry([absent]);
  await assert.rejects(f.api.checkReady(f.root,f.planPath),/registered listener identity/);
  assert.equal(f.state.browserLoads,0);assert.equal(f.state.browserLaunches,0);
 }finally{f.close();}
});
test('readiness and capture share rejection of unregistered, changed and wrong-case listener or health facts before browser creation',async()=>{
 const f=readinessFixture();
 try{
  const original={...f.state.health},cases=[
   ()=>{f.state.owned=[];},()=>f.registry([]),()=>{f.state.owned=[{...f.listener,created_ticks:1001}];},
   ()=>{f.state.owned=[{...f.listener,command_sha256:'changed-command'}];},()=>{f.state.owned=[{...f.listener,ports:[9999]}];},
   ()=>{f.state.health={...original,version:'wrong-version'};},()=>{f.state.health={...original,run_id:'wrong-run'};},
   ()=>{f.state.health={...original,workspace:f.root+'-other'};},()=>{f.state.health={...original,pid:f.listener.pid+1};},
   ()=>f.save(f.registryPath,{workspace:f.root+'-other',processes:[f.listener]})];
  for(const change of cases){
   f.state.health={...original};f.state.owned=[{...f.listener}];f.registry([{...f.listener}]);change();const before=f.snapshot();
   await assert.rejects(f.api.checkReady(f.root,f.planPath),/different case\/version|registered listener|Registry workspace/);
   await assert.rejects(f.api.record(f.root,f.planPath,'capture'),/different case\/version|registered listener|Registry workspace/);
   assert.deepEqual(f.snapshot(),before);assert.equal(f.state.browserLoads,0);assert.equal(f.state.browserLaunches,0);
  }
 }finally{f.close();}
});
test('readiness rejects missing, directory, traversal and linked files before any health or browser request',async()=>{
 const f=readinessFixture();
 try{
  const real=f.path.join(f.root,'linked-real');f.fs.mkdirSync(real);f.fs.writeFileSync(f.path.join(real,'input.py'),'linked fixture');
  f.fs.symlinkSync(real,f.path.join(f.root,'linked'),'junction');
  const cases=[{input_files:['missing.py']},{input_files:['.product-v2']},{input_files:['../outside.py']},
   {input_files:['linked/input.py']},{storage_state:'.product-v2/missing-state.json'},
   {storage_state:f.path.join(f.control,'browser-state.json')}];
  for(const change of cases){
   f.save(f.planPath,{...f.plan,...change});const before=f.snapshot();
   await assert.rejects(f.api.checkReady(f.root,f.planPath),/ENOENT|Input outside workspace|Unsafe relative input|Linked input rejected/);
   await assert.rejects(f.api.record(f.root,f.planPath,'capture'),/ENOENT|Input outside workspace|Unsafe relative input|Linked input rejected/);
   assert.deepEqual(f.snapshot(),before);assert.equal(f.state.requests.length,0);assert.equal(f.state.commands.length,0);assert.equal(f.state.browserLoads,0);
  }
 }finally{f.close();}
});
test('readiness preserves frozen policy and run identity and refuses escaped health origins, redirects, network errors and malformed JSON',async()=>{
 const f=readinessFixture();
 try{
  f.save(f.planPath,{...f.plan,recording_policy_version:'legacy-fixed-v1'});const beforePolicy=f.snapshot();
  await assert.rejects(f.api.checkReady(f.root,f.planPath),/Legacy|legacy|frozen run/);assert.deepEqual(f.snapshot(),beforePolicy);
  f.save(f.planPath,{...f.plan,health_path:'/\\external.invalid/health'});const beforeOrigin=f.snapshot();
  await assert.rejects(f.api.checkReady(f.root,f.planPath),/recording origin/);assert.deepEqual(f.snapshot(),beforeOrigin);
  f.save(f.planPath,f.plan);f.save(f.runPath,{...f.run,workspace:f.root+'-other'});const changedRun=f.snapshot();
  await assert.rejects(f.api.checkReady(f.root,f.planPath),/Workspace\/run identity/);assert.deepEqual(f.snapshot(),changedRun);f.save(f.runPath,f.run);
  for(const mode of ['redirect','network','timeout','json']){
   f.state.httpOK=mode!=='redirect';f.state.invalidJSON=mode==='json';f.state.fetchError=mode==='network'?new Error('Fixture network failure'):mode==='timeout'?new Error('Fixture request timeout'):null;
   const before=f.snapshot();await assert.rejects(f.api.checkReady(f.root,f.planPath),/Health endpoint failed|Fixture network failure|Fixture request timeout|Invalid health JSON/);assert.deepEqual(f.snapshot(),before);
  }
  assert.equal(f.state.browserLoads,0);assert.equal(f.state.browserLaunches,0);assert.equal(f.state.commands.length,0);
 }finally{f.close();}
});
function downloadFixture(){
 const fs=require('node:fs'),path=require('node:path'),os=require('node:os');
 const root=fs.mkdtempSync(path.join(os.tmpdir(),'scb-download-guard-')),frame={},page={mainFrame:()=>frame};
 const url='http://127.0.0.1:8123/api/export',guard=downloadRequestGuard(page);
 const request=(options={})=>({url:()=>options.url??url,isNavigationRequest:()=>options.navigation??true,
  frame:()=>options.frame??frame,failure:()=>({errorText:options.error??'net::ERR_ABORTED'})});
 const download=(options={})=>({url:()=>options.url??url,page:()=>options.page??page,suggestedFilename:()=> 'export.csv',
  saveAs:async target=>{if(options.saveError)throw options.saveError;if(!options.missingFile)fs.writeFileSync(target,'id,value\nA001,42\n');},failure:async()=>options.failure??null});
 return {root,frame,page,url,guard,request,download,fs,path,target:path.join(root,'download.csv'),
  close:()=>{assert.equal(path.dirname(fs.realpathSync(root)),fs.realpathSync(os.tmpdir()));fs.rmSync(root,{recursive:true,force:true});}};
}
test('only the exact proven download navigation is exempt and failure-before-download evidence stays recorded',async()=>{
 const f=downloadFixture();
 try{
  const earlier=f.request();f.guard.track(earlier);f.guard.failed(earlier);
  const attempt=f.guard.begin(),matched=f.request();f.guard.track(matched);f.guard.failed(matched);
  assert.equal(f.guard.errors().length,2);
  const proof=await f.guard.save(attempt,f.download(),f.target);f.guard.end(attempt);
  const later=f.request();f.guard.track(later);f.guard.failed(later);
  assert.equal(f.guard.errors().length,2);const audit=f.guard.audit();
  assert.deepEqual(audit.map(x=>x.classification),['blocking_request_failure','successful_download_navigation_abort','blocking_request_failure']);
  assert.equal(audit[1].successful_download.sha256,proof.sha256);assert.equal(audit[1].request_id,proof.request_id);
  assert.notEqual(audit[0].request_id,proof.request_id);assert.notEqual(audit[2].request_id,proof.request_id);
  assert.equal(require('node:crypto').createHash('sha256').update(f.fs.readFileSync(f.target)).digest('hex'),proof.sha256);
 }finally{f.close();}
});
test('other URLs, frames, request types, error codes or download pages remain blocking despite a saved file',async()=>{
 for(const options of [{request:{url:'http://127.0.0.1:8123/other'}},{request:{frame:{}}},{request:{navigation:false}},
                      {request:{error:'net::ERR_CONNECTION_RESET'}},{request:{error:'net::ERR_FAILED'}},{download:{page:{}}}]){
  const f=downloadFixture();
  try{const attempt=f.guard.begin(),request=f.request(options.request);f.guard.track(request);f.guard.failed(request);
   await f.guard.save(attempt,f.download(options.download),f.target);f.guard.end(attempt);
   assert.equal(f.guard.errors().length,1);assert.equal(f.guard.audit()[0].classification,'blocking_request_failure');
  }finally{f.close();}
 }
});
test('ambiguous same-URL navigation requests are both blocking even when one attachment is saved',async()=>{
 const f=downloadFixture();
 try{const attempt=f.guard.begin();for(let i=0;i<2;i++){const request=f.request();f.guard.track(request);f.guard.failed(request);}
  const proof=await f.guard.save(attempt,f.download(),f.target);f.guard.end(attempt);
  assert.equal(proof.request_id,null);assert.equal(f.guard.errors().length,2);
  assert.ok(f.guard.audit().every(x=>x.classification==='blocking_request_failure'));
 }finally{f.close();}
});
test('failed save, failed download, missing file and changed saved hash never authorize an aborted request',async()=>{
 for(const options of [{saveError:new Error('Download connection failed')},{failure:'canceled'},{missingFile:true}]){
  const f=downloadFixture();
  try{const attempt=f.guard.begin(),request=f.request();f.guard.track(request);f.guard.failed(request);
   await assert.rejects(f.guard.save(attempt,f.download(options),f.target),/Download connection failed|Browser download failed|ENOENT/);f.guard.end(attempt);
   assert.equal(f.guard.errors().length,1);assert.equal(f.guard.audit()[0].successful_download,null);
  }finally{f.close();}
 }
 const f=downloadFixture();
 try{const attempt=f.guard.begin(),request=f.request();f.guard.track(request);f.guard.failed(request);
  await f.guard.save(attempt,f.download(),f.target);f.guard.end(attempt);assert.equal(f.guard.errors().length,0);
  f.fs.writeFileSync(f.target,'changed download');assert.equal(f.guard.errors().length,1);
  f.fs.unlinkSync(f.target);assert.equal(f.guard.errors().length,1);
 }finally{f.close();}
});
test('short legacy video is rejected',()=>assert.throws(()=>validatePlan({...valid(),duration_seconds:10})));
test('external URL and credentials rejected',()=>{assert.equal(localUrl('https://example.com'),false);assert.equal(localUrl('http://x:y@localhost'),false);});
test('idle padding is rejected',()=>{const p=valid();p.steps[1].at=19;assert.throws(()=>validatePlan(p));});
test('missing business assertions rejected',()=>{const p=valid();delete p.steps[1].expect;assert.throws(()=>validatePlan(p));});
test('arbitrary browser code rejected',()=>{const p=valid();p.steps[1].action='evaluate';assert.throws(()=>validatePlan(p));});
test('a repeated click tour is insufficient',()=>{const p=valid();p.steps.forEach(s=>s.action='click');assert.throws(()=>validatePlan(p));});
test('missing service identity contract rejected',()=>{const p=valid();delete p.health_path;assert.throws(()=>validatePlan(p));});
test('original UI Chinese and English labels are rejected in observed text',()=>{
  for(const text of ['专利平台','权利要求','权要','工程样本','推演数据','mock','dummy','synthetic','simulated','simulation','virtual','demo data'])assert.ok(auditUiText(text).length,text);
});
test('ordinary business abbreviations do not trigger English UI labels',()=>assert.deepEqual(auditUiText('设备PLC状态 CSV记录 任务已保存'),[]));
test('visible data-production copy is rejected while real business actions remain valid',()=>{
 for(const text of ['经计算生成数据','通过计算生成的数据','由计算生成的数据','计算生成数据','生成数据','样例数据','种子数据','由模型生成的数据'])assert.ok(auditUiText(text).length,text);
 for(const text of ['生成报告','经计算生成报告','通过计算生成报告','由模型生成报告','计算结果','预测结果','运行记录','任务已保存'])assert.deepEqual(auditUiText(text),[],text);
});
test('browser launches inherit private lane temp and downloads without changing parent environment',()=>{
 const previous=process.env.TEMP;
 const one=isolatedBrowserOptions('D:\\codex+\\temp\\lane1','D:\\codex+\\temp\\lane1\\downloads');
 const two=isolatedBrowserOptions('D:\\codex+\\temp\\lane2','D:\\codex+\\temp\\lane2\\downloads');
 assert.equal(one.env.TEMP,one.env.TMP);assert.equal(one.env.TEMP,one.env.TMPDIR);
 assert.notEqual(one.env.TEMP,two.env.TEMP);assert.notEqual(one.downloadsPath,two.downloadsPath);assert.equal(process.env.TEMP,previous);
});
test('batch lease identifies current parent and exact workspace and rejects partial or full-phase claims',async()=>{
 assert.equal(leaseArgs(null,'workspace'),null);
 assert.throws(()=>leaseArgs({root:'root',ownerPid:101},'workspace'),/Complete batch/);
 const lease={root:'root',batchId:'batch',caseId:'case',token:'token',ownerPid:101};
 const args=leaseArgs(lease,'workspace');assert.equal(args[args.indexOf('--value')+1],'workspace');assert.equal(args[args.indexOf('--pid')+1],'101');
 assert.equal(leaseArgs(lease,'workspace','evidence')[1],'verify-evidence');
 await assert.rejects(record('missing-workspace',undefined,'full',lease),/capture or evidence phase/);
});
test('failed evidence rejects changed raw/input facts and releases the same-case lock',async()=>{
 const fs=require('node:fs'),path=require('node:path'),os=require('node:os'),crypto=require('node:crypto');
 const root=fs.mkdtempSync(path.join(os.tmpdir(),'scb-stage-test-'));const control=path.join(root,'.product-v2');fs.mkdirSync(control);
 const hash=p=>crypto.createHash('sha256').update(fs.readFileSync(p)).digest('hex');
 const save=(p,v)=>fs.writeFileSync(p,JSON.stringify(v));
 try{
  const raw=path.join(root,'raw.webm'),input=path.join(root,'app.js'),capture=path.join(root,'capture.json');fs.writeFileSync(raw,'preserved raw');fs.writeFileSync(input,'frozen input');
  const run={workspace:root,run_id:'fixture',video:path.join(root,'final.mp4')};save(path.join(control,'run.json'),run);
  const facts={status:'captured',workspace:root,run_id:'fixture',final:run.video,rawPath:raw,raw_sha256:hash(raw),errors:[],inputs:{'app.js':hash(input)}};
  save(capture,facts);const pending=()=>save(path.join(control,'capture-pending.json'),{path:capture,sha256:hash(capture)});pending();
  fs.writeFileSync(raw,'changed raw');await assert.rejects(record(root,undefined,'evidence'),/Original capture changed/);assert.equal(fs.existsSync(path.join(control,'recording-stage.lock')),false);
  assert.equal(fs.existsSync(path.join(control,'recording.json')),false);assert.equal(fs.existsSync(run.video),false);
  facts.raw_sha256=hash(raw);save(capture,facts);pending();fs.writeFileSync(input,'changed input');
  await assert.rejects(record(root,undefined,'evidence'),/Application input changed/);assert.equal(fs.existsSync(path.join(control,'recording-stage.lock')),false);
  fs.writeFileSync(path.join(control,'recording-stage.lock'),'active fixture owner');await assert.rejects(record(root,undefined,'evidence'),/EEXIST/);assert.equal(fs.readFileSync(path.join(control,'recording-stage.lock'),'utf8'),'active fixture owner');
 }finally{assert.equal(path.dirname(fs.realpathSync(root)),fs.realpathSync(os.tmpdir()));fs.rmSync(root,{recursive:true,force:true});}
});
test('registered workspace rejects omitted leases before every media entry and preserves legacy independence',async()=>{
 const fs=require('node:fs'),path=require('node:path'),os=require('node:os'),crypto=require('node:crypto');
 const root=fs.mkdtempSync(path.join(os.tmpdir(),'scb-binding-test-')),work=path.join(root,'case'),pool=path.join(root,'pool');
 fs.mkdirSync(path.join(work,'.product-v2'),{recursive:true});fs.mkdirSync(path.join(pool,'batch'),{recursive:true});
 const manifest=path.join(pool,'batch','manifest.json');fs.writeFileSync(manifest,JSON.stringify({media_lease_contract:'windows-job-v1',cases:[{case_id:'case',workspace:work}]}));
 fs.writeFileSync(path.join(work,'.product-v2/batch-binding.json'),JSON.stringify({contract:'windows-job-v1',root:pool,batch_id:'batch',case_id:'case',manifest_sha256:crypto.createHash('sha256').update(fs.readFileSync(manifest)).digest('hex')}));
 try{
  for(const phase of ['capture','evidence','full'])await assert.rejects(record(work,undefined,phase),/requires its capture\/evidence lease/);
  assert.throws(()=>finishRecording(work),/requires its capture\/evidence lease/);
  assert.equal(fs.existsSync(path.join(work,'.product-v2/recording-stage.lock')),false);
  assert.throws(()=>validateBatchPhase(work,'evidence',{root:pool,batchId:'other',caseId:'case',token:'token',ownerPid:101}),/frozen workspace binding/);
  const legacy=path.join(root,'legacy');fs.mkdirSync(legacy);assert.equal(validateBatchPhase(legacy,'full',null),null);
 }finally{assert.equal(path.dirname(fs.realpathSync(root)),fs.realpathSync(os.tmpdir()));fs.rmSync(root,{recursive:true,force:true});}
});

function flexible(){return {...valid(),recording_policy_version:'flow-complete-v1',estimated_duration_seconds:82,timeout_seconds:180,
 final_result:{selector:'#result',reading_seconds:7,reading_reason:'阅读本次提交的处理结果与摘要'}};}
test('new policy accepts different estimates above75 and has no fixed duration target',()=>{
 for(const seconds of [69,89,130])assert.equal(validatePlan({...flexible(),estimated_duration_seconds:seconds}),seconds);
 assert.throws(()=>validatePlan({...flexible(),duration_seconds:60}),/not a fixed duration/);
 assert.throws(()=>validatePlan({...flexible(),timeout_seconds:82}),/separate/);
 const p=flexible();p.steps.forEach(s=>delete s.at);assert.equal(validatePlan(p),82);
});
test('policy selection is frozen and unknown or mismatched plans reject',()=>{
 assert.equal(boundPolicy(valid(),{}),'legacy-fixed-v1');
 assert.throws(()=>boundPolicy(flexible(),{}),/frozen run/);
 assert.throws(()=>boundPolicy(valid(),{recording_policy_version:'flow-complete-v1'}),/frozen run/);
 assert.throws(()=>validatePlan({...flexible(),recording_policy_version:'surprise'}),/Unknown/);
});
test('reading requires observed result, positive final dwell and a meaningful purpose',()=>{
 const p=flexible();delete p.final_result.selector;assert.throws(()=>validatePlan(p),/selector/);
 for(const final_result of [{selector:'#result',reading_seconds:0},{selector:'#result',reading_seconds:5,reading_reason:''}])assert.throws(()=>validatePlan({...flexible(),final_result}),/Meaningful/);
 const q=flexible();q.steps[0].reading_seconds=4;assert.throws(()=>validatePlan(q),/Meaningful/);
});
test('flow completes naturally after actual operations and result reading with no scheduling waits or padding',async()=>{
 const plan=flexible(),waits=[],events=[];let seconds=0,views=0;
 const result=await executeTimeline(plan,async (step,index)=>{const event={action:step.action,started:seconds};seconds+=20;event.completed=seconds;events.push(event);return event;},async()=>{views++;},{now:()=>seconds,wait:async ms=>{waits.push(ms);seconds+=ms/1000;}});
 assert.equal(result.duration,127);assert.equal(views,2);assert.deepEqual(waits,[7000]);
 assert.equal(validateMeasuredDuration({...result,events,recording_policy_version:plan.recording_policy_version,estimated_duration_seconds:82,timeout_seconds:180,planned_step_count:6,completed_step_count:6}),127);
});
test('operation reading is recorded separately from business completion and final reading',async()=>{
 const plan=flexible();plan.steps[0].reading_seconds=3;plan.steps[0].reading_reason='检查筛选范围';let seconds=0;const events=[];
 const result=await executeTimeline(plan,async step=>{const e={action:step.action,started:seconds};seconds+=10;e.completed=seconds;events.push(e);return e;},async()=>{}, {now:()=>seconds,wait:async ms=>{seconds+=ms/1000;}});
 assert.equal(result.duration,70);assert.equal(events[0].reading_started,10);assert.equal(events[0].reading_completed,13);assert.equal(result.final_result_completion.observed_at,63);
});
test('too-short meaningful flow fails without adding an idle tail',async()=>{
 let seconds=0;const waits=[];
 await assert.rejects(executeTimeline(flexible(),async step=>{seconds+=2;return {};},async()=>{}, {now:()=>seconds,wait:async ms=>{waits.push(ms);seconds+=ms/1000;}}),/never pad/);
 assert.deepEqual(waits,[7000]);
});
test('runtime timeout interrupts a hung action instead of treating timeout as target duration',async()=>{
 await assert.rejects(executeTimeline({...flexible(),timeout_seconds:.02},()=>new Promise(()=>{}),async()=>{}, {now:()=>0}),/runtime timeout/);
});
test('legacy timeline still uses its frozen duration and never silently adopts flow policy',async()=>{
 let seconds=0;const result=await executeTimeline(valid(),async()=>{seconds+=1;return {};},async()=>{throw Error('legacy must not use new final result');},{now:()=>seconds,wait:async ms=>{seconds+=ms/1000;}});
 assert.equal(result.duration,60);assert.equal(seconds,60);assert.equal(validateMeasuredDuration({duration:60}),60);
 assert.throws(()=>validateMeasuredDuration({duration:85}),/frozen recording policy/);
});
test('completed-video retry ignores later input edits and preserves receipt bytes without encoding or decoding again (mock media validator)',()=>{
 const fs=require('node:fs'),path=require('node:path'),os=require('node:os'),crypto=require('node:crypto'),vm=require('node:vm');
 const root=fs.mkdtempSync(path.join(os.tmpdir(),'scb-reuse-test-'));fs.mkdirSync(path.join(root,'.product-v2'));
 const hash=p=>crypto.createHash('sha256').update(fs.readFileSync(p)).digest('hex'),save=(p,v)=>fs.writeFileSync(p,JSON.stringify(v));
 const script=path.resolve(__dirname,'../scripts/record.cjs'),commands=[];
 const mediaRequire=name=>name==='node:child_process'?{spawnSync:(exe,args)=>{commands.push(args);assert.equal(path.basename(args[0]),'media_evidence.py');assert.equal(args[1],'validate');return {status:0,stdout:'{}'};}}:require(name);
 const sandbox={require:mediaRequire,module:{exports:{}},__dirname:path.dirname(script),process,console,setTimeout,clearTimeout,AbortController};
 vm.runInNewContext(fs.readFileSync(script,'utf8'),sandbox,{filename:script});
 const previous={SCB_PRO_PYTHON:process.env.SCB_PRO_PYTHON,SCB_PRO_FFMPEG:process.env.SCB_PRO_FFMPEG,SCB_PRO_FFPROBE:process.env.SCB_PRO_FFPROBE};
 try{
  process.env.SCB_PRO_PYTHON='fixture-validator';process.env.SCB_PRO_FFMPEG='fixture-encoder';process.env.SCB_PRO_FFPROBE='fixture-probe';
  const raw=path.join(root,'raw.webm'),final=path.join(root,'final.mp4'),input=path.join(root,'app.js');
  fs.writeFileSync(raw,'fixture raw');fs.writeFileSync(final,'fixture final; not a decoding claim');fs.writeFileSync(input,'frozen input');
  const run={workspace:root,run_id:'fixture',video:final,construction_check_policy_version:'dependency-bound-v1'};save(path.join(root,'.product-v2/run.json'),run);
  const capture=path.join(root,'capture.json');save(capture,{status:'captured',workspace:root,run_id:'fixture',final,dir:root,rawPath:raw,raw_sha256:hash(raw),errors:[],inputs:{'app.js':hash(input)},duration:60,construction_checks:{status:'ready',run_id:run.run_id}});
  save(path.join(root,'.product-v2/capture-pending.json'),{path:capture,sha256:hash(capture)});
  const receipt=path.join(root,'.product-v2/recording.json');save(receipt,{passed:true,capture_receipt_sha256:hash(capture),sha256:hash(final),duration:60,width:1920,height:1080,events:[{action:'click',started:1,completed:2}],frames:path.join(root,'frames')});
  const timeline=path.join(root,'timeline.json');save(timeline,{fixture:true});save(path.join(root,'.product-v2/controlled-video.json'),{timeline,sha256:hash(timeline)});
  fs.writeFileSync(input,'later parameter/data copy change');
  const before=fs.readFileSync(receipt),result=sandbox.module.exports.finishRecording(root);
  assert.equal(result.reused_existing_evidence,true);assert.equal(result.visual_review_required,true);assert.equal(commands.length,1);
  assert.deepEqual(fs.readFileSync(receipt),before);assert.equal(commands[0][commands[0].indexOf('--recording')+1],receipt);
  save(path.join(root,'.product-v2/build-checks.json'),{video_material_change:'Primary operation path was replaced'});
  assert.throws(()=>sandbox.module.exports.finishRecording(root),/major system\/operation change/);assert.equal(commands.length,1);
  save(path.join(root,'.product-v2/build-checks.json'),{});
  fs.writeFileSync(raw,'changed raw');assert.throws(()=>sandbox.module.exports.finishRecording(root),/Original capture changed/);assert.equal(commands.length,1);
 }finally{
  for(const [key,value] of Object.entries(previous)){if(value===undefined)delete process.env[key];else process.env[key]=value;}
  assert.equal(path.dirname(fs.realpathSync(root)),fs.realpathSync(os.tmpdir()));fs.rmSync(root,{recursive:true,force:true});
 }
});
test('evidence completion preserves exact creation ticks from a legacy numeric capture receipt (mock media commands)',()=>{
 const fs=require('node:fs'),path=require('node:path'),os=require('node:os'),crypto=require('node:crypto'),vm=require('node:vm');
 const root=fs.mkdtempSync(path.join(os.tmpdir(),'scb-ticks-evidence-')),control=path.join(root,'.product-v2');fs.mkdirSync(control);
 const ticks='134363897283128250',hash=p=>crypto.createHash('sha256').update(fs.readFileSync(p)).digest('hex'),save=(p,v)=>fs.writeFileSync(p,JSON.stringify(v));
 const script=path.resolve(__dirname,'../scripts/record.cjs'),commands=[];
 const mediaRequire=name=>name==='node:child_process'?{spawnSync:(exe,args)=>{
  commands.push({exe,args});
  if(exe==='fixture-encoder'){fs.writeFileSync(args.at(-1),'fixture encoded bytes; not a decoding claim');return {status:0,stdout:''};}
  if(exe==='fixture-probe')return {status:0,stdout:JSON.stringify({format:{duration:'60'},streams:[{width:1920,height:1080}]})};
  assert.equal(exe,'fixture-validator');assert.equal(path.basename(args[0]),'media_evidence.py');assert.equal(args[1],'generate');
  const report=JSON.parse(fs.readFileSync(args[args.indexOf('--recording')+1],'utf8'));assert.equal(report.service_identity.created_ticks,ticks);
  return {status:0,stdout:'{}'};
 }}:require(name);
 const sandbox={require:mediaRequire,module:{exports:{}},__dirname:path.dirname(script),
  process:{pid:process.pid,env:{...process.env,SCB_PRO_PYTHON:'fixture-validator',SCB_PRO_FFMPEG:'fixture-encoder',SCB_PRO_FFPROBE:'fixture-probe'}},
  console,setTimeout,clearTimeout,AbortController};
 vm.runInNewContext(fs.readFileSync(script,'utf8'),sandbox,{filename:script});
 try{
  const raw=path.join(root,'raw.webm'),input=path.join(root,'app.js'),final=path.join(root,'final.mp4'),capture=path.join(root,'capture.json');
  fs.writeFileSync(raw,'fixture raw');fs.writeFileSync(input,'frozen input');save(path.join(control,'run.json'),{workspace:root,run_id:'fixture',video:final});
  const facts={status:'captured',workspace:root,run_id:'fixture',final,dir:root,rawPath:raw,raw_sha256:hash(raw),errors:[],inputs:{'app.js':hash(input)},
   prelude:0,duration:60,events:[],texts:[],identity:{pid:41001,created_ticks:1000,command_sha256:'verified-command-hash',ports:[8123]}};
  fs.writeFileSync(capture,JSON.stringify(facts).replace('"created_ticks":1000','"created_ticks":'+ticks));
  const captureHash=hash(capture);save(path.join(control,'capture-pending.json'),{path:capture,sha256:captureHash});
  sandbox.module.exports.finishRecording(root);
  assert.equal(hash(capture),captureHash);assert.equal(JSON.parse(fs.readFileSync(path.join(control,'recording.json'),'utf8')).service_identity.created_ticks,ticks);
  assert.deepEqual(commands.map(x=>x.exe),['fixture-encoder','fixture-probe','fixture-validator']);
 }finally{assert.equal(path.dirname(fs.realpathSync(root)),fs.realpathSync(os.tmpdir()));fs.rmSync(root,{recursive:true,force:true});}
});
