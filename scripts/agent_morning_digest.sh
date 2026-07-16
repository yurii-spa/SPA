#!/bin/bash
# scripts/agent_morning_digest.sh — launchd wrapper for com.spa.morning_digest
# Runs the "what got done yesterday" work-digest once at 09:00 → Telegram (owner-requested
# 2026-07-16). bash-wrapper because launchd cannot exec miniconda-python directly (exit 78
# EX_CONFIG). Logs to /tmp per invariant #12 (never ~/Documents → TCC exit-78).
# Plist: ProgramArguments = [/bin/bash, <abs path to this file>], StartCalendarInterval 09:00.
set -uo pipefail

REPO="/Users/yuriikulieshov/Documents/SPA_Claude"
PY="/Users/yuriikulieshov/miniconda3/bin/python3"
LOG="/tmp/spa_morning_digest.log"

export HOME="/Users/yuriikulieshov"
# .local/bin for the headless `claude` binary; homebrew/miniconda for python + tools.
export PATH="/Users/yuriikulieshov/.local/bin:/opt/homebrew/bin:/Users/yuriikulieshov/miniconda3/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin:${PATH:-}"

cd "$REPO" || exit 0
ts() { date "+%Y-%m-%d %H:%M:%S %Z"; }

# bound the log
if [ -f "$LOG" ] && [ "$(wc -l < "$LOG" 2>/dev/null || echo 0)" -gt 300 ]; then
    tail -100 "$LOG" > "$LOG.tmp" && mv "$LOG.tmp" "$LOG"
fi

echo "[$(ts)] === morning digest START ===" >> "$LOG"
"$PY" "$REPO/scripts/morning_work_digest.py" >> "$LOG" 2>&1
RC=$?
echo "[$(ts)] === morning digest END (exit $RC) ===" >> "$LOG"
exit 0
