#!/bin/bash
# push_agent_fixes.sh — фикс агентов: cycle_gap_monitor, bot /agents, alert dedup, sky_status
# Запуск: bash ~/Documents/SPA_Claude/scripts/push_agent_fixes.sh

set -euo pipefail
cd ~/Documents/SPA_Claude

# ── PAT fallback ─────────────────────────────────────────────────────────────
PAT=$(security find-generic-password -s GITHUB_PAT_SPA -w 2>/dev/null || true)
PAT=${PAT:-${GITHUB_PAT_SPA:-${SPA_GITHUB_PAT:-}}}
if [ -z "$PAT" ] && [ -f ~/.github_pat ]; then PAT=$(cat ~/.github_pat); fi
if [ -z "$PAT" ]; then echo "❌ PAT не найден"; exit 1; fi

echo "── 1/2: Пуш фиксов агентов ──"
python3 scripts/push_to_github.py \
  --pat "$PAT" \
  --repo "yurii-spa/SPA" \
  --branch "main" \
  --message "fix(agents): 3 agent fixes — cycle_gap_monitor, bot /agents icons, telegram dedup

1. cycle_gap_monitor plist: remove --check (dry-run) so it writes
   data/cycle_gap_state.json every 5 min → uptime shows ✅ not ❌

2. telegram/bot.py /agents: add ⏸ icon for scheduled agents
   (checkpoint-7day, weekly_backup, fund-api, sky_monitor etc.)
   that run on schedule and exit — idle is normal, not a crash

3. alerts/alert_manager.py: daily/weekly/monthly Telegram dedup
   via data/telegram_alert_state.json — send once per day only

4. sky_status.json: refreshed timestamp (was 7 days stale)" \
  --files \
    "scripts/com.spa.cycle_gap_monitor.plist" \
    "spa_core/telegram/bot.py" \
    "spa_core/alerts/alert_manager.py" \
    "data/sky_status.json"

echo ""
echo "── 2/2: Перезагрузка агентов на Mac ──"
echo "Выполни дополнительно:"
echo "  cp ~/Documents/SPA_Claude/scripts/com.spa.cycle_gap_monitor.plist ~/Library/LaunchAgents/"
echo "  launchctl unload ~/Library/LaunchAgents/com.spa.cycle_gap_monitor.plist 2>/dev/null || true"
echo "  launchctl load ~/Library/LaunchAgents/com.spa.cycle_gap_monitor.plist"
echo "  cp ~/Documents/SPA_Claude/scripts/com.spa.cycle_health.plist ~/Library/LaunchAgents/"
echo "  launchctl unload ~/Library/LaunchAgents/com.spa.cycle_health.plist 2>/dev/null || true"
echo "  launchctl load ~/Library/LaunchAgents/com.spa.cycle_health.plist"

echo ""
echo "✅ push_agent_fixes готов"
