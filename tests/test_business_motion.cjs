// Real Chromium exercises of a small isolated DOM fixture, not product acceptance.
const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const root = path.resolve(__dirname, '..');
const config = JSON.parse(fs.readFileSync(path.join(root, 'local.config.json'), 'utf8').replace(/^\uFEFF/, ''));
const { chromium } = require(config.playwright_module);
const code = fs.readFileSync(path.join(root, 'assets/web/business_motion.mjs'), 'utf8');

async function fixture(callback) {
  const browser = await chromium.launch({headless:true});
  try {
    const page = await browser.newPage();
    await page.setContent('<main id="root"><button id="action">Apply</button><output id="result">old</output></main>');
    await page.evaluate(async source => {
      const {createBusinessMotion}=await import('data:text/javascript;base64,'+btoa(source));
      window.motion=createBusinessMotion(document.querySelector('#root'));
    }, code);
    await callback(page);
  } finally { await browser.close(); }
}

test('motion overlays real committed state, rapid replacement cancels old animation', async () => {
  await fixture(async page => {
    const result=await page.evaluate(async () => {
      const el=document.querySelector('#result');el.textContent='version 2';
      const first=motion.play(el,[{opacity:.2},{opacity:1}],{duration:10000});
      const stateDuring=el.textContent, activeDuring=el.getAnimations().length;
      const second=motion.play(el,[{transform:'translateX(-4px)'},{transform:'translateX(0)'}],{duration:30});
      return {stateDuring,activeDuring,first:await first,second:await second,after:el.getAnimations().length,text:el.textContent};
    });
    assert.deepEqual(result,{stateDuring:'version 2',activeDuring:1,first:false,second:true,after:0,text:'version 2'});
  });
});

test('reduced motion cancels in-flight effects without holding business state', async () => {
  await fixture(async page => {
    await page.evaluate(() => {window.pending=motion.play(document.querySelector('#result'),[{opacity:.2},{opacity:1}],{duration:10000});});
    await page.emulateMedia({reducedMotion:'reduce'});
    await page.waitForFunction(() => document.querySelector('#result').getAnimations().length===0);
    assert.equal(await page.evaluate(() => pending),false);
    assert.equal(await page.evaluate(() => motion.play(document.querySelector('#result'),[{opacity:0},{opacity:1}])),false);
    await page.emulateMedia({reducedMotion:'no-preference'});
    assert.equal(await page.evaluate(() => motion.play(document.querySelector('#result'),[{opacity:.3},{opacity:1}],{duration:20})),true);
  });
});

test('dispose clears animation and detached nodes cannot keep animating', async () => {
  await fixture(async page => {
    const result=await page.evaluate(async () => {
      const el=document.querySelector('#result');const old=motion.play(el,[{opacity:.2},{opacity:1}],{duration:10000});
      motion.dispose();el.remove();
      return {old:await old,after:el.getAnimations().length,new:await motion.play(el,[{opacity:0},{opacity:1}])};
    });
    assert.deepEqual(result,{old:false,after:0,new:false});
  });
});
