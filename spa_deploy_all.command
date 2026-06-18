#!/usr/bin/env bash
# spa_deploy_all.command — Deploy all pending changes to GitHub
# Covers: Landing page + Telegram fixes + GoLive gate + autopush installer
# Double-click in Finder to run

set -e
cd "$(dirname "$0")"

echo "╔══════════════════════════════════════════════════════════════╗"
echo "║  SPA: Deploy All Pending Changes to GitHub                   ║"
echo "╚══════════════════════════════════════════════════════════════╝"
echo ""
echo "$(date '+%Y-%m-%d %H:%M:%S')"
echo ""

# 1. Load PAT
PAT=$(security find-generic-password -s 'GITHUB_PAT_SPA' -w 2>/dev/null)
if [ -z "$PAT" ]; then
  echo "ERROR: GITHUB_PAT_SPA not found in Keychain"; exit 1
fi
echo "✅ PAT loaded (${#PAT} chars)"

# 2. Stage all changed files (specific list, no AUTOPUSH_REPORT junk)
echo ""
echo "▶ Staging files..."
git add \
  landing/ \
  KANBAN.json \
  scripts/com.spa.daily_cycle.plist \
  scripts/golive_preflight.py \
  scripts/run_health_check.py \
  spa_core/alerts/alert_dispatcher.py \
  spa_core/alerts/alert_manager.py \
  spa_core/alerts/telegram_manager.py \
  spa_core/monitoring/peg_monitor.py \
  spa_core/paper_trading/golive_checker.py \
  spa_core/tests/test_golive_checker.py \
  tests/test_telegram_manager.py \
  install_autopush.command \
  2>/dev/null || true

git status --short | grep -v "^?" | head -30
echo ""

# 3. Commit (skip if nothing new)
echo "▶ Committing..."
git diff --cached --quiet && echo "Nothing new to commit, continuing with push..." || \
  git commit -m "fix: Telegram spam + GoLive 23/26 gate + landing page (2026-06-18)

Telegram Bot Audit (3 bugs fixed):
- com.spa.daily_cycle.plist: StartInterval 1800 → StartCalendarInterval Hour=8
- alert_manager.py: added _already_sent_today guard to send_red_flag + send_gap_alert
- alert_dispatcher.py: dedup state persisted to disk (survives process restarts)
- peg_monitor.py: cooldown_seconds=3600
- run_health_check.py: wrapped with TelegramManager (1h cooldown)
- telegram_manager.py: NEW central cooldown manager, 16 tests passing

GoLive Preflight Gate v5.0 (23/26 passing):
- golive_checker.py: expanded 6 → 26 criteria across 8 groups
- test_golive_checker.py: 24 tests, all pass
- install_autopush.command: one-click launchd autopush installer

Landing Page (Astro 4 → earn-defi.com):
- 19 files: Astro 4 + Tailwind CSS + React islands
- Hero, LiveStats, CompetitorTable, FeeStructure, Disclaimer"

echo "✅ Commit: $(git log --oneline -1)"
echo ""

# 4. Push
echo "▶ Pushing to GitHub..."
REMOTE="https://${PAT}@github.com/yurii-spa/SPA.git"
git push "$REMOTE" main
echo "✅ Pushed!"
echo ""

# 5. Reload Telegram launchd agent
echo "▶ Reloading Telegram launchd agent..."
PLIST=~/Library/LaunchAgents/com.spa.daily_cycle.plist
if [ -f "$PLIST" ]; then
  launchctl unload "$PLIST" 2>/dev/null || true
fi
cp scripts/com.spa.daily_cycle.plist ~/Library/LaunchAgents/com.spa.daily_cycle.plist
launchctl load ~/Library/LaunchAgents/com.spa.daily_cycle.plist
echo "✅ Telegram agent reloaded → runs at 08:00 daily (no more 30-min spam)"
echo ""

echo "════════════════════════════════════════════════════════════"
echo "✅ ALL DONE"
echo "  - Landing page pushed → Cloudflare will rebuild earn-defi.com"
echo "  - Telegram spam fixed → daily 08:00 only"
echo "  - GoLive gate 23/26 pushed"
echo "════════════════════════════════════════════════════════════"
echo ""
read -n 1 -s -r -p "Press any key to close..."
