#!/bin/bash
# SPA Push v8.15
# MP-1148: DeFiProtocolStablecoinParRedemptionCapacityAnalyzer  (73 tests)
# MP-1149: DeFiProtocolEmergencyWithdrawalPauseRiskAnalyzer      (74 tests)
#
# SECURITY: PAT is read from macOS Keychain (service: GITHUB_PAT_SPA).
# DO NOT embed PAT or any credentials in this file.
#
# Usage: bash ~/Documents/SPA_Claude/scripts/push_v815.sh

set -e

COMMIT_MSG="feat(v8.15): MP-1148 StablecoinParRedemptionCapacityAnalyzer + MP-1149 EmergencyWithdrawalPauseRiskAnalyzer | 73+74=147 tests | advisory/read-only exit-side risk | par-redemption capacity (days-to-par-exit, backing coverage, daily-cap utilization, net-par proceeds, PRIMARY/SECONDARY/SPLIT/TRAPPED route, capacity score) + emergency withdrawal-pause/fund-trapping risk (controller centralization EOA..DAO/m-of-n, worst-case lockup days, expected trapped days/yr, pausable exposure, opportunity cost, trap/safety score) | registry Tier-B +2 (exit_liquidity) | pure stdlib, atomic ring-buffer logs"

FILES="/Users/yuriikulieshov/Documents/SPA_Claude/spa_core/analytics/defi_protocol_stablecoin_par_redemption_capacity_analyzer.py
/Users/yuriikulieshov/Documents/SPA_Claude/spa_core/analytics/defi_protocol_emergency_withdrawal_pause_risk_analyzer.py
/Users/yuriikulieshov/Documents/SPA_Claude/spa_core/tests/test_defi_protocol_stablecoin_par_redemption_capacity_analyzer.py
/Users/yuriikulieshov/Documents/SPA_Claude/spa_core/tests/test_defi_protocol_emergency_withdrawal_pause_risk_analyzer.py
/Users/yuriikulieshov/Documents/SPA_Claude/spa_core/analytics/_module_registry.py
/Users/yuriikulieshov/Documents/SPA_Claude/KANBAN.json
/Users/yuriikulieshov/Documents/SPA_Claude/sprint_log.md
/Users/yuriikulieshov/Documents/SPA_Claude/scripts/push_v815.sh"

# PAT resolution: Keychain → env GITHUB_PAT_SPA → env SPA_GITHUB_PAT → ~/.github_pat
PAT=$(security find-generic-password -s GITHUB_PAT_SPA -w 2>/dev/null || echo "")
[ -z "$PAT" ] && PAT="${GITHUB_PAT_SPA:-${SPA_GITHUB_PAT:-}}"
[ -z "$PAT" ] && [ -f ~/.github_pat ] && PAT=$(cat ~/.github_pat)
[ -z "$PAT" ] && { echo "PAT not found — run: bash setup_pat.sh"; exit 1; }

cd ~/Documents/SPA_Claude
echo "SPA Push v8.15 — MP-1148 + MP-1149 + tests + registry + KANBAN + sprint_log"
python3 push_to_github.py --files $FILES --message "$COMMIT_MSG" --pat "$PAT"
echo "Push v8.15 complete!"
