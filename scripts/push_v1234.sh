#!/bin/bash
# scripts/push_v1234.sh
# Enhanced Telegram reporting — richer daily + weekly reports + milestone alerts.
# Modules (read-only, stdlib, Keychain-backed send via telegram_client):
#   spa_core/reporting/daily_telegram_report.py
#   spa_core/reporting/weekly_telegram_report.py
#   spa_core/reporting/alert_on_milestone.py
#   tests/test_telegram_reports.py  (38 tests, sender mocked — no real Telegram calls)
set -e
cd ~/Documents/SPA_Claude

python3 push_to_github.py \
  --files \
    /Users/yuriikulieshov/Documents/SPA_Claude/spa_core/reporting/daily_telegram_report.py \
    /Users/yuriikulieshov/Documents/SPA_Claude/spa_core/reporting/weekly_telegram_report.py \
    /Users/yuriikulieshov/Documents/SPA_Claude/spa_core/reporting/alert_on_milestone.py \
    /Users/yuriikulieshov/Documents/SPA_Claude/tests/test_telegram_reports.py \
    /Users/yuriikulieshov/Documents/SPA_Claude/scripts/push_v1234.sh \
  --message "feat: enhanced Telegram reporting — daily+weekly reports, milestone alerts, 38 tests"

echo "✅ v1234 pushed"
