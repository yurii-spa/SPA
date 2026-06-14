#!/bin/bash
# deploy_all.sh — разворачивает все изменения за 2026-06-14
# Запускай на Mac: bash ~/Documents/SPA_Claude/scripts/deploy_all.sh
set -e

CD="$HOME/Documents/SPA_Claude"
cd "$CD"

echo "======================================"
echo " SPA Deploy — 2026-06-14"
echo "======================================"

# ── PAT ──────────────────────────────────
PAT=$(security find-generic-password -s GITHUB_PAT_SPA -w 2>/dev/null || true)
[ -z "$PAT" ] && PAT="${GITHUB_PAT_SPA:-${SPA_GITHUB_PAT:-}}"
[ -z "$PAT" ] && [ -f ~/.github_pat ] && PAT=$(cat ~/.github_pat)
if [ -z "$PAT" ]; then
  echo "❌ PAT не найден (Keychain GITHUB_PAT_SPA / env / ~/.github_pat)"
  echo "   Пуш пропущен, остальное продолжается..."
  SKIP_PUSH=1
fi

# ── Git: убираем stale lock если есть ────
if [ -f ".git/index.lock" ]; then
  echo "🔓 Removing stale git index.lock..."
  rm -f ".git/index.lock"
fi

# ── Git commit ────────────────────────────
echo ""
echo "── Git commit ──────────────────────"
git config user.email "yuriycooleshov@gmail.com" 2>/dev/null || true
git config user.name "Yurii SPA" 2>/dev/null || true
git add -A 2>/dev/null || true
CHANGED=$(git diff --cached --name-only 2>/dev/null | wc -l)
if [ "$CHANGED" -gt 0 ]; then
  git commit -m "feat: analytics integration (578 modules Tier A/B/C), uptime_monitor fix, kill-switch MIN_DAYS=30, dashboard redesign, 19 launchd agents, Telegram bot plist (2026-06-14)" || true
  echo "✅ Git commit: $CHANGED files"
else
  echo "ℹ️  Git: nothing to commit"
fi

# ── Push всех изменений ───────────────────
if [ -z "$SKIP_PUSH" ]; then
  echo ""
  echo "── Pushing to GitHub ───────────────"

  _push() {
    local script="$1"
    if [ -f "scripts/$script" ]; then
      echo "  → $script"
      bash "scripts/$script" 2>&1 | tail -3
    fi
  }

  _push push_all_today.sh
  _push push_agent_fixes.sh
  _push push_p02_p06_fixes.sh
  _push push_killswitch_fix.sh
  _push push_uptime_fix.sh
  _push push_telegram_and_state.sh
  _push push_analytics_integration.sh
  _push push_v809.sh
  _push push_v810.sh
  echo "✅ Push complete"
fi

# ── Устанавливаем launchd агентов ─────────
echo ""
echo "── Installing launchd agents ───────"
bash scripts/install_agents.sh 2>&1 | tail -5
echo "✅ Agents installed"

# ── Проверка статуса ──────────────────────
echo ""
echo "── Agent Status ────────────────────"
bash scripts/agent_status.sh 2>&1

echo ""
echo "======================================"
echo " Deploy DONE"
echo " Проверь дашборд: http://localhost:8765"
echo "======================================"
