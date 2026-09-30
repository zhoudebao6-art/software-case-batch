// Observe actual animation frames; never change application DOM or hide loading.
function installMonitor({name, modules}) {
  if (window[name+'State']) window[name+'State'].active=false;
  const state=window[name+'State']={active:true,pending:Promise.resolve()};
  const visible=element=>{
    const style=getComputedStyle(element), rect=element.getBoundingClientRect();
    return rect.width>0 && rect.height>0 && style.display!=='none' && style.visibility!=='hidden' && Number(style.opacity)!==0;
  };
  const normalize=text=>text.replace(/\s+/g,' ').trim();
  const sample=()=>{
    if(!state.active) return;
    const ready=modules.some(module=>
      [...document.querySelectorAll('h1')].some(h=>visible(h)&&normalize(h.textContent)===normalize(module.heading)) &&
      module.ready_selectors.every(selector=>[...document.querySelectorAll(selector)].some(visible)));
    state.pending=window[name]({at_ms:performance.now(),url:location.href,ready});
    requestAnimationFrame(sample);
  };
  requestAnimationFrame(sample);
}

function summarize(samples) {
  const bad=samples.filter(row=>!row.ready);
  return {ok:samples.length>0 && !bad.length, observed_frames:samples.length,
    missing_content_frames:bad.length, first_missing_frames:bad.slice(0,8),
    limitation:'DOM readiness across painted frames only; actual screenshots and video still require visual review.'};
}

async function watchTransition(page, modules) {
  const name='__caseflowTransitionFrame', samples=[];
  await page.exposeFunction(name, row=>{samples.push(row);});
  const args={name,modules};
  // New documents during a real navigation are observed too.
  await page.addInitScript(installMonitor,args);
  await page.evaluate(installMonitor,args);
  return async()=>{
    await page.evaluate(()=>new Promise(resolve=>requestAnimationFrame(()=>requestAnimationFrame(resolve))));
    await page.evaluate(async name=>{
      const state=window[name+'State'];
      if(state) { state.active=false; await state.pending; }
    },name);
    return summarize(samples);
  };
}
module.exports={installMonitor,summarize,watchTransition};
