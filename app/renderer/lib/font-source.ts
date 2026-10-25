/**
 * @fileoverview Lightweight sfnt reader that builds a FontSource from raw font bytes.
 *
 * Only the handful of tables the UI needs (name, OS/2, hhea, head, maxp, fvar)
 * are read, directly from the table directory — the glyph data is never parsed,
 * so even large CJK fonts load instantly. cmap coverage comes from HarfBuzz,
 * which the preview already uses.
 */

import type { FontRole } from '@/shared/constants';
import type { FontSource, VariableAxis } from '@/shared/types';

const AXIS_NAMES: Record<string, string> = {
  wght: 'Weight',
  wdth: 'Width',
  opsz: 'Optical Size',
  ital: 'Italic',
  slnt: 'Slant',
  GRAD: 'Grade',
};

const WEIGHT_NAMES: Record<number, string> = {
  100: 'Thin',
  200: 'ExtraLight',
  250: 'Thin',
  300: 'Light',
  350: 'DemiLight',
  400: 'Regular',
  500: 'Medium',
  600: 'SemiBold',
  700: 'Bold',
  800: 'ExtraBold',
  900: 'Black',
};

const WIDTH_NAMES: Record<number, string> = {
  1: 'UltraCondensed',
  2: 'ExtraCondensed',
  3: 'Condensed',
  4: 'SemiCondensed',
  5: '',
  6: 'SemiExpanded',
  7: 'Expanded',
  8: 'ExtraExpanded',
  9: 'UltraExpanded',
};

/** OpenType name table IDs used by the UI. */
const NAME = {
  copyright: 0,
  family: 1,
  subfamily: 2,
  version: 5,
  trademark: 7,
  manufacturer: 8,
  designer: 9,
  description: 10,
  manufacturerURL: 11,
  designerURL: 12,
  license: 13,
  licenseURL: 14,
  typographicFamily: 16,
  typographicSubfamily: 17,
} as const;

type Tables = Map<string, DataView>;

/** Raised for truncated or structurally inconsistent font files. */
class DamagedFontError extends Error {
  constructor() {
    super('The font file is damaged or truncated');
  }
}

/**
 * Reads the sfnt table directory into tag → DataView slices.
 * @param buffer - The raw font file data.
 */
function readTables(buffer: ArrayBuffer): Tables {
  const view = new DataView(buffer);
  const tag = view.getUint32(0);
  if (tag === 0x74746366 /* 'ttcf' */) throw new Error('Font collections (.ttc) are not supported');
  if (tag === 0x774f4646 /* 'wOFF' */ || tag === 0x774f4632 /* 'wOF2' */) {
    throw new Error('WOFF fonts are not supported; use .otf or .ttf');
  }
  if (tag !== 0x00010000 && tag !== 0x4f54544f /* 'OTTO' */ && tag !== 0x74727565 /* 'true' */) {
    throw new Error('Not a valid OpenType font');
  }
  const numTables = view.getUint16(4);
  if (12 + numTables * 16 > buffer.byteLength) throw new DamagedFontError();
  const tables: Tables = new Map();
  for (let i = 0; i < numTables; i++) {
    const rec = 12 + i * 16;
    const name = String.fromCharCode(
      view.getUint8(rec),
      view.getUint8(rec + 1),
      view.getUint8(rec + 2),
      view.getUint8(rec + 3),
    );
    const offset = view.getUint32(rec + 8);
    const length = view.getUint32(rec + 12);
    // A table running past the end of the file means the font is truncated.
    if (offset + length > buffer.byteLength) throw new DamagedFontError();
    tables.set(name, new DataView(buffer, offset, length));
  }
  if (!tables.has('head') || !tables.has('maxp')) throw new Error('Not a valid OpenType font');
  return tables;
}

const utf16 = new TextDecoder('utf-16be');
const macRoman = new TextDecoder('macintosh');

/**
 * Reads the language tags of the ltag table, which Unicode-platform name
 * records reference by index.
 * @param table - The ltag table, if present.
 */
function readLanguageTags(table: DataView | undefined): string[] {
  if (!table) return [];
  const count = table.getUint32(8);
  const tags: string[] = [];
  for (let i = 0; i < count; i++) {
    const offset = table.getUint16(12 + i * 4);
    const length = table.getUint16(14 + i * 4);
    if (offset + length > table.byteLength) throw new DamagedFontError();
    tags.push(
      String.fromCharCode(...new Uint8Array(table.buffer, table.byteOffset + offset, length)),
    );
  }
  return tags;
}

type NameLanguage = 'en' | 'ja' | 'other';

/**
 * Classifies a name record's language, ranking records of the same language
 * (lower wins): Windows US English / Japanese, then Mac, then the rest.
 */
