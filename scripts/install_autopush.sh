#!/bin/bash
# install_autopush.sh — Install launchd agent for automatic 90-min pushes
# Run once: bash ~/Documents/SPA_Claude/scripts/install_autopush.sh

set -euo pipefail
PLIST="$HOME/Library/LaunchAgents/com.spa.autopush.plist"
LOG_DIR="$HOME/Library/Logs/SPA"
mkdir -p "$LOG_DIR"

cat > "$PLIST" << PLIST_EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN"
  "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key>
  <string>com.spa.autopush</string>
  <key>ProgramArguments</key>
  <array>
    <string>/bin/bash</string>
    <string>$HOME/Documents/SPA_Claude/scripts/auto_push.sh</string>
  </array>
  <key>StartInterval</key>
  <integer>5400</integer>
  <key>RunAtLoad</key>
  <true/>
  <key>StandardOutPath</key>
  <string>$LOG_DIR/autopush.log</string>
  <key>StandardErrorPath</key>
  <string>$LOG_DIR/autopush_err.log</string>
  <key>EnvironmentVariables</key>
  <dict>
    <key>PATH</key>
    <string>/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin</string>
  </dict>
</dict>
</plist>
PLIST_EOF

# Unload first if already loaded
launchctl unload "$PLIST" 2>/dev/null || true
launchctl load "$PLIST"

echo "✅ com.spa.autopush loaded"
echo "   Runs every 90 minutes (5400 seconds)"
echo "   Also runs immediately on load (RunAtLoad=true)"
echo "   Logs: $LOG_DIR/autopush.log"
echo ""
echo "To check status:  launchctl list | grep spa"
echo "To stop:          launchctl unload $PLIST"
echo "To view log:      tail -f $LOG_DIR/autopush.log"
