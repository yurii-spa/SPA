#!/usr/bin/env bash
# install_all_agents.sh — Install and load all SPA LaunchAgents
# AGENT-001 fix (2026-06-22)
#
# Устанавливает:
#   com.spa.rules_watchdog   — Policy Enforcer monitor (каждые 5 мин)
#   com.spa.autopush         — Auto-push pending scripts (каждые 90 мин)
#   com.spa.cycle_gap_monitor — Detect missed daily cycles (каждые 5 мин)
#   com.spa.daily_cycle      — Daily paper trading at 08:00
#
# Запуск: bash ~/Documents/SPA_Claude/scripts/install_all_agents.sh

set -euo pipefail

LAUNCHD_DIR="$HOME/Library/LaunchAgents"
REPO="/Users/yuriikulieshov/Documents/SPA_Claude"

echo "=== SPA LaunchAgents Installer (AGENT-001) ==="
echo ""

mkdir -p "$LAUNCHD_DIR"

install_agent() {
    local src="$1"
    local label="$2"
    local dst="$LAUNCHD_DIR/$label.plist"

    echo "--- $label ---"

    # Unload if already loaded (ignore errors)
    launchctl unload "$dst" 2>/dev/null || true

    # Copy plist
    cp "$src" "$dst"
    echo "  Copied: $dst"

    # Load
    launchctl load "$dst"
    echo "  Loaded ✓"

    # Verify
    if launchctl list | grep -q "$label"; then
        PID=$(launchctl list | grep "$label" | awk '{print $1}')
        echo "  Running: PID=$PID"
    else
        echo "  Loaded (not yet started — normal for calendar/interval triggers)"
    fi
    echo ""
}

# 1. Rules Watchdog — critical, runs every 5 min
install_agent "$REPO/launchd/com.spa.rules_watchdog.plist" "com.spa.rules_watchdog"

# 2. Autopush — runs every 90 min, pushes pending scripts
install_agent "$REPO/scripts/com.spa.autopush.plist" "com.spa.autopush"

# 3. Cycle Gap Monitor — runs every 5 min, detects missed cycles
install_agent "$REPO/scripts/com.spa.cycle_gap_monitor.plist" "com.spa.cycle_gap_monitor"

# 4. Daily Cycle — runs at 08:00, RunAtLoad=false so no immediate run
install_agent "$REPO/scripts/com.spa.daily_cycle.plist" "com.spa.daily_cycle"

echo "=== Status ==="
launchctl list | grep "com.spa" || echo "No com.spa agents found"

echo ""
echo "=== Logs ==="
echo "  Watchdog:   tail -f /tmp/spa_watchdog.log"
echo "  Autopush:   tail -f /tmp/spa_autopush.log"
echo "  CycleGap:   tail -f /tmp/spa_cycle_gap_monitor.log"
echo "  DailyCycle: tail -f $REPO/logs/launchd_stdout.log"
echo ""
echo "=== Done: all SPA agents installed and loaded ==="
