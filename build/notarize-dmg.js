/**
 * @fileoverview electron-builder afterAllArtifactBuild hook: notarize and staple .dmg.
 * electron-builder notarizes the .app before packaging but not the resulting .dmg,
 * so this hook submits each .dmg to Apple and staples the ticket.
 */

const { execFileSync } = require('child_process');

exports.default = async function notarizeDmg(buildResult) {
  const dmgs = (buildResult.artifactPaths || []).filter((p) => p.endsWith('.dmg'));
  if (dmgs.length === 0) return [];

  const { APPLE_API_KEY, APPLE_API_KEY_ID, APPLE_API_ISSUER } = process.env;
  if (!APPLE_API_KEY || !APPLE_API_KEY_ID || !APPLE_API_ISSUER) {
    console.warn('[notarize-dmg] Skipped: APPLE_API_KEY / APPLE_API_KEY_ID / APPLE_API_ISSUER are not set.');
    return [];
  }

  for (const dmg of dmgs) {
    console.log(`[notarize-dmg] Submitting ${dmg}…`);
    execFileSync(
      'xcrun',
      [
        'notarytool', 'submit', dmg,
        '--key', APPLE_API_KEY,
        '--key-id', APPLE_API_KEY_ID,
        '--issuer', APPLE_API_ISSUER,
        '--wait',
      ],
      { stdio: 'inherit' },
    );

    console.log(`[notarize-dmg] Stapling ${dmg}…`);
    execFileSync('xcrun', ['stapler', 'staple', dmg], { stdio: 'inherit' });
  }

  return [];
};
