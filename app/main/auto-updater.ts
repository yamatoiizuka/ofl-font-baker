/**
 * @fileoverview Auto-update via GitHub Releases using electron-updater.
 */

import { app, BrowserWindow, dialog } from 'electron';
import { autoUpdater } from 'electron-updater';

/**
 * Wire up electron-updater to check GitHub Releases on launch and prompt the
 * user to restart once a new version has been downloaded.
 */
export function initAutoUpdater(getWindow: () => BrowserWindow | null) {
  if (!app.isPackaged) return;

  autoUpdater.autoDownload = true;
  autoUpdater.autoInstallOnAppQuit = true;

  autoUpdater.on('error', (err) => {
    console.error('[auto-updater]', err);
  });

  autoUpdater.on('update-downloaded', async (info) => {
    const win = getWindow();
    const options = {
      type: 'info' as const,
      buttons: ['Restart now', 'Later'],
      defaultId: 0,
      cancelId: 1,
      message: `OFL Font Baker ${info.version} is ready to install`,
      detail: 'The update has been downloaded. Restart the app to apply it.',
    };
    const result = win
      ? await dialog.showMessageBox(win, options)
      : await dialog.showMessageBox(options);
    if (result.response === 0) {
      autoUpdater.quitAndInstall();
    }
  });

  autoUpdater.checkForUpdates().catch((err) => {
    console.error('[auto-updater] check failed:', err);
  });
}
