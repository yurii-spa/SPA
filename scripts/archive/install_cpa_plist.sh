#!/bin/bash
# Installs CPA daily cycle launchd agent
# Run: bash scripts/install_cpa_plist.sh

PLIST="com.spa.cpa_daily.plist"
LAUNCH_AGENTS="$HOME/Library/LaunchAgents"
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"

echo "Installing CPA daily cycle launchd agent..."

cp "$SCRIPT_DIR/$PLIST" "$LAUNCH_AGENTS/$PLIST"
launchctl load "$LAUNCH_AGENTS/$PLIST"

echo "✅ Installed: $LAUNCH_AGENTS/$PLIST"
echo "Runs at 09:00 daily"
echo "Log: ~/Documents/SPA_Claude/logs/cpa_daily.log"
echo ""
echo "To uninstall: launchctl unload ~/Library/LaunchAgents/$PLIST && rm ~/Library/LaunchAgents/$PLIST"
