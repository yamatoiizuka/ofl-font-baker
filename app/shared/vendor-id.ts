/**
 * @fileoverview Vendor ID (OS/2 achVendID) sanitizer.
 * Mirrors sanitize_vendor_id in python/merge_fonts.py.
 */

const FORBIDDEN = new Set(['[', ']', '(', ')', '{', '}', '<', '>', '/', '%']);
const MAX_LEN = 4;

/**
 * Strips characters not allowed in OS/2 achVendID, uppercases the rest,
 * and clamps the result to 4 characters.
 *
 * Allowed: printable ASCII 33-126 minus `[]{}<>()/%` (same set as the
 * PostScript-name sanitizer). Spaces are disallowed as input because
 * the field is right-padded with spaces on write.
 * @param raw - The candidate vendor ID.
 * @returns Up to 4 uppercase ASCII characters.
 */
export function sanitizeVendorID(raw: string): string {
  let out = '';
  for (const c of raw) {
    const cp = c.codePointAt(0)!;
    if (cp >= 33 && cp <= 126 && !FORBIDDEN.has(c)) {
      out += c.toUpperCase();
    }
  }
  return out.slice(0, MAX_LEN);
}

/**
 * Reports whether the raw input contains any character that would be
 * dropped by the sanitizer. Used to surface an inline hint while the
 * user is typing; the hint clears on blur once sanitization runs.
 * @param raw - The raw input value.
 * @returns True if at least one character is outside the allowed set.
 */
export function hasInvalidVendorChar(raw: string): boolean {
  for (const c of raw) {
    const cp = c.codePointAt(0)!;
    if (cp < 33 || cp > 126 || FORBIDDEN.has(c)) return true;
  }
  return false;
}
