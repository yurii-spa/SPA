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

# ── ПОБУДКА НЕ ТЕРЯЕТСЯ (ARB 16.10, запись пульта) ──────────────────────────
# Прежде событие, пришедшее, пока приём занят (замок) или в окне дребезга, ОТБРАСЫВАЛОСЬ
# («busy — skip» / «debounce — skip»), а следующего события могло не быть никогда: пульт будит
# приём ОДНИМ переименованием `inbox/.cockpit-wake`. Замер 16.10: прогон приёма длится 15–17 мин
# (проверка истории по каждой new-карточке), а замок считался мёртвым через 300 с по ВОЗРАСТУ —
# то есть событие посреди прогона снимало ЖИВОЙ замок и запускало ВТОРОЙ приём параллельно.
# Теперь: (1) живость держателя — по pid в замке, возраст только как потолок; (2) занято ⇒
# событие оставляется отметкой PENDING, и держатель после прогона прогоняет приём ещё раз
# (коалесценция вместо сброса); (3) дребезг ⇒ ждём остаток окна, а не выходим; (4) побудка,
# пришедшая во время прогона (`.cockpit-wake` сменился после начала прохода; точность — секунда,
# побудку в ту же секунду ловит страховка цикла), — тоже повод для повтора.
# Повтор безопасен: принятая карточка помечена `intake_seen` и приёмом больше не трогается.
PENDING="/tmp/spa_inbox_intake.pending"
WAKE="$REPO/inbox/.cockpit-wake"
LOCK_MAX_AGE=7200   # потолок: живой pid старше 2 ч — зависший прогон или переиспользованный номер
MAX_PASSES=5
mtime() { stat -c %Y "$1" 2>/dev/null || stat -f %m "$1" 2>/dev/null || echo 0; }

acquire_lock() {
    if mkdir "$LOCKDIR" 2>/dev/null; then echo "$$" > "$LOCKDIR/pid"; return 0; fi
    local holder age
    holder="$(cat "$LOCKDIR/pid" 2>/dev/null)"
    age=$(( $(date +%s) - $(mtime "$LOCKDIR") ))
    if [ -n "$holder" ] && kill -0 "$holder" 2>/dev/null && [ "$age" -le "$LOCK_MAX_AGE" ]; then
        return 1                                    # держатель жив — не трогать
    fi
    if [ -z "$holder" ] && [ "$age" -le 300 ]; then
        return 1                                    # замок без pid (только что взят / старый формат)
    fi
    echo "[$(ts)] stale lock (holder=${holder:-нет}, age=${age}s) — reclaim" >> "$LOG"
    rm -rf "$LOCKDIR"
    mkdir "$LOCKDIR" 2>/dev/null || return 1
    echo "$$" > "$LOCKDIR/pid"
    return 0
}
release_lock() { [ "$(cat "$LOCKDIR/pid" 2>/dev/null)" = "$$" ] && rm -rf "$LOCKDIR"; }

if ! acquire_lock; then
    touch "$PENDING"
    echo "[$(ts)] busy (lock, holder=$(cat "$LOCKDIR/pid" 2>/dev/null || echo '?')) — событие оставлено PENDING, держатель повторит" >> "$LOG"
    exit 0
fi
trap release_lock EXIT

# ── debounce: burst = one run — ждём остаток окна, событие не выбрасываем ──────
now=$(date +%s)
if [ -f "$TS" ]; then
    last=$(cat "$TS" 2>/dev/null || echo 0)
    if [ $((now - last)) -lt "$DEBOUNCE" ]; then
        wait_s=$(( DEBOUNCE - (now - last) ))
        echo "[$(ts)] debounce (<${DEBOUNCE}s) — жду ${wait_s}s, событие не теряю" >> "$LOG"
        sleep "$wait_s"
    fi
fi

URGENT=0
pass=0
while :; do
    pass=$((pass + 1))
    rm -f "$PENDING"
    RUN_START=$(date +%s)
    WAKE_SEEN="$(mtime "$WAKE")"           # побудка, которую этот проход уже покрывает
    echo "$RUN_START" > "$TS"
    # ── settle: let a burst of writes coalesce into one run ─────────────────
    sleep "$SETTLE"
    echo "[$(ts)] === intake START (проход $pass) ===" >> "$LOG"

    # ── run the HARD-limited intake (cards + notify only) ───────────────────
    OUT=$("$PY" -c "from spa_core.owner_queue.intake import run_note_intake; import json; print(json.dumps(run_note_intake()))" 2>>"$LOG")
    RC=$?
    echo "[$(ts)] intake result rc=$RC: ${OUT:-<none>}" >> "$LOG"
    echo "${OUT:-}" | grep -q '"urgent": true' && URGENT=1

    # ── coordination log ────────────────────────────────────────────────────
    "$PY" scripts/log_session_change.py --summary "EVENT INTAKE: ${OUT:-fail}" --files "nimbalyst-local/tracker/" --verified "event-triggered intake" >/dev/null 2>&1 || true

    # ── событие во время прогона ⇒ ещё проход (коалесценция, не сброс) ───────
    if [ -f "$PENDING" ] || [ "$(mtime "$WAKE")" != "$WAKE_SEEN" ]; then
        if [ "$pass" -ge "$MAX_PASSES" ]; then
            echo "[$(ts)] coalesce: предел $MAX_PASSES проходов — остаток подхватит страховка цикла (cockpit-rewake)" >> "$LOG"
            break
        fi
        echo "[$(ts)] coalesce: событие пришло во время прогона — ещё проход" >> "$LOG"
        continue
    fi
    break
done

# ── «срочно» → сразу полный цикл (owner-approved explicit exception) ─────────
if [ "$URGENT" -eq 1 ]; then
    echo "[$(ts)] СРОЧНО → kickstart full cycle (com.spa.orchestrator)" >> "$LOG"
    launchctl kickstart -k "gui/$(id -u)/com.spa.orchestrator" >/dev/null 2>&1 || true
fi

echo "[$(ts)] === intake END ===" >> "$LOG"
exit 0
