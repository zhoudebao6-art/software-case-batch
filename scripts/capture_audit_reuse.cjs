const fs = require('fs');
const path = require('path');
const crypto = require('crypto');
const digest = p => crypto.createHash('sha256').update(fs.readFileSync(p)).digest('hex');
function ownFile(root, relative) {
  if (typeof relative !== 'string' || path.isAbsolute(relative)) throw Error('Expected case-relative evidence');
  const target = fs.realpathSync(path.resolve(root, relative));
  const rel = path.relative(fs.realpathSync(root), target);
  if (rel === '..' || rel.startsWith('..'+path.sep) || path.isAbsolute(rel)) throw Error('Evidence outside case');
  return target;
}
function reuseAudit(caseDir, current) {
  try {
    const manifest = JSON.parse(fs.readFileSync(ownFile(caseDir,'evidence/artifact-manifest.json'),'utf8').replace(/^\uFEFF/,''));
    const audit = JSON.parse(fs.readFileSync(ownFile(caseDir,manifest.ui_text_audit),'utf8').replace(/^\uFEFF/,''));
    for (const old of audit.pages || []) {
      const method = old.image_text_check_method || old.check_method;
      if (old.screenshot_sha256 !== current.screenshot_sha256 || old.url !== current.url || old.state !== current.state || typeof method !== 'string' || !method.trim()) continue;
      try {
        const image = ownFile(caseDir,old.screenshot);
        if (digest(image) !== current.screenshot_sha256) continue;
        let rawText = old.dom_visible_text;
        if (typeof rawText !== 'string') {
          const rawFile = path.relative(caseDir,path.join(path.dirname(image),'browser.json'));
          const proof = JSON.parse(fs.readFileSync(ownFile(caseDir,rawFile),'utf8').replace(/^\uFEFF/,''));
          const raw = (proof.pages || []).find(p=>p.screenshot===old.screenshot && p.screenshot_sha256===old.screenshot_sha256 && p.url===old.url && p.state===old.state);
          rawText = raw && raw.visible_text;
        }
        if (rawText !== current.visible_text || typeof old.visible_text !== 'string' || !old.visible_text.startsWith(rawText)) continue;
        return {...current,visible_text:old.visible_text,dom_visible_text:current.visible_text,
          check_method:'Actual current browser DOM and screenshot; prior manual image reading reused only after identical screenshot SHA256, URL, state and raw DOM verification',
          image_text_check_method:'Prior manual image reading retained after exact screenshot SHA256, URL, state and actual raw DOM comparison; original method and source preserved in reused_image_audit. No new manual inspection claimed.',
          reused_image_audit:{screenshot:old.screenshot,screenshot_sha256:old.screenshot_sha256,check_method:method,audit:manifest.ui_text_audit}};
      } catch (_) { /* Missing or changed prior evidence never establishes coverage. */ }
    }
  } catch (_) { /* An unavailable prior audit leaves current raw browser proof intact. */ }
  return current;
}
function assertNoOwnerRepair(caseDir) {
  if (!fs.existsSync(path.join(caseDir,'evidence/repair-status.json'))) return;
  const note = JSON.parse(fs.readFileSync(ownFile(caseDir,'evidence/repair-status.json'),'utf8').replace(/^\uFEFF/,''));
  if (note.status === 'pending_owner_repair') throw Error('Pending owner repair before capture: '+(note.required_action || note.reason || 'Read evidence/repair-status.json and complete the concrete repair before recording'));
}
module.exports = {reuseAudit,assertNoOwnerRepair};
