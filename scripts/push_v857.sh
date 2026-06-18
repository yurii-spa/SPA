#!/bin/bash
# SPA Push v8.57
# MP-1211: DeFiProtocolVaultPerformanceFeeManagementFeeBaseGapAnalyzer  (69 tests)
#
# SECURITY: PAT is read from macOS Keychain (service: GITHUB_PAT_SPA).
# DO NOT embed PAT or any credentials in this file.
#
# Usage: bash ~/Documents/SPA_Claude/scripts/push_v857.sh

set -e

COMMIT_MSG="feat(v8.57): MP-1211 DeFiProtocolVaultPerformanceFeeManagementFeeBaseGapAnalyzer (69 tests) | advisory/read-only yield_quality Tier-B (weight 0.5) | a vault charges its PERFORMANCE fee on the GROSS return, BEFORE the management (AUM) fee is deducted, so the depositor pays a perf fee on the slice of return the management fee already consumed -- a FEE-ON-FEE; the fair base would be the return NET OF the management fee. metrics: fee_frac=clamp(fee/100); mgmt_consumed_return_pct=max(0,gross_return-net_of_mgmt_return); fee_charged_pct=fee_frac*max(0,gross_return); fair_fee_pct=fee_frac*max(0,net_of_mgmt_return); fee_on_fee_gap_pct=max(0,fee_charged-fair_fee) (perf fee on the management-fee layer); net_return_after_fee_pct=net_of_mgmt_return-fee_charged; net_return_fair_pct=net_of_mgmt_return-fair_fee; overstatement_pct=fee_on_fee_gap; net_is_negative; fee_on_mgmt_fraction=clamp(fee_on_fee_gap/fee_charged,0,1) scale-free classification basis; realization_ratio with net_fair<=0 edge mirroring the hurdle/clawback/netting/equalization template. inputs: gross_return_pct (REQUIRED finite>0 else INSUFFICIENT_DATA), net_of_mgmt_return_pct (signed, may be <gross or <0, default 0 = mgmt fee consumed everything), performance_fee_pct (coerced 0..100), optional management_fee_pct (informational, raises HIGH_MGMT_FEE flag >=2.0). override path: direct fee_on_fee_gap_pct verbatim (+positive gross & fee_charged) -> geometry (mgmt_consumed/fair)->None, GAP_FROM_OVERRIDE flag, geometry-only flags suppressed, realization_ratio anchored to (1-fee_on_mgmt_fraction). classification by fee_on_mgmt_fraction: CLEAN_NET_OF_MGMT_BASE(<=0.05)/MILD_FEE_ON_FEE_GAP(<=0.20)/MODERATE_FEE_ON_FEE_GAP(<=0.50)/SEVERE_FEE_ON_FEE_GAP(>0.50 or net_is_negative)/INSUFFICIENT_DATA. flags CLEAN_NET_BASE / NET_NEGATIVE_AFTER_FEE / FEE_ON_MGMT_LAYER (mgmt_consumed>0) / FULL_FEE_ON_FEE (net_of_mgmt<=0 and gross>0) / HIGH_MGMT_FEE (management_fee_pct>=2.0) / GAP_FROM_OVERRIDE. score=clamp(70*realization_ratio + 30*(1-fee_on_mgmt_fraction),0,100); INSUFFICIENT->0. HIGHER score = perf fee charged on the net-of-management base (gross ~ net_of_mgmt), fee was effectively fair, fee-stacking changes nothing. recommendation TRUST_FEE_STRUCTURE/MINOR_FEE_ON_FEE/DEMAND_NET_OF_MGMT_BASE/AVOID_FEE_ON_FEE; grade A-F; aggregate cleanest_vault/worst_fee_on_fee_vault/avg_score/net_negative_count/position_count; pure stdlib, atomic ring-buffer log (data/vault_performance_fee_management_fee_base_gap_log.json, cap 100), no inf/NaN, read-only/advisory | distinct from performance_fee_high_water_mark (temporal HWM-reset of one NAV series), performance_fee_volatility_tax (path-asymmetry of one series over time), performance_fee_crystallization_frequency (how OFTEN), performance_fee_hurdle_rate_gap (fee on beta vs alpha / benchmark hurdle), performance_fee_unrealized_gain_clawback_gap (temporal reversal of one unrealized mark), performance_fee_cross_sleeve_netting_gap (cross-sectional sleeve winners vs losers), performance_fee_subscription_timing_equalization_gap (mid-period subscriber pre-entry gains), management_fee_accrual (the continuous AUM-fee drag itself), management_fee_on_idle_capital (mgmt fee on uninvested cash) -- novel axis: the INTERACTION where the PERFORMANCE-fee BASE is gross-of-management-fee rather than net-of-management-fee (fee-on-fee / fee-stacking) | registry Tier-B yield_quality weight 0.5 | self-authored sprint: no type=code&status=ready task in KANBAN (backlog=26: 11 agent_infra needing git/launchd/keychain on Mac + P0/P1-FIX/USER ACTION; features=7 P3; ideas=3 LOW), orchestrator chose the topic after a non-overlap scan (no fee-on-fee / net-of-management-base / management-fee-base module exists on the perf-fee axis; seven existing perf-fee modules + two management-fee modules model other axes), added MP-1211 to KANBAN.json done and took it into work; updated KANBAN sprint_completed/sprint_current v8.56->v8.57 + done MP-1211 done_count 905->906, appended sprint_log, created this push script | architect review: last completed before this run was v8.56 (minor=56, not divisible by 5, not ending in 0/5) -> no review due; spa_core.dev_agents.architect is in any case unavailable in the sandbox (ModuleNotFoundError: anthropic) | STRICTLY READ-ONLY (SPA-BL-011): risk/execution/monitoring/allocator/cycle_runner.py/golive_checker.py untouched by this sprint"

FILES="/Users/yuriikulieshov/Documents/SPA_Claude/spa_core/analytics/defi_protocol_vault_performance_fee_management_fee_base_gap_analyzer.py
/Users/yuriikulieshov/Documents/SPA_Claude/spa_core/tests/test_defi_protocol_vault_performance_fee_management_fee_base_gap_analyzer.py
/Users/yuriikulieshov/Documents/SPA_Claude/data/vault_performance_fee_management_fee_base_gap_log.json
/Users/yuriikulieshov/Documents/SPA_Claude/spa_core/analytics/_module_registry.py
/Users/yuriikulieshov/Documents/SPA_Claude/KANBAN.json
/Users/yuriikulieshov/Documents/SPA_Claude/sprint_log.md
/Users/yuriikulieshov/Documents/SPA_Claude/scripts/push_v857.sh"

# PAT resolution: Keychain -> env GITHUB_PAT_SPA -> env SPA_GITHUB_PAT -> ~/.github_pat
PAT=$(security find-generic-password -s GITHUB_PAT_SPA -w 2>/dev/null || echo "")
[ -z "$PAT" ] && PAT="${GITHUB_PAT_SPA:-${SPA_GITHUB_PAT:-}}"
[ -z "$PAT" ] && [ -f ~/.github_pat ] && PAT=$(cat ~/.github_pat)
[ -z "$PAT" ] && { echo "PAT not found — run: bash setup_pat.sh"; exit 1; }

cd ~/Documents/SPA_Claude
echo "SPA Push v8.57 — MP-1211 + tests + registry + KANBAN + sprint_log"
python3 push_to_github.py --files $FILES --message "$COMMIT_MSG" --pat "$PAT"
echo "Push v8.57 complete!"
