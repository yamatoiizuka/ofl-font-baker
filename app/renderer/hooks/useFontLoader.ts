/**
 * @fileoverview React hook for loading font files, parsing metadata with opentype.js, and extracting variable axes.
 */

import { useCallback } from 'react';
import opentype from 'opentype.js';
import { FontSource, VariableAxis } from '@/shared/types';
import { useMergeStore } from '@/renderer/stores/mergeStore';

const AXIS_NAMES: Record<string, string> = {
  wght: 'Weight',
  wdth: 'Width',
  opsz: 'Optical Size',
  ital: 'Italic',
  slnt: 'Slant',
  GRAD: 'Grade',
};

const FONT_EXTENSIONS = ['.otf', '.ttf'];

/**
 * Provides font loading utilities including file picker and drag-and-drop support.
 * @returns An object with pickAndLoadFont and handleDrop callbacks.
 */
export function useFontLoader() {
  const setLatinFont = useMergeStore((s) => s.setLatinFont);
  const setBaseFont = useMergeStore((s) => s.setBaseFont);

  /**
   * Loads a font from a file path, parses its metadata, validates OFL license, and updates the store.
   * @param role - The font role to assign ('latin' or 'base').
   * @param filePath - The absolute file path of the font to load.
   */
  const loadFontFromPath = useCallback(
    async (role: 'latin' | 'base', filePath: string) => {
      try {
        const buffer = await window.electronAPI.readFontFile(filePath);
        const font = opentype.parse(buffer);

        // Detect variable font axes
        let isVariable = false;
        let axes: VariableAxis[] = [];
        try {
          const fvar = (font as any).tables?.fvar;
          if (fvar && Array.isArray(fvar.axes) && fvar.axes.length > 0) {
            isVariable = true;
            axes = fvar.axes.map((a: any) => {
              // Default wght axis to 400 if within range
              let currentValue = a.defaultValue;
              if (a.tag === 'wght' && a.minValue <= 400 && a.maxValue >= 400) {
                currentValue = 400;
              }
              return {
                tag: a.tag,
                name: a.name?.en || AXIS_NAMES[a.tag] || a.tag,
                minValue: a.minValue,
                defaultValue: a.defaultValue,
                maxValue: a.maxValue,
                currentValue,
              };
            });
          }
        } catch {
          // Fallback: treat as static
        }

        // Check OFL license
        const licenseText = font.names.license?.en || font.names.license?.ja || '';
        const copyright = font.names.copyright?.en || font.names.copyright?.ja || '';
        const licenseURL = font.names.licenseURL?.en || '';
        console.log(`[Font] ${font.names.fontFamily?.en || font.names.fontFamily?.ja}`);
        console.log(`  Copyright: ${copyright || 'N/A'}`);
        console.log(`  License: ${licenseText || 'N/A'}`);
        console.log(`  License URL: ${licenseURL || 'N/A'}`);
        const lic = licenseText.toLowerCase();
        if (
          !lic.includes('open font license') &&
          !lic.includes('openfont license') &&
          !lic.includes('ofl')
        ) {
          window.electronAPI.showAlert?.('Unsupported license', 'This font is not licensed under the SIL Open Font License (OFL) and cannot be loaded.');
          return;
        }

        // Read ascender from OS/2 table (sTypoAscender) or hhea
        const os2 = (font as any).tables?.os2;
        const hhea = (font as any).tables?.hhea;
        const ascender = os2?.sTypoAscender ?? hhea?.ascender ?? Math.round(font.unitsPerEm * 0.8);

        // Detect primary script from cmap coverage
        const has = (cp: number) => {
          try {
            return font.charToGlyph(String.fromCodePoint(cp)).index > 0;
          } catch {
            return false;
          }
        };
        let sampleText = 'Aa';
        // Chinese first: U+5F00 (开) is Simplified Chinese only (not in JP fonts)
        if (has(0x5f00) && !has(0x3042))
          sampleText = '永字'; // Chinese
        else if (has(0x3042))
          // Kana-only fonts may lack kanji, so fall back to 'あア' when 永 is missing
          sampleText = has(0x6c38) ? 'あ永' : 'あア'; // Japanese (has hiragana)
        else if (has(0xac00))
          sampleText = '가나'; // Korean
        else if (has(0x0627))
          sampleText = 'أبج'; // Arabic
        else if (has(0x0905))
          sampleText = 'अआ'; // Devanagari
        else if (has(0x0e01)) sampleText = 'กข'; // Thai

        const getStr = (field: any): string => {
          if (!field) return '';
          if (typeof field === 'string') return field;
          return field.en || field.ja || Object.values(field)[0] || '';
        };

        // Resolve style name:
        // 1. nameID 17 (Typographic Subfamily) — most accurate for non-RIBBI
        // 2. nameID 2 (Subfamily) — only reliable for Regular/Bold/Italic/Bold Italic
        // 3. Fallback to usWeightClass name
        const WEIGHT_NAMES: Record<number, string> = {
          100: 'Thin', 200: 'ExtraLight', 250: 'Thin', 300: 'Light',
          350: 'DemiLight', 400: 'Regular',
          500: 'Medium', 600: 'SemiBold', 700: 'Bold', 800: 'ExtraBold', 900: 'Black',
        };
        const WIDTH_NAMES: Record<number, string> = {
          1: 'UltraCondensed', 2: 'ExtraCondensed', 3: 'Condensed',
          4: 'SemiCondensed', 5: '', 6: 'SemiExpanded',
          7: 'Expanded', 8: 'ExtraExpanded', 9: 'UltraExpanded',
        };
        const nameID17 = font.names.preferredSubfamily?.en || font.names.preferredSubfamily?.ja || '';
        const nameID2 = font.names.fontSubfamily?.en || 'Regular';
        const weightClass = os2?.usWeightClass ?? 400;
        const widthClass = os2?.usWidthClass ?? 5;

        // Build style name from best available source
        let weightName = nameID17 || nameID2;
        if (weightName === 'Regular' && weightClass !== 400) {
          weightName = WEIGHT_NAMES[weightClass] || `W${weightClass}`;
        }
        const familyNameResolved = font.names.preferredFamily?.en || font.names.preferredFamily?.ja
          || font.names.fontFamily?.en || font.names.fontFamily?.ja || 'Unknown';
        const widthName = WIDTH_NAMES[widthClass] || '';
        // Remove width from weight name if already embedded (e.g. "SemiExpanded Black" → "Black")
        if (widthName && weightName.includes(widthName)) {
          weightName = weightName.replace(widthName, '').trim();
        }
        // Only add width to style if not already in the family name
        const widthInFamily = widthName && familyNameResolved.includes(widthName);
        const styleName = isVariable
          ? 'Variable'
          : (widthName && !widthInFamily)
            ? `${weightName} \u00b7 ${widthName}`
            : weightName;

        const source: FontSource = {
          path: filePath,
          role,
          familyName: font.names.preferredFamily?.en || font.names.preferredFamily?.ja
            || font.names.fontFamily?.en || font.names.fontFamily?.ja || 'Unknown',
          styleName,
          unitsPerEm: font.unitsPerEm,
          ascender,
          glyphCount: font.numGlyphs,
          sampleText,
          baselineOffset: 0,
          scale: 1.0,
          isVariable,
          axes,
          copyright: getStr(font.names.copyright),
          trademark: getStr(font.names.trademark),
          designer: getStr(font.names.designer),
          designerURL: getStr(font.names.designerURL),
          manufacturer: getStr(font.names.manufacturer),
          manufacturerURL: getStr(font.names.manufacturerURL),
          license: getStr(font.names.license),
          licenseURL: getStr(font.names.licenseURL),
          description: getStr(font.names.description),
          version: getStr(font.names.version),
        };

        if (role === 'latin') {
          setLatinFont(source);
        } else {
          setBaseFont(source);
        }
      } catch (err) {
        console.error('Failed to load font:', err);
        window.electronAPI.showAlert?.('Failed to load font', String(err));
      }
    },
    [setLatinFont, setBaseFont],
  );

  /**
   * Opens a native file picker dialog and loads the selected font.
   * @param role - The font role to assign ('latin' or 'base').
   */
  const pickAndLoadFont = useCallback(
    async (role: 'latin' | 'base') => {
      const filePath = await window.electronAPI.pickFont();
      if (!filePath) return;
      await loadFontFromPath(role, filePath);
    },
    [loadFontFromPath],
  );

  /**
   * Handles a drag-and-drop event, extracts the font file, and loads it.
   * @param role - The font role to assign ('latin' or 'base').
   * @param e - The React drag event from the drop zone.
   */
  const handleDrop = useCallback(
    async (role: 'latin' | 'base', e: React.DragEvent) => {
      e.preventDefault();
      e.stopPropagation();

      const files = Array.from(e.dataTransfer.files);
      const fontFile = files.find((f) =>
        FONT_EXTENSIONS.some((ext) => f.name.toLowerCase().endsWith(ext)),
      );

      if (!fontFile) {
        window.electronAPI.showAlert?.('Unsupported format', 'Please use OpenType (.otf) or TrueType (.ttf) fonts.');
        return;
      }

      // Use Electron's webUtils.getPathForFile() via preload bridge
      // This works in sandboxed mode (Electron 29+)
      const filePath = window.electronAPI.getPathForFile(fontFile);
      if (!filePath) return;

      await loadFontFromPath(role, filePath);
    },
    [loadFontFromPath],
  );

  return { pickAndLoadFont, handleDrop };
}
