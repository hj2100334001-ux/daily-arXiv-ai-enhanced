const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

const source = fs.readFileSync(
  path.join(__dirname, '..', 'js', 'data-config.js'),
  'utf8'
);
const context = vm.createContext({
  window: {
    location: {
      hostname: 'hj2100334001-ux.github.io',
      pathname: '/daily-arXiv-ai-enhanced/',
    },
  },
  Date,
});
vm.runInContext(`${source}\nthis.__DATA_CONFIG__ = DATA_CONFIG;`, context);

const config = context.__DATA_CONFIG__;
const first = config.getDataUrl('data/2026-07-12_AI_enhanced_Chinese.jsonl');
const second = config.getDataUrl('assets/file-list.txt');

assert.match(first, /[?&]cache=\d+$/, 'paper data URL must contain a cache-busting version');
assert.match(second, /[?&]cache=\d+$/, 'file-list URL must contain a cache-busting version');
assert.equal(
  new URL(first).searchParams.get('cache'),
  new URL(second).searchParams.get('cache'),
  'all data requests on one page load should share one cache version'
);

const indexHtml = fs.readFileSync(path.join(__dirname, '..', 'index.html'), 'utf8');
assert.match(
  indexHtml,
  /<script src="js\/data-config\.js\?v=[^"]+"><\/script>/,
  'index.html must version data-config.js so browsers load the cache-busting implementation'
);
console.log('data-config cache-busting test passed');
