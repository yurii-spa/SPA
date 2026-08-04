#!/bin/bash
# ============================================================================
# scripts/agent_inbox_intake.sh — событийный ЛЁГКИЙ интейк Inbox (owner-approved 2026-07-15)
# ============================================================================
# Триггер: LaunchAgent com.spa.inbox_watch (WatchPaths на inbox/) — срабатывает при
# появлении/изменении файла-заметки в inbox/ (Obsidian). Делает ТОЛЬКО:
#   классификация (Claude через ask_router) → карточка/идея/вопрос → ответ в Telegram.
# НИКАКОГО кода/пушей/деплоя/исполнения (Python-модуль их не вызывает). Полный цикл
# (com.spa.orchestrator) продолжает ИСПОЛНЯТЬ задачи по расписанию.
#
# Защита: flock (нет параллельных запусков) + debounce 60с (бурст = один запуск) +
# settle 5с (коалесценция бурста) + coord-log + fail-safe (упал → карточка ждёт обычного цикла).
# «срочно» в заметке → сразу kickstart полного цикла (явная команда владельца, разрешённое исключение).
# ============================================================================

set -uo pipefail

REPO="/Users/yuriikulieshov/Documents/SPA_Claude"
PY="/Users/yuriikulieshov/miniconda3/bin/python3"
LOG="/tmp/spa_inbox_intake.log"
LOCKDIR="/tmp/spa_inbox_intake.lock.d"
TS="/tmp/spa_inbox_intake.ts"
DEBOUNCE=60
SETTLE=5

export HOME="/Users/yuriikulieshov"
export PATH="/Users/yuriikulieshov/.local/bin:/opt/homebrew/bin:/Users/yuriikulieshov/miniconda3/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin:${PATH:-}"
cd "$REPO" || exit 0
ts() { date "+%Y-%m-%d %H:%M:%S %Z"; }

# bound log
if [ -f "$LOG" ] && [ "$(wc -l < "$LOG" 2>/dev/null || echo 0)" -gt 500 ]; then tail -200 "$LOG" > "$LOG.tmp" && mv "$LOG.tmp" "$LOG"; fi

# ── lock: no overlapping runs (macOS has no flock → atomic mkdir) ───────────
# stale-lock guard: a run older than 300s is dead → reclaim.
if [ -d "$LOCKDIR" ]; then
    age=$(( $(date +%s) - $(stat -f %m "$LOCKDIR" 2>/dev/null || echo 0) ))
    [ "$age" -gt 300 ] && rmdir "$LOCKDIR" 2>/dev/null
fi
if ! mkdir "$LOCKDIR" 2>/dev/null; then echo "[$(ts)] busy (lock) — skip" >> "$LOG"; exit 0; fi
trap 'rmdir "$LOCKDIR" 2>/dev/null' EXIT

# ── debounce: skip if ran < DEBOUNCE sec ago ────────────────────────────────
now=$(date +%s)
if [ -f "$TS" ]; then last=$(cat "$TS" 2>/dev/null || echo 0); if [ $((now - last)) -lt "$DEBOUNCE" ]; then echo "[$(ts)] debounce (<${DEBOUNCE}s) — skip" >> "$LOG"; exit 0; fi; fi
echo "$now" > "$TS"

# ── settle: let a burst of writes coalesce into one run ─────────────────────
sleep "$SETTLE"
echo "[$(ts)] === intake START ===" >> "$LOG"

# ── run the HARD-limited intake (cards + notify only) ───────────────────────
OUT=$("$PY" -c "from spa_core.owner_queue.intake import run_note_intake; import json; print(json.dumps(run_note_intake()))" 2>>"$LOG")
RC=$?
echo "[$(ts)] intake result rc=$RC: ${OUT:-<none>}" >> "$LOG"

# ── coordination log ────────────────────────────────────────────────────────
"$PY" scripts/log_session_change.py --summary "EVENT INTAKE: ${OUT:-fail}" --files "nimbalyst-local/tracker/" --verified "event-triggered intake" >/dev/null 2>&1 || true

# ── «срочно» → сразу полный цикл (owner-approved explicit exception) ─────────
if echo "${OUT:-}" | grep -q '"urgent": true'; then
    echo "[$(ts)] СРОЧНО → kickstart full cycle (com.spa.orchestrator)" >> "$LOG"
    launchctl kickstart -k "gui/$(id -u)/com.spa.orchestrator" >/dev/null 2>&1 || true
fi

echo "[$(ts)] === intake END ===" >> "$LOG"
exit 0
