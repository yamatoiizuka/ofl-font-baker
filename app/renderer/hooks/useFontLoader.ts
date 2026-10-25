/**
 * @fileoverview React hook for loading font files, reading their metadata, and validating the OFL license.
 */

import { useCallback } from 'react';
import { FontRole } from '@/shared/constants';
import { useMergeStore } from '@/renderer/stores/mergeStore';
import { describeFont, isOflLicense } from '@/renderer/lib/font-source';
import { getHB } from '@/renderer/lib/hb-renderer';

const FONT_EXTENSIONS = ['.otf', '.ttf'];

/**
 * Collects the Unicode codepoints mapped by a font's cmap via HarfBuzz.
 * @param buffer - The raw font file data.
 */
async function collectCodepoints(buffer: ArrayBuffer): Promise<Set<number>> {
  const hb = await getHB();
  const blob = hb.createBlob(new Uint8Array(buffer));
  const face = hb.createFace(blob, 0);
  try {
    return new Set<number>(face.collectUnicodes());
  } finally {
    face.destroy();
    blob.destroy();
  }
}

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
    async (role: FontRole, filePath: string) => {
      try {
        const buffer = await window.electronAPI.readFontFile(filePath);
        const codepoints = await collectCodepoints(buffer);
        const source = describeFont(buffer, filePath, role, (cp) => codepoints.has(cp));

        if (!isOflLicense(source.license ?? '')) {
          window.electronAPI.showAlert?.(
            'Unsupported license',
            'This font is not licensed under the SIL Open Font License (OFL) and cannot be loaded.',
          );
          return;
        }

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
    async (role: FontRole) => {
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
    async (role: FontRole, e: React.DragEvent) => {
      e.preventDefault();
      e.stopPropagation();

      const files = Array.from(e.dataTransfer.files);
      const fontFile = files.find((f) =>
        FONT_EXTENSIONS.some((ext) => f.name.toLowerCase().endsWith(ext)),
      );

      if (!fontFile) {
        window.electronAPI.showAlert?.(
          'Unsupported format',
          'Please use OpenType (.otf) or TrueType (.ttf) fonts.',
        );
        return;
      }

      // Use Electron's webUtils.getPathForFile() via preload bridge
      // This works in sandboxed mode (Electron 29+)
      try {
        const filePath = await window.electronAPI.getPathForFile(fontFile);
        if (!filePath) return;
        await loadFontFromPath(role, filePath);
      } catch (error) {
        window.electronAPI.showAlert?.('Failed to load font', String(error));
      }
    },
    [loadFontFromPath],
  );

  return { pickAndLoadFont, handleDrop };
}
