#!/usr/bin/env bash
echo "=== Reinstalling com.spa.autopush launchd ==="
PLIST=~/Library/LaunchAgents/com.spa.autopush.plist

# Unload existing if any
launchctl bootout gui/$(id -u) $PLIST 2>/dev/null || true

# Copy plist from repo
cp ~/Documents/SPA_Claude/scripts/com.spa.autopush.plist ~/Library/LaunchAgents/com.spa.autopush.plist

# Load
launchctl bootstrap gui/$(id -u) $PLIST
echo ""
launchctl list com.spa.autopush
echo ""
echo "✅ autopush reinstalled"
read -p "Press Enter to close..."
