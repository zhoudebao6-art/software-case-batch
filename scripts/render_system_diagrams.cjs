const fs = require('node:fs');
const path = require('node:path');
const crypto = require('node:crypto');
const options={};
for(let i=2;i<process.argv.length;i+=2){
  const key=process.argv[i];
  if(!['--input-dir','--output-dir','--mermaid-js'].includes(key)||!process.argv[i+1]||options[key])throw new Error('Use --input-dir DIR --output-dir NEW_DIR [--mermaid-js FILE]');
  options[key]=process.argv[i+1];
}
if(!options['--input-dir']||!options['--output-dir'])throw new Error('Input and new internal output directories are required');
const input=path.resolve(options['--input-dir']);
const out=path.resolve(options['--output-dir']);

function rejectLinks(target){
  for(let current=target;;current=path.dirname(current)){
    if(fs.existsSync(current)&&fs.lstatSync(current).isSymbolicLink())throw new Error('Link/reparse point not accepted: '+current);
    if(path.dirname(current)===current)break;
  }
}
for(const target of [input,out])rejectLinks(target);
for(const target of [out])if(fs.existsSync(target))throw new Error('Output exists; preserve the previous validation and choose a new directory: '+target);
const modules=process.env.SCB_PRO_NODE_MODULES;
const { chromium }=require(process.env.SCB_PRO_PLAYWRIGHT||require.resolve('playwright',{paths:[modules,__dirname].filter(Boolean)}));
const cacheRoot=process.env.SCB_PRO_CACHE_ROOT||(process.env.TEMP&&path.dirname(process.env.TEMP));
const mermaidFile=[options['--mermaid-js'],process.env.SCB_PRO_MERMAID_JS,
  modules&&path.join(modules,'mermaid','dist','mermaid.min.js'),
  cacheRoot&&path.join(cacheRoot,'cache','mermaid','mermaid.min.js')].find(file=>file&&fs.existsSync(file));
if(!mermaidFile||!fs.existsSync(mermaidFile))throw new Error('Local Mermaid browser bundle missing; set SCB_PRO_MERMAID_JS or --mermaid-js. Reuse or fetch it under the receiving host cache.');
const digest = raw => crypto.createHash('sha256').update(raw).digest('hex');
(async () => {
  const inputs=['时序图.mmd','设计图.mmd'].map(name=>{
    const file=path.join(input,name);
    if(fs.lstatSync(file).isSymbolicLink()||!fs.statSync(file).isFile())throw new Error('Expected ordinary Mermaid input: '+name);
    return {name,raw:fs.readFileSync(file)};
  });
  fs.mkdirSync(out,{recursive:true});
  const browser = await chromium.launch({headless:true});
  const checks = [];
  try {
    const page = await browser.newPage({viewport:{width:2100,height:1200},deviceScaleFactor:2});
    await page.route('**/*', route => route.abort());
    await page.setContent('<html lang="zh"><head><meta charset="utf-8"><style>body{margin:24px;background:#fff;font-family:"Microsoft YaHei",sans-serif}#diagram{display:inline-block;padding:16px;background:white}</style></head><body><div id="diagram"></div></body></html>');
    await page.addScriptTag({path:mermaidFile});
    await page.evaluate(() => mermaid.initialize({startOnLoad:false,securityLevel:'strict',theme:'neutral',htmlLabels:false,fontFamily:'Microsoft YaHei, sans-serif',flowchart:{useMaxWidth:false,htmlLabels:false},sequence:{useMaxWidth:false}}));
    for (const [index,{name,raw}] of inputs.entries()) {
      const result = await page.evaluate(async ({source,index}) => {
        const parsed = await mermaid.parse(source);
        const rendered = await mermaid.render('source_diagram_'+index,source);
        document.querySelector('#diagram').innerHTML=rendered.svg;
        await document.fonts.ready;
        const svg=document.querySelector('#diagram svg');
        const box=svg.getBoundingClientRect();
        const rect = element => {
          const r=element.getBoundingClientRect();
          return {x:r.x,y:r.y,right:r.right,bottom:r.bottom,width:r.width,height:r.height};
        };
        const intersect=(a,b) => Math.min(a.right,b.right)-Math.max(a.x,b.x)>1 && Math.min(a.bottom,b.bottom)-Math.max(a.y,b.y)>1;
        const labelSelector=parsed.diagramType==='sequence'?'text':'.cluster-label,.edgeLabel,.node .label';
        const labels=[...svg.querySelectorAll(labelSelector)]
          .filter(element=>element.textContent.trim()).map(element=>({kind:element.matches('.cluster-label')?'group-title':element.matches('.edgeLabel')?'edge-label':'node-label',text:element.textContent.trim(),box:rect(element)}));
        const nodes=[...svg.querySelectorAll('.node')].map(element=>({id:element.id,box:rect(element)}));
        const collisions=[];
        for(let a=0;a<labels.length;a++)for(let b=a+1;b<labels.length;b++) {
          if(intersect(labels[a].box,labels[b].box))collisions.push({a:labels[a].text,b:labels[b].text});
        }
        for(const label of labels.filter(x=>x.kind!=='node-label'))for(const node of nodes){
          if(intersect(label.box,node.box))collisions.push({label:label.text,node:node.id});
        }
        const canvas=rect(svg);
        const outsideCanvas=labels.filter(x=>x.box.x<canvas.x-1 || x.box.y<canvas.y-1 || x.box.right>canvas.right+1 || x.box.bottom>canvas.bottom+1).map(x=>x.text);
        const lifelines=[...svg.querySelectorAll('.actor-line')].map(rect);
        const messages=[...svg.querySelectorAll('.messageLine0,.messageLine1')].map(rect);
        const lastMessage=Math.max(0,...messages.map(x=>x.bottom));
        const truncatedLifelines=parsed.diagramType==='sequence' && (!lifelines.length||lifelines.some(x=>x.bottom<lastMessage-1));
        return {diagramType:parsed.diagramType,svg:rendered.svg,width:box.width,height:box.height,
                textNodes:svg.querySelectorAll('text').length,
                layoutChecks:{checkedLabels:labels.length,labelCollisions:collisions,outsideCanvas,truncatedLifelines}};
      }, {source:raw.toString('utf8'),index});
      if (!result.width || !result.height || result.textNodes<1) throw new Error('Empty rendered diagram: '+JSON.stringify({file:name,width:result.width,height:result.height,textNodes:result.textNodes}));
      // Geometry is diagnostic; the same first visual review decides real overlaps.


      fs.writeFileSync(path.join(out,name+'.svg'), result.svg);
      await page.locator('#diagram').screenshot({path:path.join(out,name+'.png'),timeout:30000});
      checks.push({file:name,sha256:digest(raw),parser:'mermaid',parsed:true,rendered:true,
                   diagramType:result.diagramType,width:result.width,height:result.height,textNodes:result.textNodes,layoutChecks:result.layoutChecks,
                   svg:{path:name+'.svg',sha256:digest(fs.readFileSync(path.join(out,name+'.svg')))},
                   png:{path:name+'.png',sha256:digest(fs.readFileSync(path.join(out,name+'.png')))}});
    }
  } finally {
    await browser.close();
  }
  const report={schema:1,checks,browserClosed:true,sourceUploaded:false,outputImagesInternalOnly:true,
                mermaidScriptSha256:digest(fs.readFileSync(mermaidFile)),checkerSha256:digest(fs.readFileSync(__filename))};
  fs.writeFileSync(path.join(out,'mermaid-validation.json'),JSON.stringify(report,null,2));
  console.log(JSON.stringify(report));
})().catch(error=>{console.error(error);process.exitCode=1;});
