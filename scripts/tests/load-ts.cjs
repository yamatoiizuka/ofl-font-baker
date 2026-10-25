// Loads a self-contained TypeScript module for node:test by transpiling it to
// CommonJS and evaluating it in a fresh context. `globals` can stub `require`.
const fs = require('node:fs');
const vm = require('node:vm');
const ts = require('typescript');

module.exports = function loadTs(file, globals = {}) {
  const exports = {};
  const { outputText } = ts.transpileModule(fs.readFileSync(file, 'utf8'), {
    compilerOptions: { module: ts.ModuleKind.CommonJS, esModuleInterop: true, target: ts.ScriptTarget.ES2020 },
  });
  vm.runInNewContext(outputText, { exports, require, Buffer, URL, TextDecoder, ...globals });
  return exports;
};
