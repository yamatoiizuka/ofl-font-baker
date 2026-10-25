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

function readBuffer(file) {
  const bytes = fs.readFileSync(path.join(FONTS, file));
  return bytes.buffer.slice(bytes.byteOffset, bytes.byteOffset + bytes.byteLength);
}

/** Builds a minimal sfnt from { tag: Uint8Array } (head/maxp only need their size). */
function buildSfnt(tables) {
  const tags = Object.keys(tables).sort();
  let offset = 12 + tags.length * 16;
  const out = Buffer.alloc(offset + tags.reduce((n, t) => n + tables[t].length, 0));
  out.writeUInt32BE(0x00010000, 0);
  out.writeUInt16BE(tags.length, 4);
  tags.forEach((tag, i) => {
    out.write(tag, 12 + i * 16, 'latin1');
    out.writeUInt32BE(offset, 12 + i * 16 + 8);
    out.writeUInt32BE(tables[tag].length, 12 + i * 16 + 12);
    out.set(tables[tag], offset);
    offset += tables[tag].length;
  });
  return out.buffer.slice(out.byteOffset, out.byteOffset + out.byteLength);
}

test('Unicode-platform names resolve their language through ltag', () => {
  // ltag lists 'ja' first, so an index-order pick would choose the Japanese record.
  const ltagTags = ['ja', 'en'];
  const ltag = Buffer.alloc(12 + ltagTags.length * 4 + 4);
  ltag.writeUInt32BE(1, 0);
  ltag.writeUInt32BE(ltagTags.length, 8);
  ltagTags.forEach((tag, i) => {
    ltag.writeUInt16BE(12 + ltagTags.length * 4 + i * 2, 12 + i * 4);
    ltag.writeUInt16BE(2, 14 + i * 4);
    ltag.write(tag, 12 + ltagTags.length * 4 + i * 2, 'latin1');
  });
  const records = [
    [0, 13, 'フォントのライセンス'],
    [1, 13, 'SIL Open Font License 1.1'],
    [1, 1, 'Test Family'],
  ];
  const strings = records.map(([, , text]) => Buffer.from(text, 'utf16le').swap16());
  const name = Buffer.alloc(6 + records.length * 12 + strings.reduce((n, b) => n + b.length, 0));
  name.writeUInt16BE(records.length, 2);
  name.writeUInt16BE(6 + records.length * 12, 4);
  let at = 0;
  records.forEach(([lang, id], i) => {
    const rec = 6 + i * 12;
    name.writeUInt16BE(0, rec); // Unicode platform
    name.writeUInt16BE(4, rec + 2);
    name.writeUInt16BE(lang, rec + 4);
    name.writeUInt16BE(id, rec + 6);
    name.writeUInt16BE(strings[i].length, rec + 8);
    name.writeUInt16BE(at, rec + 10);
    name.set(strings[i], 6 + records.length * 12 + at);
    at += strings[i].length;
  });
  const head = Buffer.alloc(54);
  head.writeUInt16BE(1000, 18);
  const font = describeFont(buildSfnt({ head, maxp: Buffer.alloc(6), name, ltag }), 'x', 'base', () => false);
  assert.equal(font.license, 'SIL Open Font License 1.1');
  assert.equal(font.familyName, 'Test Family');
  assert.ok(isOflLicense(font.license));
});

test('damaged or non-OpenType data is rejected', () => {
  const variable = readBuffer('Inter-4.1/InterVariable.ttf');
  // Truncate the file inside the fvar table.
  const view = new DataView(variable);
  let fvarOffset = 0;
  for (let i = 0; i < view.getUint16(4); i++) {
    if (String.fromCharCode(...new Uint8Array(variable, 12 + i * 16, 4)) === 'fvar') {
      fvarOffset = view.getUint32(12 + i * 16 + 8);
    }
  }
  assert.ok(fvarOffset > 0);
  assert.throws(() => describeFont(variable.slice(0, fvarOffset + 10), 'x', 'base', () => false), /damaged or truncated/);

  const unknown = readBuffer('Noto_Sans_JP/NotoSansJP-subset.ttf');
  new Uint8Array(unknown).set([0x78, 0x78, 0x78, 0x78], 0); // 'xxxx'
  assert.throws(() => describeFont(unknown, 'x', 'base', () => false), /Not a valid OpenType font/);
  assert.throws(() => describeFont(new TextEncoder().encode('wOF2xxxxxxxxxxxx').buffer, 'x', 'base', () => false), /WOFF/);
});

test('recognises OFL license strings', () => {
  assert.ok(isOflLicense('This Font Software is licensed under the SIL Open Font License, Version 1.1.'));
  assert.equal(isOflLicense('All rights reserved'), false);
});
