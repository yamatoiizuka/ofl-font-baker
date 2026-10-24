// Run after npm run build with Electron. All OS URL dispatch is intercepted.
const { app, shell, BrowserWindow } = require('electron');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const assert = require('node:assert/strict');
const root = fs.mkdtempSync(path.join(os.tmpdir(), 'font-link-test-'));
app.setPath('userData', path.join(root, 'profile'));
const opened = [];
shell.openExternal = async url => { opened.push(url); };
let done = false;
function finish(error) {
  if (done) return;
  done = true;
  if (error) console.error(error);
  else console.log('External window security integration: passed');
  fs.rmSync(root, { recursive: true, force: true });
  app.exit(error ? 1 : 0);
}
app.once('browser-window-created', (_, win) => {
  win.hide();
  win.webContents.once('did-finish-load', async () => {
    try {
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
      finish();
    } catch (error) { finish(error); }
  });
});
require(path.resolve('dist/main/index.js'));
setTimeout(() => finish(new Error('Integration test timed out')), 20000);
