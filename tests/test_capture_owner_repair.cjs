const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('fs');
const os = require('os');
const path = require('path');
const {assertNoOwnerRepair} = require('../scripts/capture_audit_reuse.cjs');
function fixture(fn) {
  const root=fs.mkdtempSync(path.join(os.tmpdir(),'capture-owner-'));
  try { fs.mkdirSync(path.join(root,'evidence')); fn(root); }
  finally { fs.rmSync(root,{recursive:true,force:true}); }
}
test('pending concrete owner repair prevents capture and carries actual instruction',()=>fixture(root=>{
  fs.writeFileSync(path.join(root,'evidence/repair-status.json'),JSON.stringify({status:'pending_owner_repair',required_action:'Fix exact threshold form without rounding'}));
  assert.throws(()=>assertNoOwnerRepair(root),/Fix exact threshold form without rounding/);
}));
test('ready status with historical instruction does not block capture',()=>fixture(root=>{
  fs.writeFileSync(path.join(root,'evidence/repair-status.json'),JSON.stringify({status:'ready_for_review',required_action:'Historical instruction'}));
  assert.doesNotThrow(()=>assertNoOwnerRepair(root));
}));
test('no advisory preserves normal capture',()=>fixture(root=>assert.doesNotThrow(()=>assertNoOwnerRepair(root))));
test('malformed advisory fails visibly instead of silently claiming readiness',()=>fixture(root=>{
  fs.writeFileSync(path.join(root,'evidence/repair-status.json'),'{');
  assert.throws(()=>assertNoOwnerRepair(root));
}));
