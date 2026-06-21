#!/bin/bash
# Fix down agents: system_health_morning, system_health_evening, uptime_monitor plist
set -e
cd /Users/yuriikulieshov/Documents/SPA_Claude

echo "=== Installing system_health plist files ==="
cp scripts/com.spa.system_health_morning.plist ~/Library/LaunchAgents/
cp scripts/com.spa.system_health_evening.plist ~/Library/LaunchAgents/

# Unload if already loaded (ignore errors)
launchctl unload ~/Library/LaunchAgents/com.spa.system_health_morning.plist 2>/dev/null || true
launchctl unload ~/Library/LaunchAgents/com.spa.system_health_evening.plist 2>/dev/null || true

launchctl load ~/Library/LaunchAgents/com.spa.system_health_morning.plist
launchctl load ~/Library/LaunchAgents/com.spa.system_health_evening.plist
echo "system_health_morning: loaded"
echo "system_health_evening: loaded"

echo ""
echo "=== Reinstalling uptime_monitor plist (plist was malformed, now fixed) ==="
cp scripts/com.spa.uptime_monitor.plist ~/Library/LaunchAgents/
launchctl unload ~/Library/LaunchAgents/com.spa.uptime_monitor.plist 2>/dev/null || true
launchctl load ~/Library/LaunchAgents/com.spa.uptime_monitor.plist
echo "uptime_monitor: reloaded"

echo ""
echo "=== Running system_health_check now (first run to create logs) ==="
/Users/yuriikulieshov/miniconda3/bin/python3 scripts/system_health_check.py 2>&1 | tail -20

echo ""
echo "=== Verify launchctl ==="
launchctl list | grep "com.spa.system_health\|com.spa.uptime"

echo ""
echo "DONE. system_health agents installed and first run complete."
