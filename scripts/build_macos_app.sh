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
  <key>LSMinimumSystemVersion</key><string>11.0</string>
  <key>LSUIElement</key><true/>
</dict></plist>
PLIST

# Launcher — values baked in at build time so it works when launched from Finder.
cat > "$APP/Contents/MacOS/gq-dashboard" <<LAUNCH
#!/bin/bash
REPO="$REPO"
PYTHON="$PYTHON"
PORT=$PORT
URL="http://localhost:\$PORT/dashboard.html"
cd "\$REPO" || exit 1

# Refresh dashboard.html + servable state (fast, no network).
"\$PYTHON" run.py dashboard --no-serve >/dev/null 2>&1 || true

# Start the static server if nothing is listening on the port.
if ! /usr/sbin/lsof -i ":\$PORT" -sTCP:LISTEN >/dev/null 2>&1; then
  nohup "\$PYTHON" -m http.server "\$PORT" --directory "\$REPO" >/dev/null 2>&1 &
  sleep 1
fi

# Open the dashboard. Chrome app-mode if present (standalone window), else default browser.
if [ -d "/Applications/Google Chrome.app" ]; then
  open -na "Google Chrome" --args --app="\$URL" --window-size=1100,820
else
  open "\$URL"
fi
LAUNCH

chmod +x "$APP/Contents/MacOS/gq-dashboard"

# De-quarantine so first launch doesn't get blocked (best effort).
xattr -dr com.apple.quarantine "$APP" 2>/dev/null || true

echo "Done. Double-click '$APP' (or drag it to your Dock)."
