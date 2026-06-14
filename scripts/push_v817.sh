#!/bin/bash
# SPA Push v8.17
# MP-1152: DeFiProtocolPerformanceFeeHighWaterMarkAnalyzer            (145 tests)
# MP-1153: DeFiProtocolPerformanceFeeCrystallizationFrequencyAnalyzer (135 tests)
#
# SECURITY: PAT is read from macOS Keychain (service: GITHUB_PAT_SPA).
# DO NOT embed PAT or any credentials in this file.
#
# Usage: bash ~/Documents/SPA_Claude/scripts/push_v817.sh

set -e

COMMIT_MSG="feat(v8.17): MP-1152 PerformanceFeeHighWaterMarkAnalyzer + MP-1153 PerformanceFeeCrystallizationFrequencyAnalyzer | 145+135=280 tests | advisory/read-only vault_fee_mechanics | HWM underwater perf-fee shielding (underwater_pct, recovery_to_hwm, gross_above_hwm, mgmt/perf fee drag with vs no HWM, hwm_savings, net_apy, fee_efficiency score; LOW/MODERATE/HIGH/EXCESSIVE_FEE_DRAG) + crystallization frequency compounding-loss (crystallization_label, compounding_loss, effective_perf_fee_drag, pay_for_volatility_risk, net_apy, frequency_efficiency score; INVESTOR_FRIENDLY/NEUTRAL/INVESTOR_UNFRIENDLY/PREDATORY) | closes gap high_water_mark/hwm/crystallization=0 | registry Tier-B +2 (vault_fee_mechanics) | pure stdlib, atomic ring-buffer logs"

FILES="/Users/yuriikulieshov/Documents/SPA_Claude/spa_core/analytics/defi_protocol_performance_fee_high_water_mark_analyzer.py
/Users/yuriikulieshov/Documents/SPA_Claude/spa_core/analytics/defi_protocol_performance_fee_crystallization_frequency_analyzer.py
/Users/yuriikulieshov/Documents/SPA_Claude/spa_core/tests/test_defi_protocol_performance_fee_high_water_mark_analyzer.py
/Users/yuriikulieshov/Documents/SPA_Claude/spa_core/tests/test_defi_protocol_performance_fee_crystallization_frequency_analyzer.py
/Users/yuriikulieshov/Documents/SPA_Claude/spa_core/analytics/_module_registry.py
/Users/yuriikulieshov/Documents/SPA_Claude/KANBAN.json
/Users/yuriikulieshov/Documents/SPA_Claude/sprint_log.md
/Users/yuriikulieshov/Documents/SPA_Claude/scripts/push_v817.sh"

# PAT resolution: Keychain → env GITHUB_PAT_SPA → env SPA_GITHUB_PAT → ~/.github_pat
PAT=$(security find-generic-password -s GITHUB_PAT_SPA -w 2>/dev/null || echo "")
[ -z "$PAT" ] && PAT="${GITHUB_PAT_SPA:-${SPA_GITHUB_PAT:-}}"
[ -z "$PAT" ] && [ -f ~/.github_pat ] && PAT=$(cat ~/.github_pat)
[ -z "$PAT" ] && { echo "PAT not found — run: bash setup_pat.sh"; exit 1; }

cd ~/Documents/SPA_Claude
echo "SPA Push v8.17 — MP-1152 + MP-1153 + tests + registry + KANBAN + sprint_log"
python3 push_to_github.py --files $FILES --message "$COMMIT_MSG" --pat "$PAT"
echo "Push v8.17 complete!"
