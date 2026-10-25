const { test } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const loadTs = require('./load-ts.cjs');
const { describeFont, isOflLicense } = loadTs('app/renderer/lib/font-source.ts');
const hbReady = require('harfbuzzjs');
const FONTS = 'python/tests/fonts';

async function describe(file) {
  const bytes = fs.readFileSync(path.join(FONTS, file));
  const buffer = bytes.buffer.slice(bytes.byteOffset, bytes.byteOffset + bytes.byteLength);
  const hb = await hbReady;
  const blob = hb.createBlob(new Uint8Array(buffer));
  const face = hb.createFace(blob, 0);
  const codepoints = new Set(face.collectUnicodes());
  face.destroy();
  blob.destroy();
  return describeFont(buffer, file, 'base', (cp) => codepoints.has(cp));
}

test('static CJK font: names, metrics and Japanese sample text', async () => {
  const font = await describe('Noto_Sans_JP/NotoSansJP-Regular.ttf');
  assert.equal(font.familyName, 'Noto Sans JP');
  assert.equal(font.styleName, 'Regular');
  assert.equal(font.unitsPerEm, 1000);
  assert.equal(font.ascender, 880);
  assert.equal(font.sampleText, 'あ永');
  assert.equal(font.isVariable, false);
  assert.ok(font.glyphCount > 10000);
  assert.ok(isOflLicense(font.license));
});

test('variable font: fvar axes with wght defaulting to 400', async () => {
  const font = await describe('Inter-4.1/InterVariable.ttf');
  assert.equal(font.styleName, 'Variable');
  assert.equal(font.sampleText, 'Aa');
  assert.equal(font.axes.map((a) => a.tag).join(), 'opsz,wght');
  const wght = font.axes.find((a) => a.tag === 'wght');
  assert.equal(wght.name, 'Weight');
  assert.equal(wght.currentValue, 400);
  assert.ok(wght.minValue < 400 && wght.maxValue > 400);
});

test('CFF CID font and non-Latin script detection', async () => {
  const cid = await describe('NotoSansCJKjp/NotoSansCJKjp-subset.otf');
  assert.equal(cid.familyName, 'Noto Sans CJK JP');
  assert.equal((await describe('Lateef/Lateef-Regular.ttf')).sampleText, 'أبج');
});

test('rejects non-sfnt data and recognises OFL license strings', () => {
  assert.throws(() => describeFont(new TextEncoder().encode('wOF2xxxxxxxxxxxx').buffer, 'x', 'base', () => false), /WOFF/);
  assert.ok(isOflLicense('This Font Software is licensed under the SIL Open Font License, Version 1.1.'));
  assert.equal(isOflLicense('All rights reserved'), false);
});
