// Stapling modifies the DMG after electron-builder generated update metadata.
// Regenerate its blockmap and hashes from the final bytes before uploading.
const fs = require('fs');
const crypto = require('crypto');
const path = require('path');
const yaml = require('js-yaml');
const { buildBlockMap } = require('app-builder-lib/out/targets/blockmap/blockmap');

async function main() {
  const major = Number(require('../package.json').build.mac.minimumSystemVersion.split('.')[0]);
  if (!Number.isInteger(major) || major < 11) throw new Error('Unsupported macOS minimum version');
  const file = 'release/latest-mac.yml';
  const info = yaml.load(fs.readFileSync(file, 'utf8'));
  for (const entry of info.files) {
    if (path.basename(entry.url) !== entry.url) throw new Error('Unexpected artifact path');
    const artifact = path.join('release', entry.url);
    if (entry.url.endsWith('.dmg')) await buildBlockMap(artifact, 'gzip', artifact + '.blockmap');
    const bytes = fs.readFileSync(artifact);
    entry.size = bytes.length;
    entry.sha512 = crypto.createHash('sha512').update(bytes).digest('base64');
  }
  const primary = info.files.find(entry => entry.url === info.path);
  if (!primary) throw new Error('Missing primary update artifact');
  info.sha512 = primary.sha512;
  info.minimumSystemVersion = `${major + 9}.0.0`;
  fs.writeFileSync(file, yaml.dump(info));
}
main().catch(error => { console.error(error); process.exitCode = 1; });
