#!/bin/bash
# scripts/install_daily_cycle.sh
# MP-1427 (v10.43): Install launchd daily paper trading cycle
# Run from ~/Documents/SPA_Claude/

set -e
cd ~/Documents/SPA_Claude

PLIST="scripts/com.spa.daily_cycle.plist"
DEST="$HOME/Library/LaunchAgents/com.spa.daily_cycle.plist"
SCRIPT="scripts/run_daily_paper_cycle.sh"

echo "=== SPA Daily Cycle Installer (v10.43) ==="

# Ensure script is executable
chmod +x "$SCRIPT"
echo "✅ $SCRIPT marked executable"

# Ensure logs dir exists
mkdir -p logs
echo "✅ logs/ directory ready"

# Unload if already loaded (ignore errors)
launchctl unload "$DEST" 2>/dev/null || true

# Copy plist to LaunchAgents
cp "$PLIST" "$DEST"
echo "✅ Plist copied to $DEST"

# Load
launchctl load "$DEST"
echo "✅ Daily cycle installed and loaded"
echo ""
echo "Runs at 08:00 UTC daily via CPACycleWithEvidence"
echo "Logs: logs/daily_cycle_YYYYMMDD.log"
echo "launchd stdout: logs/launchd_stdout.log"
echo "launchd stderr: logs/launchd_stderr.log"
echo ""
echo "To unload:   launchctl unload $DEST"
echo "To run now:  bash $SCRIPT"
