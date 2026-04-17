/**
 * @fileoverview PostScript name (nameID 6) sanitizer and validator.
 * Mirrors sanitize_postscript_name / validate_postscript_name in python/merge_fonts.py.
 */

const FORBIDDEN = new Set(['[', ']', '(', ')', '{', '}', '<', '>', '/', '%']);
const MAX_BYTES = 63;

/**
 * Strips characters not allowed in a PostScript name.
 * Allowed: printable ASCII 33-126 minus `[]{}<>()/%` (and space, which
 * lies outside that range). Result is clamped to 63 bytes.
 * @param name - The candidate name to sanitize.
 * @returns The sanitized name (may be empty).
 */
export function sanitizePostScriptName(name: string): string {
  let out = '';
  for (const c of name) {
    const cp = c.codePointAt(0)!;
    if (cp >= 33 && cp <= 126 && !FORBIDDEN.has(c)) {
      out += c;
    }
  }
  return out.slice(0, MAX_BYTES);
}

/**
 * Reports whether a PostScript name needs manual entry — true when the
 * family name contains any character that the sanitizer would drop
 * (other than spaces, which are always stripped silently).
 * @param familyName - The current family name input.
 * @returns True if auto-derivation loses information and the user should edit.
 */
export function needsManualPostScriptName(familyName: string): boolean {
  const familyWithoutSpaces = familyName.replace(/ /g, '');
  return sanitizePostScriptName(familyName) !== familyWithoutSpaces;
}

/**
 * Validates a PostScript name against the OpenType spec.
 * @param name - The name to validate.
 * @returns An error message if invalid, or null if the name is spec-compliant.
 */
export function validatePostScriptName(name: string): string | null {
  if (!name) return 'PostScript name is empty';
  const byteLength = new TextEncoder().encode(name).length;
  if (byteLength > MAX_BYTES) {
    return `PostScript name exceeds ${MAX_BYTES} bytes`;
  }
  for (const c of name) {
    const cp = c.codePointAt(0)!;
    if (cp < 33 || cp > 126 || FORBIDDEN.has(c)) {
      return `PostScript name contains invalid character "${c}"`;
    }
  }
  return null;
}
