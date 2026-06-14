#!/bin/bash
# Build "GQ Dashboard.app" — a double-clickable macOS app that starts the local
# server and opens the live paper-trading dashboard. Zero dependencies.
#
#   ./scripts/build_macos_app.sh [dest_dir]
#
# dest_dir defaults to ~/Desktop. Re-run to rebuild after code changes.
set -euo pipefail

REPO="$(cd "$(dirname "$0")/.." && pwd)"
PYTHON="$(command -v python3)"
DEST="${1:-$HOME/Desktop}"
APP="$DEST/GQ Dashboard.app"
PORT=8000

echo "Building app -> $APP"
echo "  repo:   $REPO"
echo "  python: $PYTHON"

rm -rf "$APP"
mkdir -p "$APP/Contents/MacOS" "$APP/Contents/Resources"

# Info.plist
cat > "$APP/Contents/Info.plist" <<PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
  <key>CFBundleName</key><string>GQ Dashboard</string>
  <key>CFBundleDisplayName</key><string>GQ Dashboard</string>
  <key>CFBundleIdentifier</key><string>com.gq.dashboard</string>
  <key>CFBundleVersion</key><string>1.0</string>
  <key>CFBundlePackageType</key><string>APPL</string>
  <key>CFBundleExecutable</key><string>gq-dashboard</string>
  <key>CFBundleIconFile</key><string>AppIcon</string>
  <key>LSMinimumSystemVersion</key><string>11.0</string>
  <key>NSHighResolutionCapable</key><true/>
</dict></plist>
PLIST

# App icon — generate if missing (needs Pillow), then install into the bundle.
ICNS="$REPO/assets/AppIcon.icns"
if [ ! -f "$ICNS" ] && [ -f "$REPO/scripts/make_icon.py" ]; then
  "$PYTHON" "$REPO/scripts/make_icon.py" >/dev/null 2>&1 || true
fi
if [ -f "$ICNS" ]; then
  cp "$ICNS" "$APP/Contents/Resources/AppIcon.icns"
  echo "  icon:   $ICNS"
fi

# Launcher — runs the fully native pywebview window (real macOS window + Dock icon).
# Values baked in at build time so it works when launched from Finder.
cat > "$APP/Contents/MacOS/gq-dashboard" <<LAUNCH
#!/bin/bash
cd "$REPO" || exit 1
exec "$PYTHON" run.py app
LAUNCH

chmod +x "$APP/Contents/MacOS/gq-dashboard"

# De-quarantine so first launch doesn't get blocked (best effort).
xattr -dr com.apple.quarantine "$APP" 2>/dev/null || true

echo "Done. Double-click '$APP' (or drag it to your Dock)."