function classifyName(
  platform: number,
  lang: number,
  languageTags: string[],
): [NameLanguage, number] {
  if (platform === 3) {
    if (lang === 0x0409) return ['en', 0];
    if (lang === 0x0411) return ['ja', 0];
    if ((lang & 0x3ff) === 0x09) return ['en', 2];
  } else if (platform === 1) {
    if (lang === 0) return ['en', 1];
    if (lang === 11) return ['ja', 1];
  } else if (platform === 0) {
    const tag = (languageTags[lang] ?? '').toLowerCase();
    if (tag === 'en' || tag.startsWith('en-')) return ['en', 3];
    if (tag === 'ja' || tag.startsWith('ja-')) return ['ja', 2];
  }
  return ['other', 0];
}

/**
 * Parses the name table and returns a lookup preferring English, then Japanese,
 * then whatever record exists for the requested ID.
 * @param table - The name table, if present.
 * @param languageTags - Language tags from the ltag table.
 */
function readNames(table: DataView | undefined, languageTags: string[]): (id: number) => string {
  const byId = new Map<number, Partial<Record<NameLanguage, { text: string; rank: number }>>>();
  if (table) {
    const count = table.getUint16(2);
    const storage = table.getUint16(4);
    for (let i = 0; i < count; i++) {
      const rec = 6 + i * 12;
      const platform = table.getUint16(rec);
      const encoding = table.getUint16(rec + 2);
      const lang = table.getUint16(rec + 4);
      const id = table.getUint16(rec + 6);
      const length = table.getUint16(rec + 8);
      const start = storage + table.getUint16(rec + 10);
      if (start + length > table.byteLength) throw new DamagedFontError();
      const bytes = new Uint8Array(table.buffer, table.byteOffset + start, length);
      let text: string;
      if (platform === 0 || platform === 3) text = utf16.decode(bytes);
      else if (platform === 1 && encoding === 0) text = macRoman.decode(bytes);
      else continue;
      if (!text) continue;

      const entry = byId.get(id) ?? {};
      byId.set(id, entry);
      const [language, rank] = classifyName(platform, lang, languageTags);
      const current = entry[language];
      // Keep the best-ranked record; the first one wins ties.
      if (!current || rank < current.rank) entry[language] = { text, rank };
    }
  }
  return (id) => {
    const e = byId.get(id);
    return e?.en?.text || e?.ja?.text || e?.other?.text || '';
  };
}

/**
 * Reads variation axes from the fvar table.
 * @param fvar - The fvar table, if present.
 * @param name - Name table lookup for axis labels.
 */
function readAxes(fvar: DataView | undefined, name: (id: number) => string): VariableAxis[] {
  if (!fvar) return [];
  const axesOffset = fvar.getUint16(4);
  const axisCount = fvar.getUint16(8);
  const axisSize = fvar.getUint16(10);
  const instanceCount = fvar.getUint16(12);
  const instanceSize = fvar.getUint16(14);
  // Named instances follow the axes; fontTools (the merge engine) reads them,
  // so a truncated instance array must be rejected here rather than at export.
  const axesEnd = axesOffset + axisCount * axisSize;
  if (
    axisSize < 20 ||
    axesOffset < 16 ||
    (instanceCount > 0 && instanceSize < axisCount * 4 + 4) ||
    axesEnd + instanceCount * instanceSize > fvar.byteLength
  ) {
    throw new DamagedFontError();
  }
  const fixed = (at: number) => fvar.getInt32(at) / 65536;
  const axes: VariableAxis[] = [];
  for (let i = 0; i < axisCount; i++) {
    const rec = axesOffset + i * axisSize;
    const tag = String.fromCharCode(
      fvar.getUint8(rec),
      fvar.getUint8(rec + 1),
      fvar.getUint8(rec + 2),
      fvar.getUint8(rec + 3),
    );
    const minValue = fixed(rec + 4);
    const defaultValue = fixed(rec + 8);
    const maxValue = fixed(rec + 12);
    // Default wght axis to 400 if within range
    const currentValue = tag === 'wght' && minValue <= 400 && maxValue >= 400 ? 400 : defaultValue;
    axes.push({
      tag,
      name: name(fvar.getUint16(rec + 18)) || AXIS_NAMES[tag] || tag,
      minValue,
      defaultValue,
      maxValue,
      currentValue,
    });
  }
  return axes;
}

/**
 * Picks preview sample text from the font's primary script, based on cmap coverage.
 * @param has - Returns whether the font maps a codepoint.
 */
