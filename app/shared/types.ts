/**
 * @fileoverview Shared TypeScript type definitions for font sources, merge configuration, and IPC contracts.
 */

export interface VariableAxis {
  tag: string; // e.g. 'wght', 'wdth', 'opsz'
  name: string; // Human-readable name, e.g. 'Weight'
  minValue: number;
  defaultValue: number;
  maxValue: number;
  currentValue: number; // User-selected value, initialized to defaultValue
}

import { type FontRole } from '@/shared/constants';

export interface FontSource {
  path: string;
  role: FontRole;
  familyName: string;
  styleName: string;
  unitsPerEm: number;
  ascender: number; // font units (from OS/2 or hhea)
  glyphCount: number;
  baselineOffset: number; // font units, e.g. +10, -12
  scale: number; // e.g. 0.98 for 98%
  sampleText: string; // Auto-detected from cmap coverage
  isVariable: boolean;
  axes: VariableAxis[]; // Empty array if static font
  // Cached metadata (loaded once, avoids re-parsing)
  copyright?: string;
  designer?: string;
  license?: string;
  licenseURL?: string;
  description?: string;
}

export interface MergeOutput {
  familyName: string;
  /** PostScript name (nameID 6). Printable ASCII 33-126 minus []{}<>()/%, <= 63 bytes. */
  postScriptName: string;
  weight: number;
  italic: boolean;
  width: number;
  designer: string;
  copyright: string;
  upm: number;
}

export interface MergePackage {
  dir: string;
  overwrite: boolean;
  bundleInputFonts?: boolean;
}

export interface MergeExport {
  package: MergePackage;
}

export interface MergeConfig {
  subFont: FontSource | null;
  baseFont: FontSource;
  output: MergeOutput;
  export: MergeExport;
}

export interface ExportManifest {
  outputDir: string;
  fontPath: string;
  woff2Path: string | null;
  oflPath: string | null;
  settingsPath: string | null;
  configPath: string | null;
  files: string[];
}

export interface MergeProgress {
  stage:
    | 'loading'
    | 'analyzing'
    | 'merging-glyphs'
    | 'merging-features'
    | 'writing'
    | 'done'
    | 'error';
  percent: number;
  message: string;
}

// IPC channel names
export const IPC = {
  READ_FONT_FILE: 'font:read-file',
  CHECK_FILE_EXISTS: 'font:check-exists',
  SHOW_MISSING_FONT_DIALOG: 'dialog:missing-font',
  START_MERGE: 'merge:start',
  ABORT_MERGE: 'merge:abort',
  MERGE_PROGRESS: 'merge:progress',
  PICK_OUTPUT: 'dialog:pick-output',
  PICK_FONT: 'dialog:pick-font',
  SHOW_CONTEXT_MENU: 'menu:context',
  REVEAL_IN_FINDER: 'shell:reveal',
} as const;
