/**
 * @fileoverview Registers IPC handlers for font picking, file reading, output selection, and merge execution.
 */

import { ipcMain, dialog, BrowserWindow, Menu, shell } from 'electron';
import { IPC, MergeConfig } from '@/shared/types';
import { runMerge, abortMerge } from '@/main/merge-engine';
import { setExporting } from '@/main/export-state';
import { readFileSync, existsSync } from 'fs';

/**
 * Registers all IPC handlers for font picking, file reading, output selection, and merge execution.
 */
export function registerIpcHandlers() {
  // Pick font file
  ipcMain.handle(IPC.PICK_FONT, async () => {
    const result = await dialog.showOpenDialog({
      filters: [{ name: 'Font Files', extensions: ['otf', 'ttf'] }],
      properties: ['openFile'],
    });
    if (result.canceled || result.filePaths.length === 0) return null;
    return result.filePaths[0];
  });

  // Pick output location via Save As… dialog (lets user name the export folder)
  ipcMain.handle(IPC.PICK_OUTPUT, async (_event, defaultName?: string) => {
    const result = await dialog.showSaveDialog({
      title: 'Export Font',
      buttonLabel: 'Export',
      defaultPath: defaultName || 'FontBaker-Regular',
      properties: ['createDirectory', 'showOverwriteConfirmation'],
    });
    if (result.canceled || !result.filePath) return null;
    return result.filePath;
  });

  // Check if a font file exists at the given path
  ipcMain.handle(IPC.CHECK_FILE_EXISTS, async (_event, filePath: string) => {
    return existsSync(filePath);
  });

  // Show missing font dialog — returns 'select' or 'clear'
  ipcMain.handle(IPC.SHOW_MISSING_FONT_DIALOG, async (_event, label: string, fileName: string) => {
    const result = await dialog.showMessageBox({
      type: 'warning',
      message: `${label} \u201C${fileName}\u201D not found.`,
      buttons: ['Select Font', 'Clear'],
      defaultId: 0,
      cancelId: 1,
    });
    return result.response === 0 ? 'select' : 'clear';
  });

  // Read font file as ArrayBuffer (for opentype.js parsing in renderer)
  ipcMain.handle(IPC.READ_FONT_FILE, async (_event, fontPath: string) => {
    const buffer = readFileSync(fontPath);
    return buffer.buffer.slice(buffer.byteOffset, buffer.byteOffset + buffer.byteLength);
  });

  // Abort merge
  ipcMain.handle(IPC.ABORT_MERGE, () => {
    abortMerge();
  });

  // Start merge
  ipcMain.handle(IPC.START_MERGE, async (event, config: MergeConfig) => {
    const win = BrowserWindow.fromWebContents(event.sender);
    setExporting(true);
    try {
      if (!config.output.familyName?.trim()) {
        return { success: false, error: 'Font Family is Required' };
      }

      // PICK_OUTPUT uses showSaveDialog with showOverwriteConfirmation,
      // so the OS has already asked the user to replace when the target
      // exists. We just forward overwrite=true to Python when the folder
      // is present so prepare_output_dir doesn't raise FileExistsError.
      const overwrite = existsSync(config.export.package.dir);

      const mergeConfig: MergeConfig = {
        ...config,
        export: {
          package: { ...config.export.package, overwrite },
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
  ipcMain.handle('dialog:alert', async (event, title: string, detail: string) => {
    const win = BrowserWindow.fromWebContents(event.sender);
    const options = { type: 'info' as const, message: title, detail, buttons: ['OK'] };
    if (win) {
      await dialog.showMessageBox(win, options);
    } else {
      await dialog.showMessageBox(options);
    }
  });

  // Context menu for font cards
  ipcMain.handle(
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
  ipcMain.handle(IPC.REVEAL_IN_FINDER, async (_event, filePath: string) => {
    shell.showItemInFolder(filePath);
  });

  // Open URL in default external browser
  ipcMain.handle('shell:open-external', async (_event, url: string) => {
    await shell.openExternal(url);
  });

  // Context menu for preview (cut/copy/paste)
  ipcMain.handle('menu:preview-context', async (event) => {
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

