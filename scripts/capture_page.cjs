// Trusted recorder: declarative local-page operations only, no case-supplied code.
const fs = require('fs');
const path = require('path');
const crypto = require('crypto');
const {reuseAudit,assertNoOwnerRepair} = require('./capture_audit_reuse.cjs');
const {watchTransition} = require('./capture_transition.cjs');
const {createRequire} = require('module');
const request = JSON.parse(fs.readFileSync(process.argv[2], 'utf8'));
const {chromium} = createRequire(path.join(request.node_modules, 'package.json'))('playwright');
const {plan, output, case_dir: caseDir, mode} = request;
const pause = ms => new Promise(resolve => setTimeout(resolve, ms));
const hash = filename => crypto.createHash('sha256').update(fs.readFileSync(filename)).digest('hex');
const errors = [], pages = [], events = [];
const base = plan.base_url;

async function ready(page, module) {
  await page.waitForURL(url => url.origin === base && url.pathname === module.route, {timeout: 15000});
  await page.getByRole('heading', {name: module.heading, exact: true, level: 1}).waitFor({state:'visible', timeout:15000});
  for (const selector of module.ready_selectors) await page.locator(selector).first().waitFor({state:'visible', timeout:15000});
  await page.evaluate(async () => {
    await document.fonts.ready;
    await Promise.all([...document.images].filter(img=>img.getClientRects().length).map(img=>img.decode()));
  });
  if (await page.locator('vite-error-overlay, nextjs-portal [data-nextjs-dialog-overlay]').count()) throw Error('Framework error overlay');
  const text = await page.locator('body').innerText();
  const compact = text.replace(/[\s\u200b-\u200d\ufeff]+/g,'');
  if (request.forbidden.some(term=>compact.includes(term)) || /\b(mock|dummy|synthetic|simulated|simulation|virtual)\b|demo(?:nstration)?\s+data/i.test(text)) throw Error('Forbidden visible copy');
  return text;
}

async function evidence(page, module, index) {
  const text = await ready(page,module);
  const filename = path.join(output,`module-${index+1}.png`);
  await page.screenshot({path:filename});
  const raw = {url:page.url(),state:module.name,visible_text:text,screenshot:path.relative(caseDir,filename).replaceAll('\\','/'),screenshot_sha256:hash(filename),capture_method:'Actual DOM innerText and browser screenshot after target heading, fonts and images became ready'};
  pages.push(reuseAudit(caseDir,raw));
}

async function session(record) {
  const context = await chromium.launch({headless:true});
  const browser = await context.newContext({viewport:{width:1920,height:1080},locale:'zh-CN',deviceScaleFactor:1,
    ...(record?{recordVideo:{dir:path.join(output,'raw'),size:{width:1920,height:1080}}}:{})});
  // Requests to other local case ports are refused; remote source assets remain possible.
  await browser.route('**/*', async route => {
    const url = new URL(route.request().url());
    if (['127.0.0.1','localhost','[::1]'].includes(url.hostname) && url.origin !== base) return route.abort('blockedbyclient');
    return route.continue();
  });
  const page = await browser.newPage();
  page.on('pageerror', error=>errors.push(error.message));
  page.on('console', message=>{if(message.type()==='error')errors.push(message.text());});
  let video;
  try {
    const identity = await (await page.request.get(base+plan.health_path)).json();
    if(identity.case_id !== request.case_id || path.resolve(identity.workspace).toLowerCase() !== path.resolve(caseDir).toLowerCase() || identity.version !== plan.version) throw Error('Service identity/version mismatch');
    await page.goto(base+plan.modules[0].route,{waitUntil:'domcontentloaded'});
    await ready(page,plan.modules[0]);
    await page.mouse.move(1850,70);
    const started = Date.now();
    for(let index=0;index<plan.modules.length;index++) {
      const module=plan.modules[index];
      if(index) {
        events.push({type:'interaction_start',elapsed_ms:Date.now()-started});
        const finish=plan.schema_version===2 ? await watchTransition(page,plan.modules) : null;
        await page.locator(module.enter_selector).click();
        await ready(page,module);
        if(finish) {
          const continuity=await finish();
          events.push({type:'transition_continuity',...continuity});
          if(!continuity.ok) throw Error('Transition lost both ready business pages; keep the previous page and navigation visible until the next page is ready');
        }
        events.push({type:'module_ready',elapsed_ms:Date.now()-started});
      }
      if(record || mode==='probe') await evidence(page,module,index);
      if(record) await pause(request.target_seconds*1000/plan.modules.length + 200);
    }
    events.push({type:'end',elapsed_ms:Date.now()-started});
    if(record) video=page.video();
  } finally {
    await browser.close();
    await context.close();
  }
  return video ? await video.path() : null;
}

(async()=>{
  fs.mkdirSync(output,{recursive:true});
  if(mode==='record') assertNoOwnerRepair(caseDir);
  if(mode==='record') { await session(false); pages.length=0; events.length=0; assertNoOwnerRepair(caseDir); }
  const raw=await session(mode==='record');
  if(mode==='record') assertNoOwnerRepair(caseDir);
  const result={schema_version:1,mode,pages,events,errors,raw_video:raw,case_id:request.case_id,version:plan.version};
  fs.writeFileSync(path.join(output,'browser.json'),JSON.stringify(result,null,2));
  console.log(JSON.stringify({mode,raw_video:raw,errors,states:pages.length}));
  if(errors.length) process.exitCode=1;
})().catch(error=>{
  fs.writeFileSync(path.join(output,'browser-failure.json'),JSON.stringify({mode,pages,events,errors:[...errors,error.message]},null,2));
  console.error(error.stack);process.exitCode=1;
});
