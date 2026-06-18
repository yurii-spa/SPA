#!/bin/bash
# SPA Push v8.67
# MP-1221: DeFiProtocolVaultPerformanceFeeGrossOfInsurancePremiumBaseGapAnalyzer  (91 tests)
#
# SECURITY: PAT is read from macOS Keychain (service: GITHUB_PAT_SPA).
# DO NOT embed PAT or any credentials in this file.
#
# Usage: bash ~/Documents/SPA_Claude/scripts/push_v867.sh

set -e

COMMIT_MSG="feat(v8.67): MP-1221 DeFiProtocolVaultPerformanceFeeGrossOfInsurancePremiumBaseGapAnalyzer (91 tests) | advisory/read-only yield_quality Tier-B (weight 0.5) | a vault buys recurring smart-contract COVER / INSURANCE (e.g. Nexus Mutual / cover-protocol) and pays an insurance premium each period = a real cash outflow; the depositor's economically realized yield is net_of_insurance_premium = gross_yield - insurance_premium. The vault charges its PERFORMANCE fee on the GROSS yield (before netting the insurance premium), not on the NET-OF-INSURANCE-PREMIUM yield the depositor actually realized -- so the depositor pays a performance fee on the slice of yield the premium already erased (a fee-on-insurance-premium / fee-base inflation). metrics: fee_frac=clamp(performance_fee_pct/100,0,1); gross_yield_pct REQUIRED finite>0 else INSUFFICIENT_DATA; net_of_insurance_premium_yield_pct (default 0, may be < gross, may be negative); insurance_premium_consumed_yield_pct=max(0,gross-net); fee_charged_pct=fee_frac*max(0,gross); fair_fee_pct=fee_frac*max(0,net); fee_on_insurance_premium_gap_pct=max(0,fee_charged-fair); fee_on_insurance_premium_fraction=clamp(gap/fee_charged,0,1) scale-free classification basis; net_return_after_fee/net_return_fair; realization_ratio=clamp(net_after_fee/net_fair,0,1) with edge for non-positive fair. classification CLEAN_NET_OF_INSURANCE_PREMIUM_BASE(<=0.05)/MILD_FEE_ON_INSURANCE_PREMIUM_GAP(<=0.20)/MODERATE_FEE_ON_INSURANCE_PREMIUM_GAP(<=0.50)/SEVERE_FEE_ON_INSURANCE_PREMIUM_GAP(>0.50 OR net-negative)/INSUFFICIENT_DATA. flags CLEAN_NET_BASE / NET_NEGATIVE_AFTER_FEE / FEE_ON_INSURANCE_PREMIUM / FULL_FEE_ON_INSURANCE_PREMIUM / HIGH_INSURANCE_PREMIUM (insurance_premium_cost_pct>=10) / GAP_FROM_OVERRIDE. score=clamp(70*realisation + 30*(1-fee_on_insurance_premium_fraction),0,100); INSUFFICIENT->0. HIGHER score = the performance fee was charged on the net-of-insurance-premium base (gross ~= net_of_insurance_premium), the fee was effectively fair. recommendation TRUST_FEE_STRUCTURE/MINOR_FEE_ON_INSURANCE_PREMIUM/DEMAND_NET_OF_INSURANCE_PREMIUM_BASE/AVOID_FEE_ON_INSURANCE_PREMIUM; grade A-F. override path: direct fee_on_insurance_premium_gap_pct + positive fee_charged_pct + positive gross -> taken verbatim (negative->magnitude) -> geometry (net_of_insurance_premium/insurance_premium_consumed/fair)->None, GAP_FROM_OVERRIDE flag, geometry-only flags suppressed, realization_ratio anchored to (1-fee_on_insurance_premium_fraction). aggregate cleanest_vault/worst_insurance_premium_gap_vault/avg_score/net_negative_count/position_count; pure stdlib, atomic ring-buffer log (data/vault_performance_fee_gross_of_insurance_premium_base_gap_log.json, cap 100), no inf/NaN, read-only/advisory | DISTINCT axis: the performance-fee BASE being gross-of-insurance-premium -- distinct from the other gross_of_* perf-fee base-gap modules (cost=fixed gas/keeper TX, borrow_cost=lending-market loan interest, rebalancing_cost=swap turnover, exit_slippage, funding_cost=perpetual funding carry, reserve_contribution, impermanent_loss, bad_debt_socialization, protocol_revenue_share, management_fee -- none is a recurring insurance/cover premium); distinct from the existing insurance modules (defi_insurance_cost_analyzer / defi_insurance_coverage_analyzer / defi_protocol_insurance_coverage_analyzer measure the insurance COST/COVERAGE itself, here the axis is the perf-fee BASE inflation from charging on the gross pre-premium yield); from hwm/volatility_tax/crystallization_frequency/hurdle_rate_gap/catch_up_clause_gap | registry Tier-B yield_quality weight 0.5 (B 474->475, ALL 666->667) | self-authored sprint: no type=code&status=ready task in KANBAN (backlog: agent_infra needing git/launchd/keychain on Mac + USER ACTION/P0-P2; features P3; ideas LOW), orchestrator chose the topic after a non-overlap grep scan of 666 analytics modules (a recurring cover/insurance premium existed only as cost/coverage analyzers, never as a performance-fee base layer), added MP-1221 to KANBAN.json done and took it into work; updated KANBAN sprint_completed/sprint_current v8.66->v8.67 (sprint_current v8.68) + done MP-1221 (done_count 914->915), appended sprint_log, created this push script | architect review: last completed v8.66 ends in 6 (not 0/5) -> review NOT due; backlog scanned manually -> no type=code&status=ready, no architectural regressions | STRICTLY READ-ONLY (SPA-BL-011): risk/execution/monitoring/allocator/cycle_runner.py/golive_checker.py untouched by this sprint"

FILES="/Users/yuriikulieshov/Documents/SPA_Claude/spa_core/analytics/defi_protocol_vault_performance_fee_gross_of_insurance_premium_base_gap_analyzer.py
/Users/yuriikulieshov/Documents/SPA_Claude/spa_core/tests/test_defi_protocol_vault_performance_fee_gross_of_insurance_premium_base_gap_analyzer.py
/Users/yuriikulieshov/Documents/SPA_Claude/data/vault_performance_fee_gross_of_insurance_premium_base_gap_log.json
/Users/yuriikulieshov/Documents/SPA_Claude/spa_core/analytics/_module_registry.py
/Users/yuriikulieshov/Documents/SPA_Claude/KANBAN.json
/Users/yuriikulieshov/Documents/SPA_Claude/sprint_log.md
/Users/yuriikulieshov/Documents/SPA_Claude/scripts/push_v867.sh"

# PAT resolution: Keychain -> env GITHUB_PAT_SPA -> env SPA_GITHUB_PAT -> ~/.github_pat
PAT=$(security find-generic-password -s GITHUB_PAT_SPA -w 2>/dev/null || echo "")
[ -z "$PAT" ] && PAT="${GITHUB_PAT_SPA:-${SPA_GITHUB_PAT:-}}"
[ -z "$PAT" ] && [ -f ~/.github_pat ] && PAT=$(cat ~/.github_pat)
[ -z "$PAT" ] && { echo "PAT not found — run: bash setup_pat.sh"; exit 1; }

cd ~/Documents/SPA_Claude
echo "SPA Push v8.67 — MP-1221 + tests + registry + KANBAN + sprint_log"
python3 push_to_github.py --files $FILES --message "$COMMIT_MSG" --pat "$PAT"
echo "Push v8.67 complete!"
