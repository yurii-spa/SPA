#!/bin/bash
# SPA Push v8.24
# MP-1166: DeFiProtocolVaultCapacityDilutionAnalyzer  (168 tests)
# MP-1167: DeFiProtocolVaultHarvestTimingAnalyzer      (164 tests)
#
# SECURITY: PAT is read from macOS Keychain (service: GITHUB_PAT_SPA).
# DO NOT embed PAT or any credentials in this file.
#
# Usage: bash ~/Documents/SPA_Claude/scripts/push_v824.sh

set -e

COMMIT_MSG="feat(v8.24): MP-1166 VaultCapacityDilutionAnalyzer + MP-1167 VaultHarvestTimingAnalyzer | 168+164=332 tests | advisory/read-only | finite strategy alpha capacity: as TVL grows past optimal_capacity, marginal capital dilutes per-share yield + your own deposit tips TVL over the threshold (post_deposit_tvl_usd, over_capacity_usd, utilization_pct, effective_apr_pct=headline*(capacity/post_tvl)**decay_exp, dilution_pct, headroom_usd; AMPLE_HEADROOM/APPROACHING_CAPACITY/OVER_CAPACITY/SEVERELY_DILUTED; higher score=more headroom) [category yield_quality] + harvest timing of pending vault rewards vs fixed harvest gas: harvest now or wait, optimal interval, gas drag (gas_to_reward_ratio, reward_to_gas_ratio, harvest_worthwhile_now, optimal_harvest_pending_usd, days_to_optimal, optimal_interval_days, net_if_harvest_now_usd, gas_drag_pct, overdue; HARVEST_NOW/APPROACHING_OPTIMAL/TOO_EARLY/GAS_EXCEEDS_REWARD; higher score=closer to optimum/less gas drag) [category cost_efficiency] | registry Tier-B +2 (B=416) | pure stdlib, atomic ring-buffer logs"

FILES="/Users/yuriikulieshov/Documents/SPA_Claude/spa_core/analytics/defi_protocol_vault_capacity_dilution_analyzer.py
/Users/yuriikulieshov/Documents/SPA_Claude/spa_core/analytics/defi_protocol_vault_harvest_timing_analyzer.py
/Users/yuriikulieshov/Documents/SPA_Claude/spa_core/tests/test_defi_protocol_vault_capacity_dilution_analyzer.py
/Users/yuriikulieshov/Documents/SPA_Claude/spa_core/tests/test_defi_protocol_vault_harvest_timing_analyzer.py
/Users/yuriikulieshov/Documents/SPA_Claude/data/vault_capacity_dilution_log.json
/Users/yuriikulieshov/Documents/SPA_Claude/data/vault_harvest_timing_log.json
/Users/yuriikulieshov/Documents/SPA_Claude/spa_core/analytics/_module_registry.py
/Users/yuriikulieshov/Documents/SPA_Claude/KANBAN.json
/Users/yuriikulieshov/Documents/SPA_Claude/sprint_log.md
/Users/yuriikulieshov/Documents/SPA_Claude/scripts/push_v824.sh"

# PAT resolution: Keychain → env GITHUB_PAT_SPA → env SPA_GITHUB_PAT → ~/.github_pat
PAT=$(security find-generic-password -s GITHUB_PAT_SPA -w 2>/dev/null || echo "")
[ -z "$PAT" ] && PAT="${GITHUB_PAT_SPA:-${SPA_GITHUB_PAT:-}}"
[ -z "$PAT" ] && [ -f ~/.github_pat ] && PAT=$(cat ~/.github_pat)
[ -z "$PAT" ] && { echo "PAT not found — run: bash setup_pat.sh"; exit 1; }

cd ~/Documents/SPA_Claude
echo "SPA Push v8.24 — MP-1166 + MP-1167 + tests + registry + KANBAN + sprint_log"
python3 push_to_github.py --files $FILES --message "$COMMIT_MSG" --pat "$PAT"
echo "Push v8.24 complete!"
