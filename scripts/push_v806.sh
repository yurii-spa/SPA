#!/bin/bash
# SPA Sprint v8.06 Push
# Дата: 2026-06-14
# Запускать: bash ~/Documents/SPA_Claude/scripts/push_v806.sh
#
# Пушит все файлы спринта v8.06 (MP-1136, MP-1137).
# PAT читается из macOS Keychain (GITHUB_PAT_SPA).

set -e
cd ~/Documents/SPA_Claude

PAT=$(security find-generic-password -s GITHUB_PAT_SPA -w)

echo "🚀 SPA Sprint v8.06 Push — MP-1136, MP-1137..."

python3 push_to_github.py \
  --pat "$PAT" \
  --files \
  /Users/yuriikulieshov/Documents/SPA_Claude/KANBAN.json \
  /Users/yuriikulieshov/Documents/SPA_Claude/spa_core/analytics/defi_protocol_withdrawal_queue_risk_analyzer.py \
  /Users/yuriikulieshov/Documents/SPA_Claude/spa_core/analytics/protocol_defi_protocol_concentration_risk_analyzer.py \
  /Users/yuriikulieshov/Documents/SPA_Claude/spa_core/tests/test_defi_protocol_withdrawal_queue_risk_analyzer.py \
  /Users/yuriikulieshov/Documents/SPA_Claude/spa_core/tests/test_protocol_defi_protocol_concentration_risk_analyzer.py \
  /Users/yuriikulieshov/Documents/SPA_Claude/scripts/push_v806.sh \
  --message "feat(v8.06): MP-1136 DeFiProtocolWithdrawalQueueRiskAnalyzer + MP-1137 ProtocolDeFiProtocolConcentrationRiskAnalyzer — 2 analytics modules, 220+ tests"

echo "✅ Push v8.06 complete."
