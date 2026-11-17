#!/bin/bash
# Build Refract.app and a disk image (dist/Refract-<version>-macos-<arch>.dmg) holding
# the app, the license and Refract's source code (GPL-3.0, collect_licenses.py).
#
#   tools/packaging/build_macos.sh
#
# The build runs in .venv-build (only the runtime dependencies and PyInstaller),
# created with uv when missing. Signing and notarization:
#   REFRACT_SIGN_ID        codesign identity, e.g. "Developer ID Application: Name (TEAMID)".
#                          Unset: ad-hoc signature (runs on this Mac; Gatekeeper warns elsewhere).
#   REFRACT_NOTARY_PROFILE notarytool keychain profile (xcrun notarytool store-credentials);
#                          set together with a Developer ID to notarize and staple the dmg.
#   REFRACT_TARGET_ARCH    default: this Mac's architecture. Refract is released for arm64
#                          only (no Intel build, PLAN phase 7).
#   REFRACT_BUILD_DIR      where the app is built and signed (default ~/Library/Caches/refract-build):
#                          outside synced folders such as ~/Documents, whose file provider adds
#                          Finder info to .framework folders that codesign refuses. Only the dmg
#                          is copied to dist/.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
cd "$ROOT"
VENV="$ROOT/.venv-build"
PY="$VENV/bin/python"
if [ ! -x "$PY" ]; then
  uv venv -q --python 3.12 "$VENV"
  uv pip install -q --python "$PY" numpy scipy PySide6-Essentials "pyinstaller>=6.10"
fi
VERSION="$("$PY" -c 'import refract; print(refract.__version__)')"
ARCH="${REFRACT_TARGET_ARCH:-$(uname -m)}"
BUILD="${REFRACT_BUILD_DIR:-$HOME/Library/Caches/refract-build}"
DIST="$ROOT/dist"
mkdir -p "$BUILD" "$DIST"

echo "== icons"
"$PY" tools/packaging/make_icon.py "$BUILD/icons"

# the oldest macOS the bundle runs on: the highest minos among the binaries it ships
SITE="$("$PY" -c 'import sysconfig; print(sysconfig.get_paths()["purelib"])')"
MIN=$(
  { find "$SITE/PySide6/Qt/lib" -path '*QtCore.framework/Versions/A/QtCore' -type f
    find "$SITE/numpy" "$SITE/scipy" -name '*.so' | head -50
    "$PY" -c 'import sys; print(sys.executable)'; } |
  while read -r f; do otool -l "$f" 2>/dev/null | awk '/minos/ {print $2}'; done |
  sort -t. -k1,1n -k2,2n | tail -1)
MIN="${MIN:-13.0}"
echo "== minimum macOS $MIN, arch $ARCH"

echo "== pyinstaller"
REFRACT_MIN_MACOS="$MIN" REFRACT_ICON_DIR="$BUILD/icons" REFRACT_TARGET_ARCH="$ARCH" \
  "$VENV/bin/pyinstaller" --noconfirm --clean --log-level WARN \
  --workpath "$BUILD/work" --distpath "$BUILD/dist" tools/packaging/refract.spec
APP="$BUILD/dist/Refract.app"

# files copied from a synced folder (the build venv) may carry the "hidden" flag, and Qt
# skips hidden plugins; also drop Finder info that codesign refuses
chflags -R nohidden "$APP"
xattr -cr "$APP"
# the light and dark icon (Info.plist CFBundleIconName), when Xcode's actool made it
if [ -f "$BUILD/icons/Assets.car" ]; then cp "$BUILD/icons/Assets.car" "$APP/Contents/Resources/"; fi

echo "== licenses"
"$PY" tools/packaging/collect_licenses.py "$APP/Contents/Resources/LICENSES"

echo "== sign"
xattr -cr "$APP"
ENT="$ROOT/tools/packaging/entitlements.plist"
if [ -n "${REFRACT_SIGN_ID:-}" ]; then
  # hardened runtime, inside out (nested code first), as notarization requires
  find "$APP/Contents" \( -name '*.dylib' -o -name '*.so' -o -perm -111 -type f \) ! -path '*/MacOS/Refract' -print0 |
    xargs -0 codesign --force --timestamp --options runtime --sign "$REFRACT_SIGN_ID" 2>/dev/null || true
  find "$APP/Contents" -name '*.framework' -type d -print0 |
    xargs -0 codesign --force --timestamp --options runtime --sign "$REFRACT_SIGN_ID"
  codesign --force --timestamp --options runtime --entitlements "$ENT" --sign "$REFRACT_SIGN_ID" "$APP"
else
  codesign --force --deep --sign - "$APP"
fi
codesign --verify --deep --strict "$APP"

echo "== self-test"
"$APP/Contents/MacOS/Refract" selftest --keep "$BUILD/selftest"

echo "== disk image"
DMG="$BUILD/Refract-$VERSION-macos-$ARCH.dmg"
STAGE="$BUILD/dmg"
rm -rf "$STAGE" "$DMG"
mkdir -p "$STAGE"
cp -R "$APP" "$STAGE/"
ln -s /Applications "$STAGE/Applications"
LIC="$APP/Contents/Resources/LICENSES"
cp "$LIC/NOTICE.txt" "$STAGE/Read Me.txt"
cp "$LIC/Refract/LICENSE.txt" "$STAGE/License.txt"  # GPL-3.0: license and source beside the app
cp "$LIC/Refract/refract-$VERSION-source.tar.gz" "$STAGE/"
hdiutil create -quiet -volname "Refract $VERSION" -srcfolder "$STAGE" -fs HFS+ -format UDZO "$DMG"
if [ -n "${REFRACT_SIGN_ID:-}" ]; then
  codesign --force --timestamp --sign "$REFRACT_SIGN_ID" "$DMG"
  if [ -n "${REFRACT_NOTARY_PROFILE:-}" ]; then
    echo "== notarize"
    xcrun notarytool submit "$DMG" --keychain-profile "$REFRACT_NOTARY_PROFILE" --wait
    xcrun stapler staple "$DMG"
    spctl --assess --type open --context context:primary-signature -v "$DMG"
  fi
fi
cp "$DMG" "$DIST/"
du -sh "$APP" "$DMG"
echo "built $DIST/$(basename "$DMG") (app in $APP)"
