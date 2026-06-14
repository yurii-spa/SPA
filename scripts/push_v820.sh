#!/bin/bash
# SPA Push v8.20
# MP-1158: DeFiProtocolVaultPendingHarvestPremiumAnalyzer  (132 tests)
# MP-1159: DeFiProtocolVaultRoundTripCostAnalyzer          (134 tests)
#
# SECURITY: PAT is read from macOS Keychain (service: GITHUB_PAT_SPA).
# DO NOT embed PAT or any credentials in this file.
#
# Usage: bash ~/Documents/SPA_Claude/scripts/push_v820.sh

set -e

COMMIT_MSG="feat(v8.20): MP-1158 VaultPendingHarvestPremiumAnalyzer + MP-1159 VaultRoundTripCostAnalyzer | 132+134=266 tests | advisory/read-only | pending unharvested-reward share-price premium / deposit-timing edge (pending_premium_pct, net_premium_pct after perf-fee, harvest_progress_pct, hours_to_next_harvest, timing_edge_pct, score; CLEAN/MINOR/MODERATE/LARGE_PREMIUM) [new category vault_timing] + capital-rotation round-trip cost vs APR advantage over holding horizon (round_trip_cost_pct, breakeven_days, net_gain_pct@horizon, covers_horizon, score; CHEAP/FAIR/EXPENSIVE/PROHIBITIVE/NEVER_BREAKS_EVEN) [new category cost_efficiency] | registry Tier-B +2 | pure stdlib, atomic ring-buffer logs"

FILES="/Users/yuriikulieshov/Documents/SPA_Claude/spa_core/analytics/defi_protocol_vault_pending_harvest_premium_analyzer.py
/Users/yuriikulieshov/Documents/SPA_Claude/spa_core/analytics/defi_protocol_vault_round_trip_cost_analyzer.py
/Users/yuriikulieshov/Documents/SPA_Claude/spa_core/tests/test_defi_protocol_vault_pending_harvest_premium_analyzer.py
/Users/yuriikulieshov/Documents/SPA_Claude/spa_core/tests/test_defi_protocol_vault_round_trip_cost_analyzer.py
/Users/yuriikulieshov/Documents/SPA_Claude/data/vault_pending_harvest_premium_log.json
/Users/yuriikulieshov/Documents/SPA_Claude/data/vault_round_trip_cost_log.json
/Users/yuriikulieshov/Documents/SPA_Claude/spa_core/analytics/_module_registry.py
/Users/yuriikulieshov/Documents/SPA_Claude/KANBAN.json
/Users/yuriikulieshov/Documents/SPA_Claude/sprint_log.md
/Users/yuriikulieshov/Documents/SPA_Claude/scripts/push_v820.sh"

# PAT resolution: Keychain → env GITHUB_PAT_SPA → env SPA_GITHUB_PAT → ~/.github_pat
PAT=$(security find-generic-password -s GITHUB_PAT_SPA -w 2>/dev/null || echo "")
[ -z "$PAT" ] && PAT="${GITHUB_PAT_SPA:-${SPA_GITHUB_PAT:-}}"
[ -z "$PAT" ] && [ -f ~/.github_pat ] && PAT=$(cat ~/.github_pat)
[ -z "$PAT" ] && { echo "PAT not found — run: bash setup_pat.sh"; exit 1; }

cd ~/Documents/SPA_Claude
echo "SPA Push v8.20 — MP-1158 + MP-1159 + tests + registry + KANBAN + sprint_log"
python3 push_to_github.py --files $FILES --message "$COMMIT_MSG" --pat "$PAT"
echo "Push v8.20 complete!"
