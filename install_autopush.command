#!/bin/bash
# install_autopush.command — One-click install of com.spa.autopush launchd agent
# Double-click this file in Finder to install/reload autopush.

set -euo pipefail
SPA="$HOME/Documents/SPA_Claude"
AGENTS="$HOME/Library/LaunchAgents"
LOG_DIR="$HOME/Library/Logs/SPA"

echo "╔══════════════════════════════════════════════════╗"
echo "║  SPA Autopush Install (GoLive criterion fix)     ║"
echo "╚══════════════════════════════════════════════════╝"
echo ""

# Detect working Python (same as daily_cycle for FDA compatibility)
PYTHON=""
DAILY_PLIST="$AGENTS/com.spa.daily_cycle.plist"
if [ -f "$DAILY_PLIST" ]; then
    PYTHON=$(grep -oE '/[^<>]*python[^<>]*' "$DAILY_PLIST" | head -1 || true)
fi
# Fallbacks
for p in "$HOME/miniconda3/bin/python3" "$HOME/miniforge3/bin/python3" \
          "/opt/homebrew/bin/python3" "/usr/local/bin/python3" "/usr/bin/python3"; do
    if [ -z "$PYTHON" ] && [ -x "$p" ]; then PYTHON="$p"; fi
done
if [ -z "$PYTHON" ]; then PYTHON=$(which python3 2>/dev/null || echo "python3"); fi
echo "  Python: $PYTHON ($($PYTHON --version 2>&1))"

mkdir -p "$AGENTS" "$LOG_DIR"

# Unload any previous version
launchctl unload "$AGENTS/com.spa.autopush.plist" 2>/dev/null || true

# Write the plist using auto_push.py (data file pusher)
cat > "$AGENTS/com.spa.autopush.plist" << PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>com.spa.autopush</string>
    <key>ProgramArguments</key>
    <array>
        <string>${PYTHON}</string>
        <string>${SPA}/auto_push.py</string>
    </array>
    <key>StartInterval</key>
    <integer>5400</integer>
    <key>RunAtLoad</key>
    <false/>
    <key>StandardOutPath</key>
    <string>${LOG_DIR}/autopush.log</string>
    <key>StandardErrorPath</key>
    <string>${LOG_DIR}/autopush_err.log</string>
    <key>EnvironmentVariables</key>
    <dict>
        <key>PATH</key>
        <string>/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin</string>
        <key>HOME</key>
        <string>${HOME}</string>
    </dict>
</dict>
</plist>
PLIST

launchctl load "$AGENTS/com.spa.autopush.plist"
echo ""
echo "  ✅ com.spa.autopush loaded into launchd"
echo "     Interval: every 90 minutes"
echo "     Script:   $SPA/auto_push.py"
echo "     Log:      $LOG_DIR/autopush.log"
echo ""
launchctl list | grep com.spa || echo "  (no spa services listed yet)"
echo ""
echo "Done. You can close this window."
