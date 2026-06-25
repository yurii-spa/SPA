#!/bin/bash
# scripts/daily_backup.sh — DAILY snapshot of ALL data/*.json into data/backups/.
#
# Runs BEFORE the 06:00 UTC daily_cycle so a pre-cycle snapshot always exists. Wraps
# scripts/daily_backup.py (stdlib-only, atomic, deterministic, 30-day retention).
# Scheduled by launchd com.spa.daily_backup. Logs to logs/daily_backup.log.
set -uo pipefail

REPO="/Users/yuriikulieshov/Documents/SPA_Claude"
PY="/Users/yuriikulieshov/miniconda3/bin/python3"
LOG="$REPO/logs/daily_backup.log"

mkdir -p "$REPO/logs"
cd "$REPO" || { echo "$(date -u): [FAIL] cannot cd $REPO" >> "$LOG"; exit 1; }

echo "=== $(date -u +%Y-%m-%dT%H:%M:%SZ) daily_backup start ===" >> "$LOG"
"$PY" "$REPO/scripts/daily_backup.py" --retention 30 >> "$LOG" 2>&1
STATUS=$?
echo "=== $(date -u +%Y-%m-%dT%H:%M:%SZ) daily_backup exit=$STATUS ===" >> "$LOG"
exit $STATUS
