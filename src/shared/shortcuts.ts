/**
 * @fileoverview Central registry of keyboard shortcuts used across the app.
 *
 * Single source of truth for both the Electron application menu (main
 * process, uses Electron's accelerator string format) and the renderer's
 * global keydown handler (uses DOM KeyboardEvent fields). Add new
 * shortcuts here so the list stays easy to audit at a glance.
 */

/** Shortcut identifiers — used to dispatch behaviour in the renderer. */
export type ShortcutId =
  | 'undo'
  | 'redo'
  | 'fontInfo'
  | 'revealFont'
  | 'clearFont'
  | 'export'
  | 'shortcutsHelp';

export type ShortcutSection = 'General' | 'Input' | 'Export';

export interface ShortcutDef {
  id: ShortcutId;
  /** Section heading in the help modal. */
  section: ShortcutSection;
  /** Short human label shown in menus and help text. */
  label: string;
  /** Electron accelerator string (main process / app menu). */
  accelerator: string;
  /**
   * Renderer-side match: single key + required modifiers. Keys are
   * compared case-insensitively against `KeyboardEvent.key`.
   */
  key: string;
  meta?: boolean; // ⌘ on macOS / Ctrl on Windows/Linux
  shift?: boolean;
  alt?: boolean; // ⌥ on macOS / Alt on Windows/Linux
}

export const SHORTCUTS: ShortcutDef[] = [
  // General — app-wide
  {
    id: 'undo',
    section: 'General',
    label: 'Undo',
    accelerator: 'CmdOrCtrl+Z',
    key: 'z',
    meta: true,
  },
  {
    id: 'redo',
    section: 'General',
    label: 'Redo',
    accelerator: 'CmdOrCtrl+Shift+Z',
    key: 'z',
    meta: true,
    shift: true,
  },
  {
    id: 'shortcutsHelp',
    section: 'General',
    label: 'Keyboard Shortcuts',
    accelerator: 'CmdOrCtrl+/',
    key: '/',
    meta: true,
  },

  // Input — active font card
  {
    id: 'fontInfo',
    section: 'Input',
    label: 'Show Font Info',
    accelerator: 'CmdOrCtrl+I',
    key: 'i',
    meta: true,
  },
  {
    id: 'revealFont',
    section: 'Input',
    label: 'Reveal in Finder',
    accelerator: 'CmdOrCtrl+Alt+R',
    key: 'r',
    meta: true,
    alt: true,
  },
  {
    id: 'clearFont',
    section: 'Input',
    label: 'Clear Font',
    accelerator: 'CmdOrCtrl+Backspace',
    key: 'backspace',
    meta: true,
  },

  // Export
  {
    id: 'export',
    section: 'Export',
    label: 'Export',
    accelerator: 'CmdOrCtrl+E',
    key: 'e',
    meta: true,
  },
];

/**
 * Matches a DOM keyboard event against the registered shortcuts and
 * returns the first matching shortcut id, or null.
 */
export function matchShortcut(e: KeyboardEvent): ShortcutId | null {
  const k = e.key.toLowerCase();
  const meta = e.metaKey || e.ctrlKey;
  for (const s of SHORTCUTS) {
    if (s.key !== k) continue;
    if (!!s.meta !== meta) continue;
    if (!!s.shift !== e.shiftKey) continue;
    if (!!s.alt !== e.altKey) continue;
    return s.id;
  }
  return null;
}

/** Look up a shortcut by id (primary entry, for menu construction). */
export function getShortcut(id: ShortcutId): ShortcutDef {
  const s = SHORTCUTS.find((x) => x.id === id);
  if (!s) throw new Error(`Unknown shortcut: ${id}`);
  return s;
}

/** One entry per id — de-duped for display in the help modal. */
export const SHORTCUT_HELP: ShortcutDef[] = SHORTCUTS.filter(
  (s, i, arr) => arr.findIndex((x) => x.id === s.id) === i,
);

