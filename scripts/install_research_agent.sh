#!/bin/bash
# Install (or remove) TWO launchd research agents — one per trading style — that
# run on a real OS timer (no app needed). Each builds its own app's knowledge.
#
#   ./scripts/install_research_agent.sh            # install both
#   ./scripts/install_research_agent.sh --uninstall
set -euo pipefail

SCRIPTS="/Users/Geno/Documents/GitHub/GQ/scripts"
DOMAIN="gui/$(id -u)"
# label | script | hour | minute  (staggered so they don't collide)
AGENTS=(
  "com.gq.research.fx|$SCRIPTS/research_fx.sh|9|5"
  "com.gq.research.crypto|$SCRIPTS/research_crypto.sh|9|20"
)

# retire the old combined agent if present
launchctl bootout "$DOMAIN/com.gq.research" 2>/dev/null || true
rm -f "$HOME/Library/LaunchAgents/com.gq.research.plist"

if [ "${1:-}" = "--uninstall" ]; then
  for a in "${AGENTS[@]}"; do
    L="${a%%|*}"; launchctl bootout "$DOMAIN/$L" 2>/dev/null || true
    rm -f "$HOME/Library/LaunchAgents/$L.plist"
  done
  echo "Removed both research agents."
  exit 0
fi

mkdir -p "$HOME/Library/LaunchAgents"
for a in "${AGENTS[@]}"; do
  IFS='|' read -r LABEL SCRIPT HOUR MIN <<< "$a"
  chmod +x "$SCRIPT"
  PLIST="$HOME/Library/LaunchAgents/$LABEL.plist"
  cat > "$PLIST" <<PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
  <key>Label</key><string>$LABEL</string>
  <key>ProgramArguments</key><array><string>/bin/bash</string><string>$SCRIPT</string></array>
  <key>StartCalendarInterval</key><dict><key>Hour</key><integer>$HOUR</integer><key>Minute</key><integer>$MIN</integer></dict>
  <key>StandardOutPath</key><string>/tmp/$LABEL.out</string>
  <key>StandardErrorPath</key><string>/tmp/$LABEL.err</string>
</dict></plist>
PLIST
  launchctl bootout "$DOMAIN/$LABEL" 2>/dev/null || true
  launchctl bootstrap "$DOMAIN" "$PLIST"
  echo "Installed $LABEL — daily at $(printf '%02d:%02d' "$HOUR" "$MIN") local."
done
