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

# ── ARMED: run one headless orchestrator cycle ──────────────────────────────
PROMPT="Ты — оркестратор SPA. Исполни ПОЛНОСТЬЮ протокол в docs/ORCHESTRATOR_PROTOCOL.md \
за один цикл: прочитай docs/STATE.md + docs/decisions/INDEX.md + docs/SYSTEM_BRIEFING.md; \
разбери Inbox (классификация задача/идея/непонятно); инжест owner-done решений (ADR + перевод \
карточек в ingested через scripts/orchestrator_queue.py, НИКОГДА не ставь owner-done); обнови \
docs/STATE.md и docs/journal/<ISO-неделя>.md; новые вопросы владельцу — только карточкой \
needs-owner + notify. Соблюдай инварианты CLAUDE.md. По завершении выведи краткий отчёт."

# Permission mode is chosen with the owner at activation (Stage 8). Default here
# is the conservative acceptEdits; bash calls to orchestrator_queue.py may need a
# broader mode or a settings allowlist — finalize at Stage 8.
PERM_MODE="${SPA_ORCHESTRATOR_PERM_MODE:-acceptEdits}"

echo "[$(ts)] ARMED: invoking headless Claude (perm-mode=$PERM_MODE)" >> "$LOG"
"$CLAUDE_BIN" -p "$PROMPT" --permission-mode "$PERM_MODE" >> "$LOG" 2>&1
RC=$?
echo "[$(ts)] === orchestrator cycle END (claude exit $RC) ===" >> "$LOG"
exit $RC
