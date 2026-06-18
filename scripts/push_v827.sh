#!/bin/bash
# SPA Push v8.27
# MP-1172: DeFiProtocolVaultDepositorExitVelocityAnalyzer        (160 tests)
# MP-1173: DeFiProtocolVaultHarvestCycleEntryTimingAnalyzer      (163 tests)
#
# SECURITY: PAT is read from macOS Keychain (service: GITHUB_PAT_SPA).
# DO NOT embed PAT or any credentials in this file.
#
# Usage: bash ~/Documents/SPA_Claude/scripts/push_v827.sh

set -e

COMMIT_MSG="feat(v8.27): MP-1172 VaultDepositorExitVelocityAnalyzer + MP-1173 VaultHarvestCycleEntryTimingAnalyzer | 160+163=323 tests | advisory/read-only | exit velocity: measures the VELOCITY and ACCELERATION of depositor net outflows as an early bank-run/exit-stampede signal, distinct from withdrawal-queue (Tier-A capacity), redemption-cooldown (lockup) and exit-liquidity (depth) (outflow_rate_pct, prev_outflow_rate_pct, acceleration_pct, acceleration_ratio, vs_baseline_ratio, days_to_50pct_drain; CALM/ELEVATED/DRAINING/BANK_RUN; higher score=calmer) [category liquidity] + harvest-cycle entry timing: for a holder about to DEPOSIT, where in the harvest/distribution cycle they enter (just-after-harvest = cleanest basis; snapshot_gated flips the call) (cycle_position_pct, hours_to_next_harvest, is_overdue, near_harvest, just_harvested; OPTIMAL_ENTRY/GOOD_ENTRY/LATE_CYCLE/PRE_HARVEST; higher score=cleaner entry) [category yield_quality] | registry Tier-B +2 (B=424, total 616) | pure stdlib, atomic ring-buffer logs, no inf/NaN"

FILES="/Users/yuriikulieshov/Documents/SPA_Claude/spa_core/analytics/defi_protocol_vault_depositor_exit_velocity_analyzer.py
/Users/yuriikulieshov/Documents/SPA_Claude/spa_core/analytics/defi_protocol_vault_harvest_cycle_entry_timing_analyzer.py
/Users/yuriikulieshov/Documents/SPA_Claude/spa_core/tests/test_defi_protocol_vault_depositor_exit_velocity_analyzer.py
/Users/yuriikulieshov/Documents/SPA_Claude/spa_core/tests/test_defi_protocol_vault_harvest_cycle_entry_timing_analyzer.py
/Users/yuriikulieshov/Documents/SPA_Claude/data/vault_depositor_exit_velocity_log.json
/Users/yuriikulieshov/Documents/SPA_Claude/data/vault_harvest_cycle_entry_timing_log.json
/Users/yuriikulieshov/Documents/SPA_Claude/spa_core/analytics/_module_registry.py
/Users/yuriikulieshov/Documents/SPA_Claude/KANBAN.json
/Users/yuriikulieshov/Documents/SPA_Claude/sprint_log.md
/Users/yuriikulieshov/Documents/SPA_Claude/scripts/push_v827.sh"

# PAT resolution: Keychain → env GITHUB_PAT_SPA → env SPA_GITHUB_PAT → ~/.github_pat
PAT=$(security find-generic-password -s GITHUB_PAT_SPA -w 2>/dev/null || echo "")
[ -z "$PAT" ] && PAT="${GITHUB_PAT_SPA:-${SPA_GITHUB_PAT:-}}"
[ -z "$PAT" ] && [ -f ~/.github_pat ] && PAT=$(cat ~/.github_pat)
[ -z "$PAT" ] && { echo "PAT not found — run: bash setup_pat.sh"; exit 1; }

cd ~/Documents/SPA_Claude
echo "SPA Push v8.27 — MP-1172 + MP-1173 + tests + registry + KANBAN + sprint_log"
python3 push_to_github.py --files $FILES --message "$COMMIT_MSG" --pat "$PAT"
echo "Push v8.27 complete!"
