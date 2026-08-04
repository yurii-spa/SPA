#!/bin/bash
# scripts/agent_work_digest.sh — launchd wrapper for com.spa.work_digest
# «Что сделано за вчера» (РАБОТА/девелопмент, простым языком) → Telegram, 09:00.
# Owner-requested 2026-07-16. DISTINCT from com.spa.digest_daily (that one = PORTFOLIO
# report: equity/P&L/APY/positions). This one = work-activity digest (journal/commits).
# Renamed from the retired label com.spa.morning_digest (avoid RETIRED_LABELS collision).
# bash-wrapper (launchd can't exec miniconda-python → exit 78). /tmp logs (invariant #12).
set -uo pipefail

REPO="/Users/yuriikulieshov/Documents/SPA_Claude"
PY="/Users/yuriikulieshov/miniconda3/bin/python3"
LOG="/tmp/spa_work_digest.log"

export HOME="/Users/yuriikulieshov"
export PATH="/Users/yuriikulieshov/.local/bin:/opt/homebrew/bin:/Users/yuriikulieshov/miniconda3/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin:${PATH:-}"

cd "$REPO" || exit 0
ts() { date "+%Y-%m-%d %H:%M:%S %Z"; }

if [ -f "$LOG" ] && [ "$(wc -l < "$LOG" 2>/dev/null || echo 0)" -gt 300 ]; then
    tail -100 "$LOG" > "$LOG.tmp" && mv "$LOG.tmp" "$LOG"
fi

echo "[$(ts)] === work digest START ===" >> "$LOG"
"$PY" "$REPO/scripts/morning_work_digest.py" >> "$LOG" 2>&1
RC=$?
echo "[$(ts)] === work digest END (exit $RC) ===" >> "$LOG"
exit 0
