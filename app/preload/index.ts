/**
 * @fileoverview Preload script that exposes a safe IPC API to the renderer process via Electron's contextBridge.
 */

import { contextBridge, ipcRenderer, webUtils } from 'electron';
import { IPC, MergeConfig, MergeProgress } from '@/shared/types';

/**
 * Preload API object exposed to the renderer process via contextBridge.
 * Provides safe IPC wrappers for font operations and merge workflow.
 */
const api = {
  /** Opens a native file dialog to pick a font file and returns its path. */
  pickFont: (): Promise<string | null> => ipcRenderer.invoke(IPC.PICK_FONT),

  /** Opens a native Save As dialog for the export folder. Returns the chosen full path. */
  pickOutput: (defaultName?: string): Promise<string | null> =>
    ipcRenderer.invoke(IPC.PICK_OUTPUT, defaultName),

  /** Sends a merge configuration to the main process and returns the result. */
  startMerge: (config: MergeConfig) => ipcRenderer.invoke(IPC.START_MERGE, config),

  /** Aborts the currently running merge process. */
  abortMerge: (): Promise<void> => ipcRenderer.invoke(IPC.ABORT_MERGE),

  /** Subscribes to merge progress updates from the main process and returns an unsubscribe function. */
  onMergeProgress: (callback: (progress: MergeProgress) => void) => {
    const handler = (_event: any, progress: MergeProgress) => callback(progress);
    ipcRenderer.on(IPC.MERGE_PROGRESS, handler);
    return () => ipcRenderer.removeListener(IPC.MERGE_PROGRESS, handler);
  },

  /** Checks if a file exists at the given path. */
  checkFileExists: (path: string): Promise<boolean> =>
    ipcRenderer.invoke(IPC.CHECK_FILE_EXISTS, path),

  /** Shows a native dialog for missing font files. Returns 'select' or 'clear'. */
  showMissingFontDialog: (label: string, fileName: string): Promise<'select' | 'clear'> =>
    ipcRenderer.invoke(IPC.SHOW_MISSING_FONT_DIALOG, label, fileName),

  /** Reads a font file from disk and returns its contents as an ArrayBuffer. */
  readFontFile: (path: string): Promise<ArrayBuffer> =>
    ipcRenderer.invoke(IPC.READ_FONT_FILE, path),

  /** Retrieves the absolute file system path for a dropped File object. */
  getPathForFile: (file: File): string => webUtils.getPathForFile(file),

  /** Show a native alert dialog. */
  showAlert: (title: string, detail: string): Promise<void> =>
    ipcRenderer.invoke('dialog:alert', title, detail),

  /** Show context menu for font card. Returns action: 'info' | 'reveal' | 'clear' | null */
  showCardContextMenu: (options: { hasFont: boolean; fontPath?: string }): Promise<string | null> =>
    ipcRenderer.invoke(IPC.SHOW_CONTEXT_MENU, options),

  /** Reveal a file in Finder. */
  revealInFinder: (filePath: string): Promise<void> =>
    ipcRenderer.invoke(IPC.REVEAL_IN_FINDER, filePath),

  /** Show context menu for preview. Returns action: 'cut' | 'copy' | 'paste' | 'selectAll' | null */
  showPreviewContextMenu: (): Promise<string | null> =>
    ipcRenderer.invoke('menu:preview-context'),

  /** Listen for menu undo/redo commands. */
  onMenuUndo: (callback: () => void) => {
    ipcRenderer.on('menu:undo', callback);
    return () => ipcRenderer.removeListener('menu:undo', callback);
  },
  onMenuRedo: (callback: () => void) => {
    ipcRenderer.on('menu:redo', callback);
    return () => ipcRenderer.removeListener('menu:redo', callback);
  },
  onMenuAbout: (callback: () => void) => {
    ipcRenderer.on('menu:about', callback);
    return () => ipcRenderer.removeListener('menu:about', callback);
  },
  onMenuShortcuts: (callback: () => void) => {
    ipcRenderer.on('menu:shortcuts', callback);
    return () => ipcRenderer.removeListener('menu:shortcuts', callback);
  },
  onMenuExport: (callback: () => void) => {
    ipcRenderer.on('menu:export', callback);
    return () => ipcRenderer.removeListener('menu:export', callback);
  },
  onMenuZoom: (callback: (delta: 'in' | 'out' | 'reset') => void) => {
    const onIn = () => callback('in');
    const onOut = () => callback('out');
    const onReset = () => callback('reset');
    ipcRenderer.on('menu:zoom-in', onIn);
    ipcRenderer.on('menu:zoom-out', onOut);
    ipcRenderer.on('menu:zoom-reset', onReset);
    return () => {
      ipcRenderer.removeListener('menu:zoom-in', onIn);
      ipcRenderer.removeListener('menu:zoom-out', onOut);
      ipcRenderer.removeListener('menu:zoom-reset', onReset);
    };
  },
  /** Open a URL in the user's default external browser. */
  openExternal: (url: string): Promise<void> => ipcRenderer.invoke('shell:open-external', url),

  /** True when running in screenshot mode (window size overridden via env vars). */
  isScreenshotMode: process.argv.includes('--screenshot'),
};

export type ElectronAPI = typeof api;

contextBridge.exposeInMainWorld('electronAPI', api);
