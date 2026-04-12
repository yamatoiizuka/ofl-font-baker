/**
 * @fileoverview Tracks whether an export/merge is currently in progress, shared between IPC handlers and the quit confirmation dialog.
 */

let exporting = false;

/**
 * Sets the current exporting state.
 * @param value - True while a merge is in progress.
 */
export function setExporting(value: boolean): void {
  exporting = value;
}

/**
 * Returns whether an export is currently in progress.
 */
export function isExporting(): boolean {
  return exporting;
}
