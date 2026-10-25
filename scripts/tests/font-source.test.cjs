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

/** Builds an ltag table listing `tags`. */
function makeLtag(tags) {
  const strings = 12 + tags.length * 4;
  const ltag = Buffer.alloc(strings + tags.join('').length);
  ltag.writeUInt32BE(1, 0);
  ltag.writeUInt32BE(tags.length, 8);
  let at = strings;
  tags.forEach((tag, i) => {
    ltag.writeUInt16BE(at, 12 + i * 4);
    ltag.writeUInt16BE(tag.length, 14 + i * 4);
    ltag.write(tag, at, 'latin1');
    at += tag.length;
  });
  return ltag;
}

/** Builds a name table of Unicode-platform records: [languageID, nameID, text]. */
function makeName(records) {
  const strings = records.map(([, , text]) => Buffer.from(text, 'utf16le').swap16());
  const storage = 6 + records.length * 12;
  const name = Buffer.alloc(storage + strings.reduce((n, b) => n + b.length, 0));
  name.writeUInt16BE(records.length, 2);
  name.writeUInt16BE(storage, 4);
  let at = 0;
  records.forEach(([lang, id], i) => {
    const rec = 6 + i * 12;
    name.writeUInt16BE(0, rec); // Unicode platform
    name.writeUInt16BE(4, rec + 2);
    name.writeUInt16BE(lang, rec + 4);
    name.writeUInt16BE(id, rec + 6);
    name.writeUInt16BE(strings[i].length, rec + 8);
    name.writeUInt16BE(at, rec + 10);
    name.set(strings[i], storage + at);
    at += strings[i].length;
  });
  return name;
}

/** Returns a copy of one table's bytes from a real font. */
function extractTable(buffer, tag) {
  const view = new DataView(buffer);
  for (let i = 0; i < view.getUint16(4); i++) {
    const rec = 12 + i * 16;
    if (String.fromCharCode(...new Uint8Array(buffer, rec, 4)) === tag) {
      return Buffer.from(new Uint8Array(buffer, view.getUint32(rec + 8), view.getUint32(rec + 12)));
    }
  }
  throw new Error(`no ${tag} table`);
}

function minimalFont(extra) {
  const head = Buffer.alloc(54);
  head.writeUInt16BE(1000, 18);
  return buildSfnt({ head, maxp: Buffer.alloc(6), ...extra });
}

const describeBuffer = (buffer) => describeFont(buffer, 'x', 'base', () => false);

test('Unicode-platform names resolve their language through ltag', () => {
  // ltag lists 'ja' first, so an index-order pick would choose the Japanese record.
  const font = describeBuffer(minimalFont({
    ltag: makeLtag(['ja', 'en']),
    name: makeName([
      [0, 13, 'フォントのライセンス'],
      [1, 13, 'SIL Open Font License 1.1'],
      [1, 1, 'Test Family'],
    ]),
  }));
  assert.equal(font.license, 'SIL Open Font License 1.1');
  assert.equal(font.familyName, 'Test Family');
  assert.ok(isOflLicense(font.license));
});

test('files that are not OpenType or are cut short are rejected', () => {
  const variable = readBuffer('Inter-4.1/InterVariable.ttf');
  const view = new DataView(variable);
  let fvarOffset = 0;
  for (let i = 0; i < view.getUint16(4); i++) {
    if (String.fromCharCode(...new Uint8Array(variable, 12 + i * 16, 4)) === 'fvar') {
      fvarOffset = view.getUint32(12 + i * 16 + 8);
    }
  }
  assert.ok(fvarOffset > 0);
  // The fvar table now runs past the end of the file.
  assert.throws(() => describeBuffer(variable.slice(0, fvarOffset + 10)), /damaged or truncated/);

  const unknown = readBuffer('Noto_Sans_JP/NotoSansJP-subset.ttf');
  new Uint8Array(unknown).set([0x78, 0x78, 0x78, 0x78], 0); // 'xxxx'
  assert.throws(() => describeBuffer(unknown), /Not a valid OpenType font/);
  assert.throws(() => describeBuffer(new TextEncoder().encode('wOF2xxxxxxxxxxxx').buffer), /WOFF/);
});

test('tables whose contents overflow their own bounds are rejected', () => {
  // Each table fits inside the file, but its internal records do not fit inside the table.
  const fvar = extractTable(readBuffer('Inter-4.1/InterVariable.ttf'), 'fvar');
  const axesEnd = fvar.readUInt16BE(4) + fvar.readUInt16BE(8) * fvar.readUInt16BE(10);
  assert.ok(fvar.readUInt16BE(12) > 0, 'fixture should declare named instances');
  const cases = {
    'fvar missing its named instances': { fvar: fvar.subarray(0, axesEnd) },
    'fvar header cut short': { fvar: fvar.subarray(0, 12) },
    // A following table keeps the overflowing string inside the file.
    'name string past the table': { name: makeName([[0, 1, 'Family']]).subarray(0, 20), zzzz: Buffer.alloc(32) },
    'name record array past the table': { name: makeName([[0, 1, 'A'], [0, 2, 'B']]).subarray(0, 20) },
    'ltag tag range past the table': { ltag: makeLtag(['en']).subarray(0, 16) },
  };
  for (const [label, tables] of Object.entries(cases)) {
    assert.throws(() => describeBuffer(minimalFont(tables)), /damaged or truncated/, label);
  }
  // Empty strings and zero-length unknown tables are still fine.
  const ok = describeBuffer(minimalFont({ name: makeName([[0, 1, '']]), zzzz: Buffer.alloc(0) }));
  assert.equal(ok.familyName, 'Unknown');
});

test('errors from the cmap callback are not reported as file damage', () => {
  const buffer = readBuffer('Noto_Sans_JP/NotoSansJP-subset.ttf');
  assert.throws(() => describeFont(buffer, 'x', 'base', () => { throw new RangeError('callback'); }), /callback/);
});

test('recognises OFL license strings', () => {
  assert.ok(isOflLicense('This Font Software is licensed under the SIL Open Font License, Version 1.1.'));
  assert.equal(isOflLicense('All rights reserved'), false);
});
