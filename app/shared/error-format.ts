/**
 * @fileoverview Cleans up raw Python stderr from a failed merge for
 * display and clipboard copying. Redacts absolute home-directory paths
 * (so copy-pasted Issue reports don't leak usernames), collapses
 * repeated warning lines, and extracts a one-line summary when the
 * traceback has a recognisable shape (e.g. a missing-glyph KeyError).
 */

/**
 * Returns the given raw error text with the noisy bits cleaned up:
 * - `/Users/<name>/…` (macOS) and `/home/<name>/…` (Linux) become `~/…`
 * - `C:\Users\<name>\…` (Windows) becomes `~\…`
 * - long `.../site-packages/` paths collapse to `site-packages/`
 * - consecutive identical lines collapse to one row with `(×N)`
 * @param raw - The unsanitised error text captured from Python stderr.
 * @returns A redacted and deduplicated copy suitable for sharing.
 */
export function cleanErrorText(raw: string): string {
  if (!raw) return raw;

  const redacted = raw
    .replace(/\/(?:Users|home)\/[^\/\s]+\//g, '~/')
    .replace(/[A-Z]:\\Users\\[^\\\s]+\\/g, '~\\')
    // Collapse any deep virtualenv / pyenv path into just `site-packages/…`.
    .replace(/[^\s"'`]*\/site-packages\//g, 'site-packages/')
    // merge-engine.ts wraps Python stderr with "Merge failed (exit code N): "
    // on the same line as the first warning, which blocks the dedup below
    // from seeing it as a duplicate. Split the prefix onto its own line.
    .replace(/^(Merge failed \(exit code \d+\):)\s*/, '$1\n');

  const lines = redacted.split('\n');
  const out: string[] = [];
  let i = 0;
  while (i < lines.length) {
    let count = 1;
    while (i + count < lines.length && lines[i + count] === lines[i]) count++;
    out.push(count > 1 ? `${lines[i]}  (×${count})` : lines[i]);
    i += count;
  }
  return out.join('\n');
}

/** Font context included at the top of the clipboard payload. */
export interface ErrorContext {
  baseFamily?: string;
  subFamily?: string;
}

/**
 * Builds the text that gets copied to the clipboard: a small font-context
 * header (so the report reader knows which fonts were in play) followed
 * by a blank line and the cleaned traceback.
 * @param raw - The unsanitised error text.
 * @param context - Optional base/sub font family names to include.
 * @returns A self-contained clipboard payload.
 */
export function buildCopyableError(raw: string, context?: ErrorContext): string {
  const cleaned = cleanErrorText(raw);
  const header: string[] = [];
  if (context?.baseFamily) header.push(`Base: ${context.baseFamily}`);
  if (context?.subFamily) header.push(`Sub: ${context.subFamily}`);
  return header.length > 0 ? `${header.join('\n')}\n\n${cleaned}` : cleaned;
}
