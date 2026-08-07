#!/bin/bash
# ============================================================================
# scripts/agent_orchestrator.sh — headless orchestrator agent (ENV_SETUP v3 §3.5)
# ============================================================================
# Runs ONE orchestrator cycle by launching a headless Claude Code session that
# executes docs/ORCHESTRATOR_PROTOCOL.md (read STATE → parse Inbox → ingest
# Owner-Done → ADRs → update STATE/journal → notify new Needs-Owner).
#
# The mechanical steps are deterministic (scripts/orchestrator_queue.py); the
# judgment steps are the Claude session. This is project-management, NOT
# risk/execution/monitoring — LLM is allowed here (and forbidden there).
#
# SAFETY / ACTIVATION GATE (Этап 8):
#   INERT by default. Without env SPA_ORCHESTRATOR_ARMED=1 the agent logs a
#   notice and exits 0 WITHOUT invoking Claude. This makes the plist safe to
#   exist (or even be loaded) before the smoke-test. Activate at Stage 8 by
#   setting SPA_ORCHESTRATOR_ARMED=1 in the plist's EnvironmentVariables and
#   choosing the permission mode with the owner.
# ============================================================================

set -uo pipefail

REPO_ROOT="/Users/yuriikulieshov/Documents/SPA_Claude"
CLAUDE_BIN="${CLAUDE_BIN:-/Users/yuriikulieshov/.local/bin/claude}"
PYTHON="/Users/yuriikulieshov/miniconda3/bin/python3"
LOG="/tmp/spa_orchestrator.log"

export PATH="/Users/yuriikulieshov/.local/bin:/Users/yuriikulieshov/miniconda3/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin:${PATH:-}"
export HOME="/Users/yuriikulieshov"

cd "$REPO_ROOT" || exit 1

ts() { date "+%Y-%m-%d %H:%M:%S %Z"; }
echo "[$(ts)] === orchestrator cycle START ===" >> "$LOG"

# Bound the log.
if [ -f "$LOG" ] && [ "$(wc -l < "$LOG")" -gt 800 ]; then
    tail -400 "$LOG" > "$LOG.tmp" && mv "$LOG.tmp" "$LOG"
fi

# ── ARMING GATE ─────────────────────────────────────────────────────────────
if [ "${SPA_ORCHESTRATOR_ARMED:-0}" != "1" ]; then
    echo "[$(ts)] INERT: SPA_ORCHESTRATOR_ARMED != 1 — not invoking Claude. (Activate at Stage 8.)" >> "$LOG"
    echo "[$(ts)] === orchestrator cycle END (inert, exit 0) ===" >> "$LOG"
    exit 0
fi

# ── OWNER-GATE ACTIVE (ADR-OWN-2026-07-autoship, owner-approved full auto-ship) ──
# Mark autonomous context so the deterministic push interlock in push_to_github*.py
# enforces the owner-gate on any landing/ push (SAFE ships to live; owner-gated classes
# — yield numbers / tier naming / legal / solicitation — are routed to a needs-owner card
# by scripts/safe_site_push.py, never auto-shipped). Kill = unset SPA_ORCHESTRATOR_ARMED.
export SPA_AUTONOMOUS=1

# ── DURABLE SESSION IDENTITY (card agent-durable-session-id) ────────────────
# THIS shell is the cycle's long-lived process: it waits for claude below and exits with it.
# Announcing it makes "is that session still working?" a measurement instead of a guess —
# scripts/log_session_change.py records session_pid + its start time, and steps 0a/0b use them
# as the primary criterion (the announcement's age stays the fallback). Without this, every
# entry carried the pid of a one-shot CLI process that was already dead when written, so `ps`
# said "no such process" for every cycle, alive or orphaned.
export SPA_SESSION_PID=$$
export SPA_SESSION_ID="${SPA_SESSION_ID:-cycle-$$}"

# ── CYCLE LOCK (ADR-070 п.9, решение владельца 2026-08-07) ──────────────────
# Один цикл за раз. Карточки от одновременной работы защищены с 30.07, сам цикл — нет:
# захват карточки ловит столкновение уже ПОСЛЕ шагов 0/0a/0b и не ловит вовсе, когда вторая
# сессия берёт следующую карточку и два автономных пушера идут в origin/main наперегонки.
# Замок общий (в главном рабочем дереве — циклы работают из /tmp-worktree), atomic-mkdir,
# живость держателя ИЗМЕРЯЕТСЯ тем же кодом, что шаги 0a/0b. Код 3 = занято живой сессией:
# это не ошибка, а вежливый выход (agent_health не должен краснеть на здоровое поведение).
# Поломка самого замка => `unprotected`, код 0: цикл идёт и говорит об этом вслух.
LOCK_PY="$REPO_ROOT/scripts/orchestrator_cycle_lock.py"
if [ ! -f "$LOCK_PY" ]; then
    # Дерево прода отстаёт от origin (синк идёт Step 0 дневного цикла). Молчать нельзя:
    # незаметно потерянная защита — это класс fail-OPEN, ради которого замок и написан.
    echo "[$(ts)] lock: ⚠️ нет $LOCK_PY — цикл идёт БЕЗ защиты от одновременного прогона" >> "$LOG"
