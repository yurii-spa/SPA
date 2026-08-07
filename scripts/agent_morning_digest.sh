#!/bin/bash
# scripts/agent_morning_digest.sh — launchd wrapper for com.spa.morning_digest
# Runs the "what got done yesterday" work-digest once at 09:00 → Telegram (owner-requested
# 2026-07-16). bash-wrapper because launchd cannot exec miniconda-python directly (exit 78
# EX_CONFIG). Logs to /tmp per invariant #12 (never ~/Documents → TCC exit-78).
# Plist: ProgramArguments = [/bin/bash, <abs path to this file>], StartCalendarInterval 09:00.
#
# EXIT CODE IS HONEST — see the same block in scripts/agent_work_digest.sh (ADR-070 п.11).
# This label is RETIRED (the live one is com.spa.work_digest) and both wrappers run the SAME
# python; the twin is kept honest so the defect cannot be copied forward from here.
set -uo pipefail

# SPA_DIGEST_* — test-only sandbox overrides; production plists set none of them.
REPO="${SPA_DIGEST_REPO:-/Users/yuriikulieshov/Documents/SPA_Claude}"
PY="${SPA_DIGEST_PYTHON:-/Users/yuriikulieshov/miniconda3/bin/python3}"
LOG="${SPA_DIGEST_LOG:-/tmp/spa_morning_digest.log}"

export HOME="${HOME:-/Users/yuriikulieshov}"
# .local/bin for the headless `claude` binary; homebrew/miniconda for python + tools.
export PATH="/Users/yuriikulieshov/.local/bin:/opt/homebrew/bin:/Users/yuriikulieshov/miniconda3/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin:${PATH:-}"

ts() { date "+%Y-%m-%d %H:%M:%S %Z"; }

# Unreachable repo = EX_TEMPFAIL (75), never success (TCC/wake window, 2026-08-07).
if ! cd "$REPO" 2>/dev/null; then
    echo "[$(ts)] === morning digest END (exit 75: репозиторий недоступен: $REPO) ===" >> "$LOG" 2>/dev/null \
        || echo "morning digest: репозиторий недоступен: $REPO" >&2
    exit 75
fi

# bound the log
if [ -f "$LOG" ] && [ "$(wc -l < "$LOG" 2>/dev/null || echo 0)" -gt 300 ]; then
    tail -100 "$LOG" > "$LOG.tmp" && mv "$LOG.tmp" "$LOG"
fi

echo "[$(ts)] === morning digest START ===" >> "$LOG"
"$PY" "$REPO/scripts/morning_work_digest.py" >> "$LOG" 2>&1
RC=$?
echo "[$(ts)] === morning digest END (exit $RC) ===" >> "$LOG"
exit "$RC"
