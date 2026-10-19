const test = require('node:test');
const assert = require('node:assert/strict');
const path = require('node:path');
const {pathToFileURL} = require('node:url');
const moduleUrl = pathToFileURL(path.join(__dirname, '../assets/web/request_scope.mjs')).href;
const deferred = () => { let resolve, reject; const promise = new Promise((a,b) => {resolve=a;reject=b;}); return {promise, resolve, reject}; };

test('late response from A cannot replace B, including stale error/finally', async () => {
  const {createRequestScope} = await import(moduleUrl); const scope = createRequestScope();
  const state = {object: null, value: null, error: null, busy: false};
  async function load(object, task) {
    scope.enter(object); state.object=object; state.value=null; state.error=null; state.busy=true;
    const ticket=scope.begin();
    try { const value=await task; if(scope.isCurrent(ticket)) state.value=value; }
    catch(error) { if(scope.isCurrent(ticket)) state.error=error.message; }
    finally { if(scope.finish(ticket)) state.busy=false; }
  }
  const a=deferred(), b=deferred(); const first=load('A:v1',a.promise), second=load('B:v1',b.promise);
  a.reject(new Error('old A error')); await first;
  assert.deepEqual(state,{object:'B:v1',value:null,error:null,busy:true});
  b.resolve('B result'); await second;
  assert.deepEqual(state,{object:'B:v1',value:'B result',error:null,busy:false});
});

test('closed/empty context and same-object new revision invalidate outstanding work', async () => {
  const {createRequestScope} = await import(moduleUrl); const scope=createRequestScope();
  scope.enter('A:v1'); const first=scope.begin(); scope.close();
  assert.equal(scope.isCurrent(first),false); assert.equal(first.signal.aborted,true);
  assert.throws(()=>scope.begin(),/No current/);
  scope.enter('A:v1'); const old=scope.begin(); scope.enter('A:v2'); const fresh=scope.begin();
  assert.equal(scope.isCurrent(old),false); assert.equal(scope.isCurrent(fresh),true);
  scope.enter('A:v2'); assert.equal(scope.isCurrent(fresh),false);
});

test('latest per-lane work wins without canceling independent current lanes', async () => {
  const {createRequestScope} = await import(moduleUrl); const scope=createRequestScope(); scope.enter('A:v1');
  const first=scope.begin('details'), chart=scope.begin('chart'), second=scope.begin('details');
  assert.equal(first.signal.aborted,true); assert.equal(scope.isCurrent(first),false);
  assert.equal(scope.isCurrent(chart),true); assert.equal(scope.isCurrent(second),true);
  assert.equal(scope.finish(first),false); assert.equal(scope.finish(second),true);
  scope.cancel('chart'); assert.equal(scope.isCurrent(chart),false);
});

test('foreign or forged tickets cannot commit', async () => {
  const {createRequestScope} = await import(moduleUrl); const a=createRequestScope(), b=createRequestScope();
  a.enter('A:v1'); b.enter('A:v1'); const ticket=a.begin();
  assert.equal(b.isCurrent(ticket),false); assert.equal(a.isCurrent({...ticket}),false);
  a.close(); assert.equal(a.finish(ticket),false);
  assert.throws(()=>a.enter({id:'A'}),/Context/);
});

test('successful old request cannot replace a newer completed result', async () => {
  const {createRequestScope} = await import(moduleUrl); const scope=createRequestScope();
  let shown=null; const old=deferred(), fresh=deferred();
  async function read(task) { const t=scope.begin(); const value=await task; if(scope.isCurrent(t)) shown=value; scope.finish(t); }
  scope.enter('A:v1'); const a=read(old.promise); scope.enter('B:v1'); const b=read(fresh.promise);
  fresh.resolve('B result'); await b; old.resolve('old A result'); await a;
  assert.equal(shown,'B result');
});

test('closing a view does not pretend to undo a completed server command', async () => {
  const {createRequestScope} = await import(moduleUrl); const scope=createRequestScope();
  const server=deferred(); let persisted=null, shown=null;
  scope.enter('A:v1'); const t=scope.begin('save');
  const command=server.promise.then(value=>{persisted=value; if(scope.isCurrent(t)) shown=value;});
  scope.close(); server.resolve('saved A'); await command;
  assert.equal(persisted,'saved A'); assert.equal(shown,null); assert.equal(t.signal.aborted,true);
});
