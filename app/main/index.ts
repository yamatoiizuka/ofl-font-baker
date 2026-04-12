/**
 * @fileoverview Main process entry point for the Electron application, responsible for window creation and lifecycle management.
 */

import { app, BrowserWindow, Menu, dialog } from 'electron';
import path from 'path';
import { registerIpcHandlers } from '@/main/ipc-handlers';
import { getShortcut } from '@/shared/shortcuts';
import { isExporting, setExporting } from '@/main/export-state';
import { abortMerge } from '@/main/merge-engine';

const APP_NAME = 'Font Baker';

let mainWindow: BrowserWindow | null = null;

/**
 * Build the application menu with proper app name and Edit menu shortcuts.
 */
function buildMenu() {
  const isMac = process.platform === 'darwin';
  const template: Electron.MenuItemConstructorOptions[] = [
    ...(isMac
      ? [
          {
            label: APP_NAME,
            submenu: [
              {
                label: `About ${APP_NAME}`,
                click: () => mainWindow?.webContents.send('menu:about'),
              },
              { type: 'separator' as const },
              { role: 'services' as const },
              { type: 'separator' as const },
              { role: 'hide' as const, label: `Hide ${APP_NAME}` },
              { role: 'hideOthers' as const },
              { role: 'unhide' as const },
              { type: 'separator' as const },
              { role: 'quit' as const, label: `Quit ${APP_NAME}` },
            ],
          },
        ]
      : []),
    {
      label: 'File',
      submenu: [isMac ? { role: 'close' as const } : { role: 'quit' as const }],
    },
    {
      label: 'Edit',
      submenu: [
        {
          label: getShortcut('undo').label,
          accelerator: getShortcut('undo').accelerator,
          click: () => mainWindow?.webContents.send('menu:undo'),
        },
        {
          label: getShortcut('redo').label,
          accelerator: getShortcut('redo').accelerator,
          click: () => mainWindow?.webContents.send('menu:redo'),
        },
        { type: 'separator' },
        {
          label: getShortcut('export').label,
          accelerator: getShortcut('export').accelerator,
          click: () => mainWindow?.webContents.send('menu:export'),
        },
        { type: 'separator' },
        { role: 'cut' },
        { role: 'copy' },
        { role: 'paste' },
        { role: 'selectAll' },
      ],
    },
    {
      label: 'View',
      submenu: [
        { role: 'reload' },
        { role: 'forceReload' },
        { role: 'toggleDevTools' },
        { type: 'separator' },
        { role: 'resetZoom' },
        { role: 'zoomIn' },
        { role: 'zoomOut' },
        { type: 'separator' },
        { role: 'togglefullscreen' },
      ],
    },
    {
      label: 'Window',
      submenu: [
        { role: 'minimize' },
        { role: 'zoom' },
        ...(isMac
          ? [{ type: 'separator' as const }, { role: 'front' as const }]
          : [{ role: 'close' as const }]),
      ],
    },
    {
      role: 'help',
      submenu: [
        {
          label: getShortcut('shortcutsHelp').label,
          accelerator: getShortcut('shortcutsHelp').accelerator,
          click: () => mainWindow?.webContents.send('menu:shortcuts'),
        },
      ],
    },
  ];

  Menu.setApplicationMenu(Menu.buildFromTemplate(template));
}

/**
 * Creates the main application BrowserWindow.
 */
function createWindow() {
  // Allow overriding window dimensions via env vars (used by screenshot mode).
  const envWidth = Number(process.env.WINDOW_WIDTH);
  const envHeight = Number(process.env.WINDOW_HEIGHT);
  const width = Number.isFinite(envWidth) && envWidth > 0 ? envWidth : 1080;
  const height = Number.isFinite(envHeight) && envHeight > 0 ? envHeight : 840;
  const hasOverride = width !== 1080 || height !== 840;

  mainWindow = new BrowserWindow({
    width,
    height,
    minWidth: hasOverride ? 0 : 1080,
    minHeight: hasOverride ? 0 : 640,
    webPreferences: {
      preload: path.join(__dirname, '../preload/index.js'),
      contextIsolation: true,
      nodeIntegration: false,
      additionalArguments: hasOverride ? ['--screenshot'] : [],
    },
    titleBarStyle: 'hiddenInset',
    title: APP_NAME,
  });

  if (process.env.VITE_DEV_SERVER_URL) {
    mainWindow.loadURL(process.env.VITE_DEV_SERVER_URL);
    mainWindow.webContents.openDevTools();
  } else {
    mainWindow.loadFile(path.join(__dirname, '../renderer/index.html'));
  }

  mainWindow.webContents.on('will-navigate', (e) => {
    e.preventDefault();
  });

  mainWindow.on('closed', () => {
    mainWindow = null;
  });
}

app.setName(APP_NAME);

app.whenReady().then(() => {
  buildMenu();
  registerIpcHandlers();
  createWindow();

  app.on('activate', () => {
    if (BrowserWindow.getAllWindows().length === 0) {
      createWindow();
    }
  });
});

let quitConfirmed = false;

app.on('before-quit', (event) => {
  if (quitConfirmed || !isExporting()) return;
  event.preventDefault();
  const options = {
    type: 'warning' as const,
    message: 'Export in progress',
    detail: 'Quitting now will cancel the current export. Are you sure you want to quit?',
    buttons: ['Cancel', 'Quit'],
    defaultId: 0,
    cancelId: 0,
  };
  const result = mainWindow
    ? dialog.showMessageBoxSync(mainWindow, options)
    : dialog.showMessageBoxSync(options);
  if (result === 1) {
    abortMerge();
    setExporting(false);
    quitConfirmed = true;
    app.quit();
  }
});

app.on('window-all-closed', () => {
  if (process.platform !== 'darwin') {
    app.quit();
  }
});
