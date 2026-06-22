#!/usr/bin/env bash
# install_rules_watchdog.sh — установить LaunchAgent для Rules Watchdog
set -euo pipefail

PLIST="com.spa.rules_watchdog.plist"
SRC="$HOME/Documents/SPA_Claude/launchd/$PLIST"
DST="$HOME/Library/LaunchAgents/$PLIST"
LOGDIR="$HOME/Documents/SPA_Claude/logs"

mkdir -p "$LOGDIR"

cp "$SRC" "$DST"
launchctl unload "$DST" 2>/dev/null || true
launchctl load -w "$DST"
echo "✅ com.spa.rules_watchdog installed and loaded"
echo "   Logs: $LOGDIR/rules_watchdog.log"
echo "   Runs every 300 seconds"