export function detectSampleText(has: (cp: number) => boolean): string {
  // Chinese first: U+5F00 (开) is Simplified Chinese only (not in JP fonts)
  if (has(0x5f00) && !has(0x3042)) return '永字'; // Chinese
  // Kana-only fonts may lack kanji, so fall back to 'あア' when 永 is missing
  if (has(0x3042)) return has(0x6c38) ? 'あ永' : 'あア'; // Japanese (has hiragana)
  if (has(0xac00)) return '가나'; // Korean
  if (has(0x0627)) return 'أبج'; // Arabic
  if (has(0x0905)) return 'अआ'; // Devanagari
  if (has(0x0e01)) return 'กข'; // Thai
  return 'Aa';
}

/**
 * Returns true when the license string names the SIL Open Font License.
 * @param license - The nameID 13 license description.
 */
export function isOflLicense(license: string): boolean {
  const lic = license.toLowerCase();
  return (
    lic.includes('open font license') || lic.includes('openfont license') || lic.includes('ofl')
  );
}

/**
 * Builds a FontSource from raw font bytes.
 * @param buffer - The raw font file data.
 * @param path - The absolute file path of the font.
 * @param role - The font role to assign.
 * @param hasCodepoint - Returns whether the font's cmap maps a codepoint.
 */
export function describeFont(
  buffer: ArrayBuffer,
  path: string,
  role: FontRole,
  hasCodepoint: (cp: number) => boolean,
): FontSource {
  let source: Omit<FontSource, 'sampleText'>;
  try {
    source = readFontSource(buffer, path, role);
  } catch (err) {
    // Out-of-bounds reads inside a table also mean a damaged file.
    throw err instanceof RangeError ? new DamagedFontError() : err;
  }
  return { ...source, sampleText: detectSampleText(hasCodepoint) };
}

/**
 * Parses the font tables into everything but the cmap-derived sample text.
 */
function readFontSource(
  buffer: ArrayBuffer,
  path: string,
  role: FontRole,
): Omit<FontSource, 'sampleText'> {
  const tables = readTables(buffer);
  const name = readNames(tables.get('name'), readLanguageTags(tables.get('ltag')));
  const os2 = tables.get('OS/2');
  const hhea = tables.get('hhea');
  const unitsPerEm = tables.get('head')!.getUint16(18);
  const glyphCount = tables.get('maxp')!.getUint16(4);
  const axes = readAxes(tables.get('fvar'), name);
  const isVariable = axes.length > 0;

  const ascender =
    os2 && os2.byteLength >= 70
      ? os2.getInt16(68)
      : hhea
        ? hhea.getInt16(4)
        : Math.round(unitsPerEm * 0.8);
  const weightClass = os2 ? os2.getUint16(4) : 400;
  const widthClass = os2 ? os2.getUint16(6) : 5;
  const vendorID =
    os2 && os2.byteLength >= 62
      ? String.fromCharCode(os2.getUint8(58), os2.getUint8(59), os2.getUint8(60), os2.getUint8(61))
      : '';

  const familyName = name(NAME.typographicFamily) || name(NAME.family) || 'Unknown';

  // Resolve style name:
  // 1. nameID 17 (Typographic Subfamily) — most accurate for non-RIBBI
  // 2. nameID 2 (Subfamily) — only reliable for Regular/Bold/Italic/Bold Italic
  // 3. Fallback to usWeightClass name
  let weightName = name(NAME.typographicSubfamily) || name(NAME.subfamily) || 'Regular';
  if (weightName === 'Regular' && weightClass !== 400) {
    weightName = WEIGHT_NAMES[weightClass] || `W${weightClass}`;
  }
  const widthName = WIDTH_NAMES[widthClass] || '';
  // Remove width from weight name if already embedded (e.g. "SemiExpanded Black" → "Black")
  if (widthName && weightName.includes(widthName)) {
    weightName = weightName.replace(widthName, '').trim();
  }
  // Only add width to style if not already in the family name
  const widthInFamily = widthName && familyName.includes(widthName);
  const styleName = isVariable
    ? 'Variable'
    : widthName && !widthInFamily
      ? `${weightName} · ${widthName}`
      : weightName;

  return {
    path,
    role,
    familyName,
    styleName,
    unitsPerEm,
    ascender,
    glyphCount,
    baselineOffset: 0,
    scale: 1.0,
    isVariable,
    axes,
    copyright: name(NAME.copyright),
    trademark: name(NAME.trademark),
    designer: name(NAME.designer),
    designerURL: name(NAME.designerURL),
    manufacturer: name(NAME.manufacturer),
    manufacturerURL: name(NAME.manufacturerURL),
    license: name(NAME.license),
    licenseURL: name(NAME.licenseURL),
    description: name(NAME.description),
    version: name(NAME.version),
    vendorID,
  };
}
