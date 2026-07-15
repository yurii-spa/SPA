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

# ── ARMED: run one headless GOVERNED-AUTONOMY cycle ─────────────────────────
PROMPT="Ты — оркестратор SPA под НОВЫМ протоколом «управляемая автономия» (owner-approved 2026-07-15). \
Исполни ПОЛНОСТЬЮ docs/ORCHESTRATOR_PROTOCOL.md за один цикл, включая раздел «Автономный рабочий мандат»: \
(1) прочитай docs/STATE.md + docs/decisions/INDEX.md + docs/SYSTEM_BRIEFING.md + свежие data/session_changes.jsonl; \
(2) разбери Inbox (задача/идея/непонятно) и инжест owner-done (ADR + set-status ingested через \
scripts/orchestrator_queue.py; НИКОГДА не ставь owner-done); (3) если явных заданий нет — возьми ОДНУ \
безопасную задачу сам (hardening/тесты/доки/мелкие НЕ-owner-gated фичи из backlog/roadmap). \
ОБЯЗАТЕЛЬНО: объяви владение файлами (scripts/log_session_change.py) до правок; изолированный worktree; \
ТЕСТЫ ЗЕЛЁНЫЕ до пуша; пуш через push_to_github.py. ЗАПРЕЩЕНО: трогать RiskPolicy/kill/risk-логику, живой \
трек data/equity_curve_daily.json, деплой/выгрузку агентов, числа/нейминг/legal на сайте, МОЛЧА ослаблять/ \
отключать тесты — всё это ТОЛЬКО карточкой needs-owner + notify, не делать. Обнови STATE + journal. \
Ничего «в воздухе». По завершении — краткий отчёт что сделано/что в карточки."

# Headless: не может отвечать на интерактивные запросы разрешений → bypass (машина владельца,
# гардрейлы в промпте + стоп-правила протокола + инвариант #16). Выключение = снять
# SPA_ORCHESTRATOR_ARMED из plist (launchctl bootout com.spa.orchestrator).
echo "[$(ts)] ARMED: invoking headless Claude (governed autonomy, skip-permissions)" >> "$LOG"
"$CLAUDE_BIN" -p "$PROMPT" --dangerously-skip-permissions >> "$LOG" 2>&1
RC=$?
echo "[$(ts)] === orchestrator cycle END (claude exit $RC) ===" >> "$LOG"
exit $RC
