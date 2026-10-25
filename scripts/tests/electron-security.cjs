// Run after npm run build: node_modules/.bin/electron scripts/tests/electron-security.cjs
// Dialogs and OS URL dispatch are stubbed; all file operations use this process's temporary directory.
const { app, shell, dialog, BrowserWindow } = require('electron');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const root = fs.mkdtempSync(path.join(os.tmpdir(), 'font-ipc-test-'));
app.setPath('userData', path.join(root, 'profile'));
const font = path.join(root, 'test.ttf');
fs.writeFileSync(font, 'TEST_FONT_BYTES');
const destination = path.join(root, 'Output');
fs.mkdirSync(destination);
fs.writeFileSync(path.join(destination, 'keep.txt'), 'KEEP');
dialog.showOpenDialog = async () => ({ canceled: false, filePaths: [font] });
dialog.showSaveDialog = async () => ({ canceled: false, filePath: destination });
const opened = [];
shell.openExternal = async url => { opened.push(url); };
let done = false;
function finish(error) {
  if (done) return;
  done = true;
  if (error) console.error(error);
  else console.log('Electron security integration: passed');
  fs.rmSync(root, { recursive: true, force: true });
  app.exit(error ? 1 : 0);
}

/** File access goes through main-process grants; untrusted senders are refused. */
async function checkIpc(win) {
  const run = code => win.webContents.executeJavaScript(code);
  await assert.rejects(run(`window.electronAPI.readFontFile(${JSON.stringify(font)})`), /select this font again/);
  await assert.rejects(run(`window.electronAPI.getPathForFile(new File(['fake'], 'fake.ttf'))`));
  const selected = await run('window.electronAPI.pickFont()');
  assert.equal(await run(`window.electronAPI.readFontFile(${JSON.stringify(selected)}).then(b => new TextDecoder().decode(b))`), 'TEST_FONT_BYTES');
  const config = { baseFont: { path: selected }, output: { familyName: 'Test', postScriptName: 'Test-Regular' }, export: { package: { dir: destination, overwrite: true } } };
  const denied = await run(`window.electronAPI.startMerge(${JSON.stringify(config)})`);
  assert.equal(denied.success, false);
  assert.match(denied.error, /Choose the export folder again/);
  assert.equal(fs.readFileSync(path.join(destination, 'keep.txt'), 'utf8'), 'KEEP');
  const child = new BrowserWindow({ show: false, webPreferences: {
    preload: path.resolve('dist/preload/index.js'), contextIsolation: true, nodeIntegration: false,
  } });
  await child.loadURL('data:text/html,<body>untrusted</body>');
  await assert.rejects(child.webContents.executeJavaScript(`window.electronAPI.readFontFile(${JSON.stringify(selected)})`), /Untrusted IPC sender/);
  child.destroy();
  if (process.env.TEST_TRANSACTIONAL_EXPORT) {
    config.export.package.dir = await run('window.electronAPI.pickOutput()');
    const failedExport = await run(`window.electronAPI.startMerge(${JSON.stringify(config)})`);
    assert.equal(failedExport.success, false); // Deliberately invalid test font.
    assert.equal(fs.readFileSync(path.join(destination, 'keep.txt'), 'utf8'), 'KEEP');
  }
}

/** Only web links reach the OS; no child windows are ever opened. */
async function checkExternalLinks(win) {
  for (const url of ['https://example.invalid/font', 'file:///does-not-exist', 'custom:command']) {
    await win.webContents.executeJavaScript(`(() => {
      const a = document.createElement('a');
      a.href = ${JSON.stringify(url)}; a.target = '_blank'; a.rel = 'noopener noreferrer';
      document.body.append(a); a.click(); a.remove();
    })()`, true);
  }
  assert.deepEqual(opened, ['https://example.invalid/font']);
  assert.equal(BrowserWindow.getAllWindows().length, 1);
  await assert.rejects(win.webContents.executeJavaScript("window.electronAPI.openExternal('file:///does-not-exist')"));
}

app.once('browser-window-created', (_, win) => {
  win.hide();
  win.webContents.once('did-finish-load', async () => {
    try {
      await checkIpc(win);
      await checkExternalLinks(win);
      finish();
    } catch (error) { finish(error); }
  });
});
require(path.resolve('dist/main/index.js'));
setTimeout(() => finish(new Error('Integration test timed out')), 20000);
