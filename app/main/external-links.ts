import { shell } from 'electron';

/** Only web URLs may leave the application; never dispatch file/custom schemes. */
export function webURL(value: unknown): string | null {
  if (typeof value !== 'string') return null;
  try {
    const url = new URL(value);
    if (!['https:', 'http:'].includes(url.protocol) || url.username || url.password) return null;
    return url.href;
  } catch {
    return null;
  }
}

export async function openExternalWebURL(value: unknown): Promise<void> {
  const url = webURL(value);
  if (!url) throw new Error('Only HTTP and HTTPS links are supported');
  await shell.openExternal(url);
}
