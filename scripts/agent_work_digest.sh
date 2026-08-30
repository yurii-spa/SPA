#!/bin/bash
# AGENT_MODULE: scripts.morning_work_digest
# Точка входа, НЕСУЩАЯ КОНТРАКТ агента. Объявлено 30.08: без неё паспорт не
# может назвать ни права, ни ограничения — их читают ИЗ МОДУЛЯ, а вывести его
# из многошаговой обёртки нельзя. Основание: единственная цель: строка 46 запускает scripts/morning_work_digest.py.
# scripts/agent_work_digest.sh — launchd wrapper for com.spa.work_digest
# «Что сделано за вчера» (РАБОТА/девелопмент, простым языком) → Telegram, 09:00.
# Owner-requested 2026-07-16. DISTINCT from com.spa.digest_daily (that one = PORTFOLIO
# report: equity/P&L/APY/positions). This one = work-activity digest (journal/commits).
# Renamed from the retired label com.spa.morning_digest (avoid RETIRED_LABELS collision).
# bash-wrapper (launchd can't exec miniconda-python → exit 78). /tmp logs (invariant #12).
#
# EXIT CODE IS HONEST (ADR-070 п.11, решение владельца 2026-08-07): «не ушло — ошибка,
# agent_health видит». The python half already answers the delivery question honestly —
# morning_work_digest.py returns 1 whenever Telegram delivery is not CONFIRMED — and this
# wrapper used to throw that answer away with an unconditional `exit 0`, so launchd
# recorded a failed digest as LastExitStatus=0 and agent_health (which reads exactly that)
# reported the agent OK. Same fail-OPEN shape as the canonical agent_template.sh was
# written to avoid: that one "captures the python exit code and EXITS WITH IT".
# A scheduled agent is NOT revived on a nonzero exit (self_heal acts on residency/PID),
# so an honest code surfaces as an agent_health WARNING — visible, no kickstart loop.
set -uo pipefail

# SPA_DIGEST_* exist ONLY so tests can point the wrapper at a sandbox; production plists
# set none of them (same convention as SPA_AGENT_REPO_ROOT/SPA_AGENT_PYTHON in the template).
REPO="${SPA_DIGEST_REPO:-/Users/yuriikulieshov/Documents/SPA_Claude}"
PY="${SPA_DIGEST_PYTHON:-/Users/yuriikulieshov/miniconda3/bin/python3}"
LOG="${SPA_DIGEST_LOG:-/tmp/spa_work_digest.log}"

export HOME="${HOME:-/Users/yuriikulieshov}"
export PATH="/Users/yuriikulieshov/.local/bin:/opt/homebrew/bin:/Users/yuriikulieshov/miniconda3/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin:${PATH:-}"

ts() { date "+%Y-%m-%d %H:%M:%S %Z"; }

# An unreachable repo is EX_TEMPFAIL (75), never success: on 2026-08-07 a TCC block made
# ~/Documents unreadable for ~25 min, and under `|| exit 0` that window would have been
# reported as a delivered digest. 75 is the code the template already uses for "environment
# not ready", which keeps it distinguishable from a logic failure (1) and a config one (78).
if ! cd "$REPO" 2>/dev/null; then
    echo "[$(ts)] === work digest END (exit 75: репозиторий недоступен: $REPO) ===" >> "$LOG" 2>/dev/null \
        || echo "work digest: репозиторий недоступен: $REPO" >&2
    exit 75
fi

if [ -f "$LOG" ] && [ "$(wc -l < "$LOG" 2>/dev/null || echo 0)" -gt 300 ]; then
    tail -100 "$LOG" > "$LOG.tmp" && mv "$LOG.tmp" "$LOG"
fi

echo "[$(ts)] === work digest START ===" >> "$LOG"
"$PY" "$REPO/scripts/morning_work_digest.py" >> "$LOG" 2>&1
RC=$?
echo "[$(ts)] === work digest END (exit $RC) ===" >> "$LOG"
exit "$RC"
