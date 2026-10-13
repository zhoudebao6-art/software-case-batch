const {test}=require('node:test');
const assert=require('node:assert/strict');
const {validatePlan,localUrl,auditUiText,record,leaseArgs,isolatedBrowserOptions,validateBatchPhase,finishRecording}=require('../scripts/record.cjs');
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
