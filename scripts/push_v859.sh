#!/bin/bash
# SPA Push v8.59
# MP-1213: DeFiProtocolVaultPerformanceFeeGrossOfCostBaseGapAnalyzer  (89 tests)
#
# SECURITY: PAT is read from macOS Keychain (service: GITHUB_PAT_SPA).
# DO NOT embed PAT or any credentials in this file.
#
# Usage: bash ~/Documents/SPA_Claude/scripts/push_v859.sh

set -e

COMMIT_MSG="feat(v8.59): MP-1213 DeFiProtocolVaultPerformanceFeeGrossOfCostBaseGapAnalyzer (89 tests) | advisory/read-only yield_quality Tier-B (weight 0.5) | a vault charges its PERFORMANCE fee on the GROSS harvested profit BEFORE deducting the gas/keeper/harvest costs the vault itself pays to realize that profit; the FAIR base is the profit NET OF those harvest costs (the depositor only ever keeps the net-of-cost profit), so charging the perf fee on the gross profit makes the depositor pay a fee on the harvest-cost slice they never kept -- a fee-on-cost / fee-base inflation. metrics: fee_frac=clamp(fee/100); gross_profit_pct REQUIRED finite>0 else INSUFFICIENT_DATA; net_of_cost_profit_pct (default 0, may be<gross, may be negative); cost_consumed_profit_pct=max(0,gross-net); fee_charged_pct=fee_frac*max(0,gross) (reality); fair_fee_pct=fee_frac*max(0,net) (depositor belief); fee_on_cost_gap_pct=max(0,fee_charged-fair_fee) (perf fee levied on the harvest-cost layer); fee_on_cost_fraction=clamp(fee_on_cost_gap/fee_charged,0,1) scale-free classification basis (size-independent); net_return_after_fee_pct=net-fee_charged; net_return_fair_pct=net-fair_fee; overstatement_pct=fee_on_cost_gap; net_is_negative; realization_ratio with the non-positive-fair edge mirroring the management-fee-base template. inputs: gross_profit_pct (REQUIRED finite>0), net_of_cost_profit_pct (default 0.0), performance_fee_pct (REQUIRED finite, coerced 0..100), optional harvest_cost_pct (informational, raises HIGH_HARVEST_COST flag >=5%). override path: direct fee_on_cost_gap_pct verbatim (+positive gross & fee_charged) -> geometry (net/cost_consumed/fair/net_returns)->None, GAP_FROM_OVERRIDE flag, geometry-only flags suppressed, fee_on_cost_fraction=clamp(gap/fee_charged,0,1), realization_ratio anchored to (1-fee_on_cost_fraction). classification by fee_on_cost_fraction: CLEAN_NET_OF_COST_BASE(<=0.05)/MILD_FEE_ON_COST_GAP(<=0.20)/MODERATE_FEE_ON_COST_GAP(<=0.50)/SEVERE_FEE_ON_COST_GAP(>0.50 or net_is_negative)/INSUFFICIENT_DATA. flags CLEAN_NET_BASE / NET_NEGATIVE_AFTER_FEE / FEE_ON_HARVEST_COST (gap>0) / FULL_FEE_ON_COST (net<=0 & gross>0, fee fully on cost) / HIGH_HARVEST_COST (harvest_cost_pct>=5) / GAP_FROM_OVERRIDE. score=clamp(70*realization_ratio + 30*(1-fee_on_cost_fraction),0,100); INSUFFICIENT->0. HIGHER score = perf fee charged on the net-of-cost base (gross~net), fee effectively fair. recommendation TRUST_FEE_STRUCTURE/MINOR_FEE_ON_COST/DEMAND_NET_OF_COST_BASE/AVOID_FEE_ON_COST; grade A-F; aggregate cleanest_vault/worst_fee_on_cost_vault/avg_score/net_negative_count/position_count; pure stdlib, atomic ring-buffer log (data/vault_performance_fee_gross_of_cost_base_gap_log.json, cap 100), no inf/NaN, read-only/advisory | distinct from performance_fee_management_fee_base_gap (adds back the MANAGEMENT/AUM fee to the base -- HERE it is the gas/keeper/harvest cost), defi_gas_cost_yield_drag / defi_protocol_gas_cost_breakeven / gas_cost_sensitivity (price gas DRAG on yield, NOT the performance-fee BASE), performance_fee_high_water_mark (temporal HWM-reset), performance_fee_volatility_tax (path-asymmetry), performance_fee_crystallization_frequency (how OFTEN), performance_fee_hurdle_rate_gap (fee on beta vs alpha) -- novel axis: a perf-fee BASE that is GROSS-OF-HARVEST-COST rather than net-of-harvest-cost | registry Tier-B yield_quality weight 0.5 (B 464->465, ALL 657->658) | self-authored sprint: no type=code&status=ready task in KANBAN (backlog=26: 11 agent_infra needing git/launchd/keychain on Mac + USER ACTION/P0-P2; features=7 P3; ideas=3 LOW), orchestrator chose the topic after a non-overlap grep scan of 657 analytics modules, added MP-1213 to KANBAN.json done and took it into work; updated KANBAN sprint_completed/sprint_current v8.58->v8.59 + done MP-1213, appended sprint_log, created this push script | architect review: last completed before this run was v8.58 (minor=58, not divisible by 5, not ending in 0/5) -> no review due; spa_core.dev_agents.architect is in any case unavailable in the sandbox (ModuleNotFoundError: anthropic) | STRICTLY READ-ONLY (SPA-BL-011): risk/execution/monitoring/allocator/cycle_runner.py/golive_checker.py untouched by this sprint"

FILES="/Users/yuriikulieshov/Documents/SPA_Claude/spa_core/analytics/defi_protocol_vault_performance_fee_gross_of_cost_base_gap_analyzer.py
/Users/yuriikulieshov/Documents/SPA_Claude/spa_core/tests/test_defi_protocol_vault_performance_fee_gross_of_cost_base_gap_analyzer.py
/Users/yuriikulieshov/Documents/SPA_Claude/data/vault_performance_fee_gross_of_cost_base_gap_log.json
/Users/yuriikulieshov/Documents/SPA_Claude/spa_core/analytics/_module_registry.py
/Users/yuriikulieshov/Documents/SPA_Claude/KANBAN.json
/Users/yuriikulieshov/Documents/SPA_Claude/sprint_log.md
/Users/yuriikulieshov/Documents/SPA_Claude/scripts/push_v859.sh"

# PAT resolution: Keychain -> env GITHUB_PAT_SPA -> env SPA_GITHUB_PAT -> ~/.github_pat
PAT=$(security find-generic-password -s GITHUB_PAT_SPA -w 2>/dev/null || echo "")
[ -z "$PAT" ] && PAT="${GITHUB_PAT_SPA:-${SPA_GITHUB_PAT:-}}"
[ -z "$PAT" ] && [ -f ~/.github_pat ] && PAT=$(cat ~/.github_pat)
[ -z "$PAT" ] && { echo "PAT not found — run: bash setup_pat.sh"; exit 1; }

cd ~/Documents/SPA_Claude
echo "SPA Push v8.59 — MP-1213 + tests + registry + KANBAN + sprint_log"
python3 push_to_github.py --files $FILES --message "$COMMIT_MSG" --pat "$PAT"
echo "Push v8.59 complete!"