else
    LOCK_OUT="$("$PYTHON" "$LOCK_PY" acquire \
                --session "$SPA_SESSION_ID" --pid "$SPA_SESSION_PID" 2>&1)"
    LOCK_RC=$?
    echo "[$(ts)] lock: $LOCK_OUT" >> "$LOG"
    if [ "$LOCK_RC" -eq 3 ]; then
        echo "[$(ts)] === orchestrator cycle END (busy, polite exit 0) ===" >> "$LOG"
        exit 0
    fi
fi
# Снимаем и при аварийном выходе — брошенный замок хоть и снимается следующим прогоном по
# измеренной смерти держателя, но лишний круг «занято» никому не нужен.
release_lock() {
    [ -f "$LOCK_PY" ] || return 0
    "$PYTHON" "$LOCK_PY" release \
        --session "$SPA_SESSION_ID" --pid "$SPA_SESSION_PID" >> "$LOG" 2>&1
}
trap release_lock EXIT

# ── ARMED: run one headless GOVERNED-AUTONOMY cycle ─────────────────────────
PROMPT="Ты — оркестратор SPA под НОВЫМ протоколом «управляемая автономия» (owner-approved 2026-07-15). \
Исполни ПОЛНОСТЬЮ docs/ORCHESTRATOR_PROTOCOL.md за один цикл, включая раздел «Автономный рабочий мандат»: \
(1) прочитай docs/STATE.md + docs/decisions/INDEX.md + docs/SYSTEM_BRIEFING.md + свежие data/session_changes.jsonl, \
затем ОБЯЗАТЕЛЬНО python3 scripts/consume_office_reports.py (ADR-066: офис+сторож архитектуры в контекст, \
квитанции потребления; RED/CRITICAL/НЕ-ПРОЧИТАН из вывода => карточка, не молчание); \
(2) разбери Inbox (задача/идея/непонятно) и инжест owner-done (ADR + set-status ingested через \
scripts/orchestrator_queue.py; НИКОГДА не ставь owner-done); (3) если явных заданий нет — возьми ОДНУ \
безопасную задачу сам (hardening/тесты/доки/мелкие НЕ-owner-gated фичи из backlog/roadmap). \
ОБЯЗАТЕЛЬНО: объяви владение файлами (scripts/log_session_change.py) до правок; изолированный worktree; \
ТЕСТЫ ЗЕЛЁНЫЕ до пуша; пуш КОДА через push_to_github.py, а пуш ЛЮБЫХ файлов сайта (landing/**) — ТОЛЬКО \
через scripts/safe_site_push.py (owner-gate ADR-OWN-2026-07: безопасные layout/копирайт/SEO/багфиксы \
уезжают в live сами; числа доходности/нейминг тиров/legal/solicitation линтер САМ заворачивает в карточку). \
ЗАПРЕЩЕНО: трогать RiskPolicy/kill/risk-логику, живой трек data/equity_curve_daily.json, деплой/выгрузку \
агентов, МОЛЧА ослаблять/отключать тесты — всё это ТОЛЬКО карточкой needs-owner + notify, не делать. \
Обнови STATE + journal. Ничего «в воздухе». По завершении — краткий отчёт что сделано/что в карточки."

# Headless: не может отвечать на интерактивные запросы разрешений → bypass (машина владельца,
# гардрейлы в промпте + стоп-правила протокола + инвариант #16). Выключение = снять
# SPA_ORCHESTRATOR_ARMED из plist (launchctl bootout com.spa.orchestrator).
echo "[$(ts)] ARMED: invoking headless Claude (governed autonomy, skip-permissions)" >> "$LOG"
"$CLAUDE_BIN" -p "$PROMPT" --dangerously-skip-permissions >> "$LOG" 2>&1
RC=$?
echo "[$(ts)] === orchestrator cycle END (claude exit $RC) ===" >> "$LOG"
exit $RC
