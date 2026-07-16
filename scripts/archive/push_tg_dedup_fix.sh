#!/bin/bash
# push_tg_dedup_fix.sh — фикс спама Telegram: дедупликация daily/weekly/monthly алертов
# Запуск: bash ~/Documents/SPA_Claude/scripts/push_tg_dedup_fix.sh

set -euo pipefail
cd ~/Documents/SPA_Claude

# ── PAT fallback ────────────────────────────────────────────────────────────
PAT=$(security find-generic-password -s GITHUB_PAT_SPA -w 2>/dev/null || true)
PAT=${PAT:-${GITHUB_PAT_SPA:-${SPA_GITHUB_PAT:-}}}
if [ -z "$PAT" ] && [ -f ~/.github_pat ]; then PAT=$(cat ~/.github_pat); fi
if [ -z "$PAT" ]; then echo "❌ PAT не найден"; exit 1; fi

COMMIT_MSG="fix(alerts): deduplicate Telegram alerts — send daily/weekly/monthly once per day only

Root cause: alert_manager.py had no throttling — send_daily_summary() fired
every 30 min since cycle_runner runs at StartInterval=1800. Added:
- _already_sent_today(key) / _mark_sent_today(key) helpers using
  data/telegram_alert_state.json (atomic write via os.replace)
- Guards in send_daily_summary, send_weekly_report, send_monthly_report
- Tests: 4/4 dedup assertions pass"

python3 scripts/push_to_github.py \
  --pat "$PAT" \
  --repo "yurii-spa/SPA" \
  --branch "main" \
  --message "$COMMIT_MSG" \
  --files \
    "spa_core/alerts/alert_manager.py"

echo "✅ push_tg_dedup_fix готов"