/**
 * Parse an accelerator into named slots so the modal can render
 * aligned columns (shift / alt / cmd / key) with spacers for missing mods.
 */
export function parseAccelerator(
  accel: string,
  isMac = true,
): { shift?: string; alt?: string; cmd?: string; key?: string } {
  const out: { shift?: string; alt?: string; cmd?: string; key?: string } = {};
  for (const p of accel.split('+')) {
    if (p === 'Shift') out.shift = symbolize(p, isMac);
    else if (p === 'Alt' || p === 'Option') out.alt = symbolize(p, isMac);
    else if (p === 'Ctrl' || p === 'Control' || p === 'Cmd' || p === 'Command' || p === 'CmdOrCtrl')
      out.cmd = symbolize(p, isMac);
    else out.key = symbolize(p, isMac);
  }
  return out;
}

/**
 * Split an accelerator string into display parts, one glyph per key cap.
 * Parts are ordered: Shift → Control → Option → Command → key, matching
 * Figma and the macOS menu bar convention.
 */
export function splitAccelerator(accel: string, isMac = true): string[] {
  const raw = accel.split('+');
  const mods: Record<string, string> = {};
  let keyPart = '';
  for (const p of raw) {
    const s = symbolize(p, isMac);
    if (p === 'Shift') mods.shift = s;
    else if (p === 'Ctrl' || p === 'Control') mods.ctrl = s;
    else if (p === 'Alt' || p === 'Option') mods.alt = s;
    else if (p === 'Cmd' || p === 'Command' || p === 'CmdOrCtrl') mods.cmd = isMac ? '⌘' : '⌃';
    else keyPart = s;
  }
  const out: string[] = [];
  if (mods.shift) out.push(mods.shift);
  if (mods.ctrl) out.push(mods.ctrl);
  if (mods.alt) out.push(mods.alt);
  if (mods.cmd) out.push(mods.cmd);
  if (keyPart) out.push(keyPart);
  return out;
}

function symbolize(p: string, isMac: boolean): string {
  if (!isMac) return p;
  switch (p) {
    case 'CmdOrCtrl':
    case 'Cmd':
    case 'Command':
      return '⌘';
    case 'Ctrl':
    case 'Control':
      return '⌃';
    case 'Shift':
      return '⇧';
    case 'Alt':
    case 'Option':
      return '⌥';
    case 'Plus':
      return '+';
    case 'Backspace':
      return '⌫';
    case 'Delete':
      return '⌦';
    case 'Return':
    case 'Enter':
      return '⏎';
    case 'Tab':
      return '⇥';
    case 'Escape':
    case 'Esc':
      return '⎋';
    case 'Left':
      return '←';
    case 'Right':
      return '→';
    case 'Up':
      return '↑';
    case 'Down':
      return '↓';
    default:
      return p.length === 1 ? p.toUpperCase() : p;
  }
}

/** Format an accelerator string for display (e.g. "⌘⇧Z" on macOS). */
export function formatAccelerator(accel: string, isMac = true): string {
  const parts = accel.split('+');
  const sym = (p: string) => {
    if (!isMac) return p;
    switch (p) {
      case 'CmdOrCtrl':
      case 'Cmd':
      case 'Command':
        return '⌘';
      case 'Ctrl':
      case 'Control':
        return '⌃';
      case 'Shift':
        return '⇧';
      case 'Alt':
      case 'Option':
        return '⌥';
      case 'Plus':
        return '+';
      case 'Backspace':
        return '⌫';
      case 'Delete':
        return '⌦';
      case 'Return':
      case 'Enter':
        return '⏎';
      case 'Tab':
        return '⇥';
      case 'Escape':
      case 'Esc':
        return '⎋';
      case 'Left':
        return '←';
      case 'Right':
        return '→';
      case 'Up':
        return '↑';
      case 'Down':
        return '↓';
      default:
        return p.length === 1 ? p.toUpperCase() : p;
    }
  };
  return parts.map(sym).join(isMac ? '' : '+');
}
