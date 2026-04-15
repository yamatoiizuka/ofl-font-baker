#!/usr/bin/env bash
# Build, sign, notarize, and publish a macOS release to GitHub Releases (as draft).
#
# Prerequisites:
#   - Apple signing identity in Keychain (Developer ID Application)
#   - App Store Connect API key at $APPLE_API_KEY
#   - env vars: APPLE_API_KEY, APPLE_API_KEY_ID, APPLE_API_ISSUER
#   - gh CLI authenticated with repo scope
#
# Why this script instead of `electron-builder --publish always`:
#   --publish uploads artifacts in parallel with the afterAllArtifactBuild hook,
#   so the .dmg reaches GitHub before the hook staples the notarization ticket.
#   Building locally first, then uploading with gh, guarantees correct ordering
#   and SHA consistency with latest-mac.yml.

set -euo pipefail

cd "$(dirname "$0")/.."

for v in APPLE_API_KEY APPLE_API_KEY_ID APPLE_API_ISSUER; do
  if [[ -z "${!v:-}" ]]; then
    echo "error: $v is not set" >&2
    exit 1
  fi
done

gh auth status >/dev/null

VERSION="$(node -p "require('./package.json').version")"
TAG="v${VERSION}"

echo "==> Cleaning release/"
rm -rf release

echo "==> Building (sign + notarize .app + notarize/staple .dmg)"
npm run dist

echo "==> Verifying artifacts"
xcrun stapler validate "release/Font Baker-arm64.dmg"
codesign --verify --deep --strict "release/mac-arm64/Font Baker.app"

# latest-mac.yml records URLs with hyphens (Font-Baker-...), but electron-builder
# writes files with spaces (Font Baker-...). Rename so uploaded asset names match
# the yml — otherwise auto-updater 404s.
echo "==> Normalizing filenames (space -> hyphen)"
for f in release/"Font Baker-"*; do
  mv "$f" "${f// /-}"
done

echo "==> Creating draft release ${TAG}"
gh release create "$TAG" \
  "release/Font-Baker-arm64.dmg" \
  "release/Font-Baker-arm64.dmg.blockmap" \
  "release/Font-Baker-arm64.zip" \
  "release/Font-Baker-arm64.zip.blockmap" \
  "release/latest-mac.yml" \
  --draft \
  --title "OFL Font Baker $TAG" \
  --notes "Release notes pending."

echo ""
echo "Draft created. Edit notes and publish at:"
echo "https://github.com/yamatoiizuka/ofl-font-baker/releases"
