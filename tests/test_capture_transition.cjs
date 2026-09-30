const test = require('node:test');
const assert = require('node:assert/strict');
const vm = require('node:vm');
const {installMonitor, summarize} = require('../scripts/capture_transition.cjs');

function simulate(states) {
  const frames = [], samples = [];
  let current = states[0];
  const node = () => ({textContent:current, getBoundingClientRect:()=>({width:100,height:100})});
  const context = {
    window:{report:async value=>samples.push(value)}, location:{href:'http://127.0.0.1/a'},
    performance:{now:()=>samples.length*16}, requestAnimationFrame:fn=>frames.push(fn),
    getComputedStyle:()=>({visibility:'visible',display:'block',opacity:'1'}),
    document:{querySelectorAll:selector=>selector==='h1'||selector==='#'+current ? (current?[node()]:[]) : []}
  };
  vm.createContext(context);
  vm.runInContext(`(${installMonitor.toString()})({name:'report',modules:[{heading:'A',ready_selectors:['#A']},{heading:'B',ready_selectors:['#B']}]})`,context);
  for(const state of states) { current=state; frames.shift()(); }
  return summarize(samples);
}

test('probe catches loading frame hidden by ready-only screenshots',()=>{
  const report=simulate(['A','','B']);
  assert.equal(report.ok,false);
  assert.equal(report.missing_content_frames,1);
});
test('keeping previous business page until next ready is continuous',()=>{
  assert.equal(simulate(['A','A','B']).ok,true);
});
test('no observed frames must not claim continuity',()=>{
  assert.equal(summarize([]).ok,false);
});

test('actual browser distinguishes whole-page loading from retained business page',
  {skip:!process.env.CASEFLOW_TEST_NODE_MODULES}, async()=>{
  const path=require('node:path'), http=require('node:http');
  const {createRequire}=require('node:module');
  const {chromium}=createRequire(path.join(process.env.CASEFLOW_TEST_NODE_MODULES,'package.json'))('playwright');
  const {watchTransition}=require('../scripts/capture_transition.cjs');
  const server=http.createServer((req,res)=>{
    res.setHeader('Content-Type','text/html; charset=utf-8');
    res.end(`<div id="root"><h1>A</h1><main id="A">Current business records</main></div><button id="next">Next</button>
      <script>next.onclick=()=>{if(location.pathname==='/bad')root.innerHTML='Loading...';setTimeout(()=>{root.innerHTML='<h1>B</h1><main id="B">Target business records</main>'},250)}</script>`);
  });
  await new Promise(resolve=>server.listen(0,'127.0.0.1',resolve));
  let browser;
  try {
    browser=await chromium.launch({headless:true});
    for(const route of ['bad','good']) {
      const page=await browser.newPage();
      try {
        await page.goto(`http://127.0.0.1:${server.address().port}/${route}`);
        const finish=await watchTransition(page,[{heading:'A',ready_selectors:['#A']},{heading:'B',ready_selectors:['#B']}]);
        await page.locator('#next').click();
        await page.locator('#B').waitFor({state:'visible'});
        const report=await finish();
        assert.equal(report.ok,route==='good',JSON.stringify(report));
        assert.ok(report.observed_frames>0);
      } finally { await page.close(); }
    }
  } finally {
    if(browser) await browser.close();
    await new Promise(resolve=>server.close(resolve));
  }
});
