const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const test = require('node:test');

test('trusted recording does not duplicate the browser session', () => {
  const source = fs.readFileSync(path.join(__dirname, '..', 'scripts', 'capture_page.cjs'), 'utf8');
  assert.doesNotMatch(source, /await session\(false\)/,
    'prepare_video/probe already performs the browser preflight; recording must use one bounded session');
  assert.match(source, /const raw=await session\(mode==='record'\)/);
});
