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

# ── ANTI-DRIFT: registry truth lives in origin/main, not in the working copy ──
# Incident 2026-07-29: the 20.07 `freeze-main-phase0` ruleset stranded R&D in PRs, so the
# working copy's registry lagged main by 7 ideas. Two sessions then picked the SAME free
# number (#21) and one re-tested an idea already answered in a stranded PR (ALK, PR #8 →
# closed without merge, folded into #27). Fix: fetch origin (read-only — never touch the
# shared working tree, other sessions write here) and hand the session the next free idea
# number computed from origin/main. Fail-OPEN with an explicit UNKNOWN marker: the prompt
# then orders the session to derive the number itself from origin/main before writing.
git fetch origin main --quiet >> "$LOG" 2>&1 \
    || echo "[$(ts)] WARN: git fetch origin main failed — number may be stale" >> "$LOG"

LAST_IDEA="$(git show origin/main:docs/DYNAMIC_LEVERAGE_GUARDIAN.md 2>/dev/null \
    | grep -oE '^(- \*\*#|### Идея #)[0-9]+' | grep -oE '[0-9]+' | sort -n | tail -1)"
if [ -n "$LAST_IDEA" ]; then
    NEXT_IDEA="$((LAST_IDEA + 1))"
else
    NEXT_IDEA="UNKNOWN"
fi
echo "[$(ts)] registry on origin/main ends at #${LAST_IDEA:-?} → next free idea number: #$NEXT_IDEA" >> "$LOG"

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
краткий отчёт: какие гипотезы, вердикты, что запушено, что отвергнуто и почему. \
ВАЖНО (анти-дрейф, инцидент 29.07): реестр читать ИЗ ORIGIN, а не из рабочей копии — она отстаёт, \
пока другие сессии пушат: \`git show origin/main:docs/DYNAMIC_LEVERAGE_GUARDIAN.md\`. Следующий \
СВОБОДНЫЙ номер идеи = #$NEXT_IDEA (вычислен из origin/main перед стартом; если тут UNKNOWN — \
вычисли сам тем же способом). Прежде чем тестировать гипотезу, проверь по ORIGIN-реестру, что она \
там ещё не отвечена. Пушить НАПРЯМУЮ в main (bypass admin включён владельцем 29.07) — PR не \
создавать; если пуш вернул HTTP 422 'must be made through a pull request', значит правило вернули: \
НЕ обходить его ветками молча, а завести карточку владельцу и сообщить в отчёте."

echo "[$(ts)] ARMED: invoking headless Claude (novel-edge R&D, skip-permissions)" >> "$LOG"
"$CLAUDE_BIN" -p "$PROMPT" --dangerously-skip-permissions >> "$LOG" 2>&1
RC=$?
echo "[$(ts)] === iteration END (claude exit $RC) ===" >> "$LOG"
exit $RC
