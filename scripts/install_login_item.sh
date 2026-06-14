#!/bin/bash
# Install (or remove) a LaunchAgent that opens GQ Dashboard at login.
#
#   ./scripts/install_login_item.sh            # install + start now
#   ./scripts/install_login_item.sh --uninstall
set -euo pipefail

LABEL="com.gq.dashboard"
PLIST="$HOME/Library/LaunchAgents/$LABEL.plist"
APP_EXE="$HOME/Desktop/GQ Dashboard.app/Contents/MacOS/gq-dashboard"
DOMAIN="gui/$(id -u)"

if [ "${1:-}" = "--uninstall" ]; then
  launchctl bootout "$DOMAIN/$LABEL" 2>/dev/null || true
  rm -f "$PLIST"
  echo "Removed login item ($LABEL)."
  exit 0
fi

[ -x "$APP_EXE" ] || { echo "App not found at: $APP_EXE — build it first (scripts/build_macos_app.sh)"; exit 1; }
mkdir -p "$HOME/Library/LaunchAgents"

cat > "$PLIST" <<PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
  <key>Label</key><string>$LABEL</string>
  <key>ProgramArguments</key><array><string>$APP_EXE</string></array>
  <key>RunAtLoad</key><true/>
  <key>ProcessType</key><string>Interactive</string>
  <key>LimitLoadToSessionType</key><string>Aqua</string>
  <key>StandardOutPath</key><string>/tmp/gq_app.log</string>
  <key>StandardErrorPath</key><string>/tmp/gq_app.log</string>
</dict></plist>
PLIST

# Reload cleanly (bootout if already present, then bootstrap).
launchctl bootout "$DOMAIN/$LABEL" 2>/dev/null || true
launchctl bootstrap "$DOMAIN" "$PLIST"
echo "Installed login item ($LABEL). It will launch GQ Dashboard at every login."
