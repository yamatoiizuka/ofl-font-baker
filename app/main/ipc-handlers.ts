/**
 * @fileoverview Registers IPC handlers for font picking, file reading, output selection, and merge execution.
 */

import { app, ipcMain, dialog, BrowserWindow, Menu, shell, IpcMainInvokeEvent } from 'electron';
import path from 'path';
import { pathToFileURL } from 'url';
import { FileAuthority } from './file-authority';
import { IPC, MergeConfig } from '@/shared/types';
import { runMerge, abortMerge } from '@/main/merge-engine';
import { isExporting, setExporting } from '@/main/export-state';
import { validatePostScriptName } from '@/shared/postscript-name';
import { openExternalWebURL } from './external-links';

/**
 * Registers all IPC handlers for font picking, file reading, output selection, and merge execution.
 */
export function registerIpcHandlers(getWindow: () => BrowserWindow | null) {
  const files = new FileAuthority(path.join(app.getPath('userData'), 'authorized-fonts.json'));
  const trustedURL = process.env.VITE_DEV_SERVER_URL || pathToFileURL(path.join(__dirname, '../renderer/index.html')).href;
  function trusted(event: IpcMainInvokeEvent) {
    const win = getWindow();
    if (!win || event.sender !== win.webContents || event.senderFrame !== win.webContents.mainFrame ||
        event.senderFrame.url.split('#')[0] !== new URL(trustedURL).href.split('#')[0]) {
      throw new Error('Untrusted IPC sender');
    }
  }
  function handle(channel: string, listener: (event: IpcMainInvokeEvent, ...args: any[]) => any) {
    ipcMain.handle(channel, (event, ...args) => {
      trusted(event);
      return listener(event, ...args);
    });
  }
  // This private channel is only used by preload with webUtils.getPathForFile(File).
  // The bridge never exposes a string-based registration function.
  handle('font:register-dropped-file', (_event, file: string) => files.grantInput(file));
  // Pick font file
  handle(IPC.PICK_FONT, async (event) => {
    const result = await dialog.showOpenDialog({
      filters: [{ name: 'Font Files', extensions: ['otf', 'ttf'] }],
      properties: ['openFile'],
    });
    if (result.canceled || result.filePaths.length === 0) return null;
    trusted(event);
    return files.grantInput(result.filePaths[0]);
  });

  // Pick output location via Save As… dialog (lets user name the export folder)
  handle(IPC.PICK_OUTPUT, async (event, defaultName?: string) => {
    files.clearOutput();
    const safeName = typeof defaultName === 'string' ? path.basename(defaultName).slice(0, 200) : undefined;
    const result = await dialog.showSaveDialog({
      title: 'Export Font',
      buttonLabel: 'Export',
      defaultPath: safeName || 'FontBaker-Regular',
      properties: ['createDirectory', 'showOverwriteConfirmation'],
    });
    if (result.canceled || !result.filePath) return null;
    trusted(event);
    return files.grantOutput(result.filePath);
  });

  // Check if a font file exists at the given path
  handle(IPC.CHECK_FILE_EXISTS, async (_event, filePath: string) => {
    return files.hasInput(filePath);
  });

  // Show missing font dialog — returns 'select' or 'clear'
  handle(IPC.SHOW_MISSING_FONT_DIALOG, async (_event, label: string, fileName: string) => {
    const result = await dialog.showMessageBox({
      type: 'warning',
      message: `${label} \u201C${fileName}\u201D is missing or needs access permission.`,
      buttons: ['Select Font', 'Clear'],
      defaultId: 0,
      cancelId: 1,
    });
    return result.response === 0 ? 'select' : 'clear';
  });

  // Read font file as ArrayBuffer (for opentype.js parsing in renderer)
  handle(IPC.READ_FONT_FILE, async (_event, fontPath: string) => {
    const buffer = files.readInput(fontPath);
    return buffer.buffer.slice(buffer.byteOffset, buffer.byteOffset + buffer.byteLength);
  });

  // Abort merge
  handle(IPC.ABORT_MERGE, () => {
    abortMerge();
  });

  // Start merge
  handle(IPC.START_MERGE, async (event, config: MergeConfig) => {
    const win = BrowserWindow.fromWebContents(event.sender);
    if (isExporting()) return { success: false, error: 'An export is already in progress' };
    setExporting(true);
    try {
      if (!config || typeof config.output?.familyName !== 'string' ||
          typeof config.export?.package?.dir !== 'string' || !config.baseFont ||
          JSON.stringify(config).length > 1024 * 1024) {
        throw new Error('Invalid merge configuration');
      }
      const basePath = files.requireInput(config.baseFont.path);
      const subPath = config.subFont ? files.requireInput(config.subFont.path) : null;
      const destination = files.consumeOutput(config.export.package.dir, [basePath, ...(subPath ? [subPath] : [])]);
      if (!config.output.familyName?.trim()) {
        return { success: false, error: 'Font Family is Required' };
      }
      const psError = validatePostScriptName((config.output.postScriptName || '').trim());
      if (psError) {
        return { success: false, error: `PostScript name: ${psError}` };
      }

      const mergeConfig: MergeConfig = {
        ...config,
        baseFont: { ...config.baseFont, path: basePath },
        subFont: config.subFont && subPath ? { ...config.subFont, path: subPath } : null,
        export: {
          package: { ...config.export.package, ...destination },
        },
      };
      const manifest = await runMerge(mergeConfig, (progress) => {
        win?.webContents.send(IPC.MERGE_PROGRESS, progress);
      });

      return { success: true, path: manifest.fontPath };
    } catch (err: any) {
      return { success: false, error: err.message };
    } finally {
      setExporting(false);
    }
  });

  // Alert dialog with app icon (attached to window as sheet on macOS)
  handle('dialog:alert', async (event, title: string, detail: string) => {
    const win = BrowserWindow.fromWebContents(event.sender);
    const options = { type: 'info' as const, message: title, detail, buttons: ['OK'] };
    if (win) {
      await dialog.showMessageBox(win, options);
    } else {
      await dialog.showMessageBox(options);
    }
  });

  // Context menu for font cards
  handle(
    IPC.SHOW_CONTEXT_MENU,
    async (event, options: { hasFont: boolean; fontPath?: string }) => {
      const win = BrowserWindow.fromWebContents(event.sender);
      if (!win) return null;

      return new Promise<string | null>((resolve) => {
        const template: Electron.MenuItemConstructorOptions[] = [];
        if (options.hasFont) {
          template.push(
            {
              label: 'Get Info',
              accelerator: 'CmdOrCtrl+I',
              registerAccelerator: false,
              click: () => resolve('info'),
            },
            {
              label: 'Reveal in Finder',
              accelerator: 'CmdOrCtrl+Alt+R',
              registerAccelerator: false,
              click: () => resolve('reveal'),
            },
            { type: 'separator' },
            {
              label: 'Clear',
              accelerator: 'CmdOrCtrl+Backspace',
              registerAccelerator: false,
              click: () => resolve('clear'),
            },
          );
        }
        if (template.length === 0) {
          resolve(null);
          return;
        }
        const menu = Menu.buildFromTemplate(template);
        menu.popup({ window: win, callback: () => resolve(null) });
      });
    },
  );

  // Reveal file in Finder
  handle(IPC.REVEAL_IN_FINDER, async (_event, filePath: string) => {
    shell.showItemInFolder(files.requireInput(filePath));
  });

  // Open URL in default external browser
  handle('shell:open-external', async (_event, url: string) => {
    await openExternalWebURL(url);
  });

  // Context menu for preview (cut/copy/paste)
  handle('menu:preview-context', async (event) => {
    const win = BrowserWindow.fromWebContents(event.sender);
    if (!win) return null;

    return new Promise<string | null>((resolve) => {
      const menu = Menu.buildFromTemplate([
        { label: 'Cut', accelerator: 'CmdOrCtrl+X', click: () => resolve('cut') },
        { label: 'Copy', accelerator: 'CmdOrCtrl+C', click: () => resolve('copy') },
        { label: 'Paste', accelerator: 'CmdOrCtrl+V', click: () => resolve('paste') },
        { type: 'separator' },
        { label: 'Select All', accelerator: 'CmdOrCtrl+A', click: () => resolve('selectAll') },
      ]);
      menu.popup({ window: win, callback: () => resolve(null) });
    });
  });
}

