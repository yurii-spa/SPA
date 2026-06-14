#!/bin/bash
# SPA Push Script — v6.59 Telegram /protocols reporter (MP-659)
# Pushes: telegram_protocols_reporter.py, its tests, and KANBAN.json
#
# PAT fallback chain:
#   1. $GITHUB_PAT_SPA env var
#   2. $GITHUB_PAT env var
#   3. macOS Keychain (GITHUB_PAT_SPA)
#
# SECRETS POLICY: No tokens or credentials are embedded in this file.

set -e
cd ~/Documents/SPA_Claude

echo "🚀 SPA Push v6.59 — /protocols Telegram reporter..."

python3 push_to_github.py \
  --files \
  /Users/yuriikulieshov/Documents/SPA_Claude/spa_core/telegram_protocols_reporter.py \
  /Users/yuriikulieshov/Documents/SPA_Claude/spa_core/tests/test_telegram_protocols_reporter.py \
  /Users/yuriikulieshov/Documents/SPA_Claude/scripts/push_v659_telegram.sh \
  /Users/yuriikulieshov/Documents/SPA_Claude/KANBAN.json \
  --message "feat(v6.59/MP-659): /protocols Telegram command — rich per-protocol status report (81 tests)"

echo "✅ Push v6.59 complete."
