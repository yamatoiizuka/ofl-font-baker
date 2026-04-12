/**
 * @fileoverview Shared constants used across renderer and main processes.
 */

/** Font role type alias used throughout the application. */
export type FontRole = 'latin' | 'base';

/** Weight value-to-name mapping for font export and display. */
export const WEIGHT_MAP = [
  { value: 100, name: 'Thin', label: '100\u2009-\u2009Thin' },
  { value: 200, name: 'ExtraLight', label: '200\u2009-\u2009Extra Light' },
  { value: 300, name: 'Light', label: '300\u2009-\u2009Light' },
  { value: 400, name: 'Regular', label: '400\u2009-\u2009Regular' },
  { value: 500, name: 'Medium', label: '500\u2009-\u2009Medium' },
  { value: 600, name: 'SemiBold', label: '600\u2009-\u2009Semi Bold' },
  { value: 700, name: 'Bold', label: '700\u2009-\u2009Bold' },
  { value: 800, name: 'ExtraBold', label: '800\u2009-\u2009Extra Bold' },
  { value: 900, name: 'Black', label: '900\u2009-\u2009Black' },
] as const;

/**
 * Returns the weight name for a given numeric weight value.
 * @param weight - The numeric weight value (100-900).
 * @returns The weight name string, or 'Regular' if not found.
 */
export function getWeightName(weight: number): string {
  return WEIGHT_MAP.find((w) => w.value === weight)?.name ?? 'Regular';
}

/** OS/2 usWidthClass value-to-name mapping (OpenType spec). */
export const WIDTH_MAP = [
  { value: 1, name: 'UltraCondensed', label: 'UltraCondensed' },
  { value: 2, name: 'ExtraCondensed', label: 'ExtraCondensed' },
  { value: 3, name: 'Condensed', label: 'Condensed' },
  { value: 4, name: 'SemiCondensed', label: 'SemiCondensed' },
  { value: 5, name: '', label: 'Normal' },
  { value: 6, name: 'SemiExpanded', label: 'SemiExpanded' },
  { value: 7, name: 'Expanded', label: 'Expanded' },
  { value: 8, name: 'ExtraExpanded', label: 'ExtraExpanded' },
  { value: 9, name: 'UltraExpanded', label: 'UltraExpanded' },
] as const;

export function getWidthName(width: number): string {
  return WIDTH_MAP.find((w) => w.value === width)?.name ?? '';
}

/**
 * Computes the OpenType style name from weight, italic, and width values.
 * e.g. "SemiBold Italic", "Condensed Regular", "Condensed Bold Italic"
 */
export function computeStyleName(weight: number, italic: boolean, width: number): string {
  const widthName = getWidthName(width);
  const weightName = getWeightName(weight);
  const parts: string[] = [];
  if (widthName) parts.push(widthName);
  parts.push(weightName);
  if (italic) parts.push('Italic');
  return parts.join(' ');
}

/**
 * Computes the hyphenated file/folder suffix from weight, italic, and width.
 * e.g. "Regular", "BoldItalic", "Condensed-Regular", "SemiExpanded-BlackItalic"
 */
export function computeFileStyleName(weight: number, italic: boolean, width: number): string {
  const widthName = getWidthName(width);
  const weightName = getWeightName(weight);
  let suffix = weightName;
  if (italic) suffix += 'Italic';
  return widthName ? `${widthName}-${suffix}` : suffix;
}

/** Cursor blink interval in milliseconds. */
export const CURSOR_BLINK_INTERVAL_MS = 530;

/** Duration to show the "merge complete" message in milliseconds. */
export const DONE_DISPLAY_MS = 5000;

/** Duration to show merge error messages (longer so users can read them). */
export const ERROR_DISPLAY_MS = 10000;
