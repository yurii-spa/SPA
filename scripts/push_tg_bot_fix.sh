#!/usr/bin/env bash
# push_tg_bot_fix.sh — push Telegram bot fixes to GitHub
#
# Fixes:
#   Bug 1: "Подробнее" button showed command list instead of event details
#           → added _cmd_detail() handler + detail_* routing in _dispatch()
#           → spa_core/telegram/bot.py
#
#   Bug 2: Daily Report showed N/A for equity/P&L/APY
#           → added fallbacks to paper_trading_status.json + equity_curve_daily.json
#           → made sentinel_status.json optional (missing → alert_class "OK")
#           → spa_core/agents/reporting_agent.py
#
# PAT resolution order:
#   1. macOS Keychain: security find-generic-password -s GITHUB_PAT_SPA
#   2. Environment: GITHUB_PAT_SPA, SPA_GITHUB_PAT
#   3. ~/.github_pat file
#
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

# ── PAT resolution ────────────────────────────────────────────────────────────
PAT=$(security find-generic-password -s GITHUB_PAT_SPA -w 2>/dev/null || true)
PAT=${PAT:-${GITHUB_PAT_SPA:-${SPA_GITHUB_PAT:-}}}
if [ -z "$PAT" ] && [ -f ~/.github_pat ]; then PAT=$(cat ~/.github_pat); fi

if [ -z "$PAT" ]; then
  echo "ERROR: GitHub PAT not found." >&2
  echo "Set it with: bash setup_pat.sh  (or add to ~/.github_pat)" >&2
  exit 1
fi

# ── Files to push ─────────────────────────────────────────────────────────────
FILES=(
  "${REPO_ROOT}/spa_core/telegram/bot.py"
  "${REPO_ROOT}/spa_core/agents/reporting_agent.py"
)

COMMIT_MSG="fix(telegram): route detail_* callbacks; fix daily report N/A fields

Bug 1 (bot.py):
  'Подробнее' inline button sent callback_data='detail_{proto}__{cat}'.
  _dispatch() had no handler for detail_* → fell through to cmd_help()
  and showed the command list instead of event details.
  Fix: detect detail_ prefix in _dispatch(), call new _cmd_detail() method
  which reads red_flags.json, finds the matching alert, and formats a
  full Russian-language detail message via format_alert_detail_ru().

Bug 2 (reporting_agent.py — collect_pnl_data):
  portfolio_track.json MISSING → equity_today/P&L all None → 'N/A'.
  analytics_summary.json exists but avg_apy_7d key absent → apy 'N/A'.
  sentinel_status.json MISSING → data_complete=False → 'Incomplete data'.
  Fixes:
    a) Fallback equity from paper_trading_status.json + equity_curve_daily.json
    b) Fallback avg_apy_7d: compute from last 7 bars of equity_curve_daily.json
       (apy_today field); last resort: apy_today_pct from paper_trading_status.json
    c) sentinel_status.json is now optional (missing → alert_class='OK',
       does NOT set data_complete=False)"

# ── Push ──────────────────────────────────────────────────────────────────────
echo "Pushing ${#FILES[@]} files..."
for f in "${FILES[@]}"; do
  echo "  $f"
done

GITHUB_PAT_SPA="$PAT" python3 "${REPO_ROOT}/push_to_github.py" \
  --files "${FILES[@]}" \
  --message "$COMMIT_MSG"

echo "Done."
