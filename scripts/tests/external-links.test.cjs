const { test } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const ts = require('typescript');
const exportsObject = {};
const opened = [];
vm.runInNewContext(ts.transpileModule(fs.readFileSync('app/main/external-links.ts', 'utf8'), {
  compilerOptions: { module: ts.ModuleKind.CommonJS },
}).outputText, { exports: exportsObject, URL, require: () => ({ shell: { openExternal: async url => opened.push(url) } }) });
test('only web links reach the OS handler', async () => {
  for (const url of ['file:///etc/passwd', 'javascript:alert(1)', 'data:text/html,test', 'mailto:x@example.com', 'custom:command', 'https://user:password@example.com', 'invalid', null]) {
    await assert.rejects(exportsObject.openExternalWebURL(url));
  }
  assert.equal(opened.length, 0);
  await exportsObject.openExternalWebURL('https://example.com/font');
  await exportsObject.openExternalWebURL('http://example.com/');
  assert.deepEqual(opened, ['https://example.com/font', 'http://example.com/']);
});
