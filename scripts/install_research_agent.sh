#!/bin/bash
# Install (or remove) a launchd agent that runs the daily research script on a
# real OS timer — runs whether or not any app is open (unlike app-bound schedules).
#
#   ./scripts/install_research_agent.sh            # install (daily 09:05 local)
#   ./scripts/install_research_agent.sh --uninstall
set -euo pipefail

LABEL="com.gq.research"
PLIST="$HOME/Library/LaunchAgents/$LABEL.plist"
SCRIPT="/Users/Geno/Documents/GitHub/GQ/scripts/daily_research.sh"
DOMAIN="gui/$(id -u)"

if [ "${1:-}" = "--uninstall" ]; then
  launchctl bootout "$DOMAIN/$LABEL" 2>/dev/null || true
  rm -f "$PLIST"
  echo "Removed research agent ($LABEL)."
  exit 0
fi

chmod +x "$SCRIPT"
mkdir -p "$HOME/Library/LaunchAgents"

cat > "$PLIST" <<PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
  <key>Label</key><string>$LABEL</string>
  <key>ProgramArguments</key><array>
    <string>/bin/bash</string><string>$SCRIPT</string>
  </array>
  <key>StartCalendarInterval</key><dict>
    <key>Hour</key><integer>9</integer>
    <key>Minute</key><integer>5</integer>
  </dict>
  <key>StandardOutPath</key><string>/tmp/gq_research.out</string>
  <key>StandardErrorPath</key><string>/tmp/gq_research.err</string>
</dict></plist>
PLIST

launchctl bootout "$DOMAIN/$LABEL" 2>/dev/null || true
launchctl bootstrap "$DOMAIN" "$PLIST"
echo "Installed research agent ($LABEL) — runs daily at 09:05 local via launchd."
echo "Missed runs while the Mac is asleep/off run at next wake (launchd default)."
