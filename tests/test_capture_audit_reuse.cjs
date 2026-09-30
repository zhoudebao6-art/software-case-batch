const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('fs');
const os = require('os');
const path = require('path');
const crypto = require('crypto');
const {reuseAudit} = require('../scripts/capture_audit_reuse.cjs');
function fixture(fn) {
  const root=fs.mkdtempSync(path.join(os.tmpdir(),'capture-audit-'));
  try {
    fs.mkdirSync(path.join(root,'evidence')); fs.mkdirSync(path.join(root,'recording'));
    const bytes=Buffer.from('exact screenshot fixture');
    fs.writeFileSync(path.join(root,'recording/old.png'),bytes);
    const sha=crypto.createHash('sha256').update(bytes).digest('hex');
    const raw={url:'http://127.0.0.1:18168/analysis',state:'分区分析',screenshot:'recording/old.png',screenshot_sha256:sha,visible_text:'当前DOM'};
    const audited={...raw,visible_text:'当前DOM\n轴名、刻度及图例',image_text_check_method:'Actual screenshot manually read'};
    const write=()=>{
      fs.writeFileSync(path.join(root,'evidence/artifact-manifest.json'),JSON.stringify({ui_text_audit:'evidence/audit.json'}));
      fs.writeFileSync(path.join(root,'evidence/audit.json'),JSON.stringify({pages:[audited]}));
      fs.writeFileSync(path.join(root,'recording/browser.json'),JSON.stringify({pages:[raw]}));
    };
    write(); fn({root,raw,audited,write,current:{...raw,screenshot:'recording/new.png'}});
  } finally { fs.rmSync(root,{recursive:true,force:true}); }
}
test('same raster and actual DOM preserve existing manual image reading with provenance',()=>fixture(({root,current})=>{
  const got=reuseAudit(root,current);
  assert.equal(got.visible_text,'当前DOM\n轴名、刻度及图例');
  assert.equal(got.dom_visible_text,'当前DOM');
  assert.equal(got.reused_image_audit.screenshot,'recording/old.png');
  assert.match(got.check_method,/SHA256/);
}));
for(const key of ['url','state','visible_text','screenshot_sha256']) test(`changed ${key} cannot reuse`,()=>fixture(({root,current})=>{
  current[key]+='changed'; assert.deepEqual(reuseAudit(root,current),current);
}));
test('changed candidate bytes cannot reuse',()=>fixture(({root,current})=>{
  fs.writeFileSync(path.join(root,'recording/old.png'),'altered'); assert.deepEqual(reuseAudit(root,current),current);
}));
test('missing manual method cannot reuse',()=>fixture(({root,current,audited,write})=>{
  delete audited.image_text_check_method; write(); assert.deepEqual(reuseAudit(root,current),current);
}));
test('missing raw proof cannot reuse raster supplement',()=>fixture(({root,current})=>{
  fs.unlinkSync(path.join(root,'recording/browser.json')); assert.deepEqual(reuseAudit(root,current),current);
}));
test('evidence outside case is ignored',()=>fixture(({root,current})=>{
  fs.writeFileSync(path.join(root,'evidence/artifact-manifest.json'),JSON.stringify({ui_text_audit:'../../audit.json'}));
  assert.deepEqual(reuseAudit(root,current),current);
}));
