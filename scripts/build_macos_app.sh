#!/bin/bash
# Build a double-clickable macOS app that opens a native paper-trading dashboard.
#
#   ./scripts/build_macos_app.sh "<App Name>" <entry_script.py> <bundle-id> [dest_dir]
#   e.g. ./scripts/build_macos_app.sh "GQ Forex"  run_fx.py     com.gq.fx
#        ./scripts/build_macos_app.sh "GQ Crypto" run_crypto.py com.gq.crypto
#
# dest_dir defaults to ~/Desktop. PYTHON env var overrides the interpreter.
set -euo pipefail

REPO="$(cd "$(dirname "$0")/.." && pwd)"
NAME="${1:-GQ Dashboard}"
ENTRY="${2:-run.py}"
BUNDLE_ID="${3:-com.gq.dashboard}"
DEST="${4:-$HOME/Desktop}"
EXE="$(echo "$NAME" | tr ' A-Z' '-a-z')"
APP="$DEST/$NAME.app"

# Pick an interpreter that has BOTH the harness deps and pywebview.
PYTHON="${PYTHON:-}"
if [ -z "$PYTHON" ]; then
  for cand in /usr/local/bin/python3 /opt/homebrew/bin/python3 "$(command -v python3)"; do
    if [ -x "$cand" ] && "$cand" -c "import numpy, webview" >/dev/null 2>&1; then PYTHON="$cand"; break; fi
  done
fi
[ -z "$PYTHON" ] && { echo "No python with numpy+webview found; install pywebview."; exit 1; }

echo "Building '$NAME' -> $APP   (python: $PYTHON, entry: $ENTRY)"
rm -rf "$APP"; mkdir -p "$APP/Contents/MacOS" "$APP/Contents/Resources"

cat > "$APP/Contents/Info.plist" <<PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
  <key>CFBundleName</key><string>$NAME</string>
  <key>CFBundleDisplayName</key><string>$NAME</string>
  <key>CFBundleIdentifier</key><string>$BUNDLE_ID</string>
  <key>CFBundleVersion</key><string>1.0</string>
  <key>CFBundlePackageType</key><string>APPL</string>
  <key>CFBundleExecutable</key><string>$EXE</string>
  <key>CFBundleIconFile</key><string>AppIcon</string>
  <key>LSMinimumSystemVersion</key><string>11.0</string>
  <key>NSHighResolutionCapable</key><true/>
</dict></plist>
PLIST

ICNS="$REPO/assets/AppIcon.icns"
[ -f "$ICNS" ] && cp "$ICNS" "$APP/Contents/Resources/AppIcon.icns"

cat > "$APP/Contents/MacOS/$EXE" <<LAUNCH
#!/bin/bash
cd "$REPO" || exit 1
exec "$PYTHON" "$ENTRY" app
LAUNCH
chmod +x "$APP/Contents/MacOS/$EXE"
xattr -dr com.apple.quarantine "$APP" 2>/dev/null || true
echo "Done -> $APP"
