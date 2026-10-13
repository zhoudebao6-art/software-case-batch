const {test}=require('node:test');
const assert=require('node:assert/strict');
const {validatePlan,localUrl,auditUiText,record,leaseArgs,isolatedBrowserOptions,validateBatchPhase,finishRecording,executeTimeline,boundPolicy,validateMeasuredDuration}=require('../scripts/record.cjs');
function valid(){return {url:'http://127.0.0.1:8123',ready:'#ready',health_path:'/api/health',version:'v1',input_files:['app.py'],steps:[
  {at:1,action:'fill',value:'x',selector:'#search',expect:'#search'},
  {at:10,action:'click',selector:'#query',expect:'#table'},
  {at:20,action:'click',selector:'#detail',expect:'#panel'},
  {at:30,action:'select',value:'x',selector:'#status',expect:'#status'},
  {at:40,action:'click',selector:'#save',expect:'#saved'},
  {at:53,action:'download',selector:'#download',expect:'#saved'}]};}
test('default is a minute',()=>assert.equal(validatePlan(valid()),60));
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
test('same-capture retry validates existing evidence and preserves receipt bytes without encoding or decoding again (mock media validator)',()=>{
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
  const run={workspace:root,run_id:'fixture',video:final};save(path.join(root,'.product-v2/run.json'),run);
  const capture=path.join(root,'capture.json');save(capture,{status:'captured',workspace:root,run_id:'fixture',final,dir:root,rawPath:raw,raw_sha256:hash(raw),errors:[],inputs:{'app.js':hash(input)},duration:60});
  save(path.join(root,'.product-v2/capture-pending.json'),{path:capture,sha256:hash(capture)});
  const receipt=path.join(root,'.product-v2/recording.json');save(receipt,{passed:true,capture_receipt_sha256:hash(capture),sha256:hash(final),duration:60,width:1920,height:1080,events:[{action:'click',started:1,completed:2}],frames:path.join(root,'frames')});
  const timeline=path.join(root,'timeline.json');save(timeline,{fixture:true});save(path.join(root,'.product-v2/controlled-video.json'),{timeline,sha256:hash(timeline)});
  const before=fs.readFileSync(receipt),result=sandbox.module.exports.finishRecording(root);
  assert.equal(result.reused_existing_evidence,true);assert.equal(result.visual_review_required,true);assert.equal(commands.length,1);
  assert.deepEqual(fs.readFileSync(receipt),before);assert.equal(commands[0][commands[0].indexOf('--recording')+1],receipt);
  fs.writeFileSync(raw,'changed raw');assert.throws(()=>sandbox.module.exports.finishRecording(root),/Original capture changed/);assert.equal(commands.length,1);
 }finally{
  for(const [key,value] of Object.entries(previous)){if(value===undefined)delete process.env[key];else process.env[key]=value;}
  assert.equal(path.dirname(fs.realpathSync(root)),fs.realpathSync(os.tmpdir()));fs.rmSync(root,{recursive:true,force:true});
 }
});
