#!/bin/bash
# push_all_today.sh — пушит все изменения за сегодня (2026-06-14)
# Баг-фиксы + дизайн дашборда + plists агентов + install script

set -e
COMMIT_MSG="feat: agent topology L1/L2, dashboard Nansen redesign, cycle bugfixes (2026-06-14)"

PAT=$(security find-generic-password -s GITHUB_PAT_SPA -w 2>/dev/null || echo "")
[ -z "$PAT" ] && PAT="${GITHUB_PAT_SPA:-${SPA_GITHUB_PAT:-}}"
[ -z "$PAT" ] && [ -f ~/.github_pat ] && PAT=$(cat ~/.github_pat)
[ -z "$PAT" ] && { echo "❌ PAT не найден"; exit 1; }

cd "$(dirname "$0")/.." || exit 1

python3 push_to_github.py \
  --message "$COMMIT_MSG" \
  --pat "$PAT" \
  --files \
    index.html \
    spa_core/paper_trading/cycle_runner.py \
    spa_core/analytics/analytics_pipeline.py \
    scripts/install_agents.sh \
    scripts/com.spa.daily_cycle.plist \
    scripts/com.spa.httpserver.plist \
    scripts/com.spa.cloudflared.plist \
    scripts/com.spa.uptime_monitor.plist \
    scripts/com.spa.cycle_health.plist \
    scripts/com.spa.cycle_gap_monitor.plist \
    scripts/com.spa.portfolio_monitor.plist \
    scripts/com.spa.peg_monitor.plist \
    scripts/com.spa.red_flag_monitor.plist \
    scripts/com.spa.governance_watcher.plist \
    scripts/com.spa.base_gas_monitor.plist \
    scripts/com.spa.sky_monitor.plist \
    scripts/com.spa.autopush.plist

echo "✅ Всё запушено"
