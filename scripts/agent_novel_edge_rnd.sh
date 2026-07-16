#!/bin/bash
# ============================================================================
# scripts/agent_novel_edge_rnd.sh — headless R&D "opportunity finder" agent.
# ============================================================================
# Owner-requested 2026-07-16: the agent that PERIODICALLY searches for new edge
# opportunities. Runs the standing R&D directive
#   ~/.claude/scheduled-tasks/novel-edge-rnd/SKILL.md
# TWICE A WEEK (Tue+Fri, via the plist StartCalendarInterval). Each iteration:
# invents 1-2 NEW edge hypotheses → HONEST backtest on real history → logs the
# verdict (positive OR negative) to docs/DYNAMIC_LEVERAGE_GUARDIAN.md → builds a
# paper module only if it holds out-of-sample. All advisory / paper / OUTSIDE
# RiskPolicy; deploy of any NEW agent stays owner-gated (card), per the SKILL.
#
# WHY the previous engine went quiet: R&D findings were driven by the roadmap-loop
# (session 1345fef8) which the owner STOPPED 2026-07-15 — there was no dedicated
# scheduler. THIS agent is that dedicated, owner-visible scheduler.
#
# SAFETY: arming gate (SPA_RND_ARMED=1) — inert otherwise (logs + exit 0, no Claude).
# bash-wrapper (launchd can't exec miniconda-python → exit 78). Logs in /tmp (never
# ~/Documents → TCC exit-78). Governance lives in the SKILL (НОВЫЙ ПРОТОКОЛ block).
# ============================================================================
set -uo pipefail

REPO_ROOT="/Users/yuriikulieshov/Documents/SPA_Claude"
CLAUDE_BIN="${CLAUDE_BIN:-/Users/yuriikulieshov/.local/bin/claude}"
LOG="/tmp/spa_novel_edge_rnd.log"

export PATH="/Users/yuriikulieshov/.local/bin:/opt/homebrew/bin:/Users/yuriikulieshov/miniconda3/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin:${PATH:-}"
export HOME="/Users/yuriikulieshov"

cd "$REPO_ROOT" || exit 1
ts() { date "+%Y-%m-%d %H:%M:%S %Z"; }
echo "[$(ts)] === novel-edge R&D iteration START ===" >> "$LOG"

# bound the log
if [ -f "$LOG" ] && [ "$(wc -l < "$LOG" 2>/dev/null || echo 0)" -gt 800 ]; then
    tail -400 "$LOG" > "$LOG.tmp" && mv "$LOG.tmp" "$LOG"
fi

# ── ARMING GATE ─────────────────────────────────────────────────────────────
if [ "${SPA_RND_ARMED:-0}" != "1" ]; then
    echo "[$(ts)] INERT: SPA_RND_ARMED != 1 — not invoking Claude." >> "$LOG"
    echo "[$(ts)] === iteration END (inert, exit 0) ===" >> "$LOG"
    exit 0
fi

# ── ARMED: run one headless R&D iteration per the standing SKILL directive ───
PROMPT="Исполни ОДНУ автономную R&D-итерацию SPA строго по директиве \
~/.claude/scheduled-tasks/novel-edge-rnd/SKILL.md — прочитай её ПЕРВОЙ и следуй ей полностью, \
включая «🔴 НОВЫЙ ПРОТОКОЛ» и ЖЕЛЕЗНЫЕ ИНВАРИАНТЫ. Кратко: (1) прочитай docs/STATE.md + \
docs/decisions/INDEX.md + docs/SYSTEM_BRIEFING.md + реестр docs/DYNAMIC_LEVERAGE_GUARDIAN.md \
(НЕ повторяй уже протестированные идеи) + свежие data/swarm/*.json; (2) объяви владение файлами \
через scripts/log_session_change.py; (3) придумай 1-2 НОВЫЕ edge-гипотезы «доход выше, риск ниже», \
ЧЕСТНО забэктести на реальной истории (переиспользуй существующие harness'ы), запиши вердикт \
(позитив И негатив) в реестр; (4) при устойчивом out-of-sample позитиве — paper-модуль (advisory, \
fail-closed, hash-chain, тесты) и КАРТОЧКА владельцу на деплой нового агента (НЕ деплой молча). \
Всё advisory/paper/OUTSIDE_RISKPOLICY: go-live трек и RiskPolicy v1.0 НЕ трогать, живой cycle_runner \
против data/ НЕ запускать. Тесты зелёные до пуша; пуш через push_to_github_batch.py. По завершении — \
краткий отчёт: какие гипотезы, вердикты, что запушено, что отвергнуто и почему."

echo "[$(ts)] ARMED: invoking headless Claude (novel-edge R&D, skip-permissions)" >> "$LOG"
"$CLAUDE_BIN" -p "$PROMPT" --dangerously-skip-permissions >> "$LOG" 2>&1
RC=$?
echo "[$(ts)] === iteration END (claude exit $RC) ===" >> "$LOG"
exit $RC
