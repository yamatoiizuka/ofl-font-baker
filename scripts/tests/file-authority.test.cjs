const { test } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const loadTs = require('./load-ts.cjs');
const { FileAuthority } = loadTs('app/main/file-authority.ts');
function setup(t) {
  const root = fs.realpathSync(fs.mkdtempSync(path.join(os.tmpdir(), 'font-authority-')));
  t.after(() => fs.rmSync(root, { recursive: true, force: true }));
  const font = path.join(root, 'input.ttf');
  fs.writeFileSync(font, 'font bytes');
  const registry = path.join(root, 'grants.json');
  return { root, font, registry, authority: new FileAuthority(registry) };
}
test('unselected files cannot be read; grants survive restart', t => {
  const { font, registry, authority } = setup(t);
  assert.throws(() => authority.readInput(font), /select this font again/);
  authority.grantInput(font);
  assert.equal(authority.readInput(font).toString(), 'font bytes');
  assert.equal(new FileAuthority(registry).readInput(font).toString(), 'font bytes');
});
test('replaced input and redirected symlink are denied', t => {
  const { root, font, authority } = setup(t);
  authority.grantInput(font);
  fs.renameSync(font, font + '.old');
  fs.writeFileSync(font, 'new inode');
  assert.throws(() => authority.readInput(font), /select this font again/);
  fs.unlinkSync(font);
  const other = path.join(root, 'other.ttf');
  fs.writeFileSync(other, 'other bytes');
  fs.symlinkSync(other, font);
  assert.throws(() => authority.readInput(font), /select this font again/);
});
test('export needs a matching single-use save grant', t => {
  const { root, authority } = setup(t);
  const output = path.join(root, 'Output');
  assert.throws(() => authority.consumeOutput(output, []), /Choose/);
  authority.grantOutput(output);
  assert.equal(authority.consumeOutput(output, []).overwrite, false);
  assert.throws(() => authority.consumeOutput(output, []), /Choose/);
  authority.grantOutput(output);
  assert.throws(() => authority.consumeOutput(output + '-other', []), /Choose/);
  assert.throws(() => authority.consumeOutput(output, []), /Choose/);
});
test('newly appeared destination cannot gain overwrite permission', t => {
  const { root, authority } = setup(t);
  const output = path.join(root, 'Output');
  authority.grantOutput(output);
  fs.mkdirSync(output);
  assert.throws(() => authority.consumeOutput(output, []), /changed/);
});
test('input-containing and symlink destinations are rejected', t => {
  const { root, font, authority } = setup(t);
  authority.grantOutput(root);
  assert.throws(() => authority.consumeOutput(root, [font]), /contain an input/);
  const link = path.join(root, 'link');
  fs.symlinkSync(root, link);
  assert.throws(() => authority.grantOutput(link), /regular export folder/);
});
test('native-approved existing destination gets overwrite; cancellation revokes it', t => {
  const { root, authority } = setup(t);
  const output = path.join(root, 'Output');
  fs.mkdirSync(output);
  authority.grantOutput(output);
  assert.equal(authority.consumeOutput(output, []).overwrite, true);
  authority.grantOutput(output);
  authority.clearOutput();
  assert.throws(() => authority.consumeOutput(output, []), /Choose/);
});
