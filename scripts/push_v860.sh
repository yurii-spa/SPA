#!/bin/bash
# SPA Push v8.60
# MP-1214: DeFiProtocolVaultPerformanceFeeProtocolRevenueShareBaseGapAnalyzer  (91 tests)
#
# SECURITY: PAT is read from macOS Keychain (service: GITHUB_PAT_SPA).
# DO NOT embed PAT or any credentials in this file.
#
# Usage: bash ~/Documents/SPA_Claude/scripts/push_v860.sh

set -e

COMMIT_MSG="feat(v8.60): MP-1214 DeFiProtocolVaultPerformanceFeeProtocolRevenueShareBaseGapAnalyzer (91 tests) | advisory/read-only yield_quality Tier-B (weight 0.5) | a vault's strategy deposits into an UNDERLYING DeFi protocol that takes a revenue-share / take-rate cut of the yield; the vault charges its PERFORMANCE fee on the GROSS yield (before the underlying protocol's revenue-share cut) rather than on the net-of-protocol-share yield the depositor actually receives, so the depositor pays a perf fee on the slice of yield the underlying protocol already extracted -- a fee-base inflation on an EXTERNAL cost layer. metrics: fee_frac=clamp(fee/100); gross_yield_pct REQUIRED finite>0 else INSUFFICIENT_DATA; net_of_protocol_share_yield_pct (default 0, may be<gross, may be negative); protocol_consumed_yield_pct=max(0,gross-net); fee_charged_pct=fee_frac*max(0,gross) (reality); fair_fee_pct=fee_frac*max(0,net) (depositor belief); fee_on_protocol_share_gap_pct=max(0,fee_charged-fair_fee) (perf fee levied on the protocol-revenue-share layer); fee_on_protocol_share_fraction=clamp(gap/fee_charged,0,1) scale-free classification basis (size-independent); net_return_after_fee_pct=net-fee_charged; net_return_fair_pct=net-fair_fee; overstatement_pct=gap; net_is_negative; realization_ratio with the non-positive-fair edge mirroring the gross-of-cost/management-fee-base template. inputs: gross_yield_pct (REQUIRED finite>0), net_of_protocol_share_yield_pct (default 0.0), performance_fee_pct (REQUIRED finite, coerced 0..100), optional protocol_take_rate_pct (informational, raises HIGH_PROTOCOL_TAKE flag >=20%). override path: direct fee_on_protocol_share_gap_pct verbatim (+positive gross & fee_charged) -> geometry (net/protocol_consumed/fair/net_returns)->None, GAP_FROM_OVERRIDE flag, geometry-only flags suppressed, fraction=clamp(gap/fee_charged,0,1), realization_ratio anchored to (1-fraction). classification by fee_on_protocol_share_fraction: CLEAN_NET_OF_PROTOCOL_BASE(<=0.05)/MILD_FEE_ON_PROTOCOL_SHARE_GAP(<=0.20)/MODERATE_FEE_ON_PROTOCOL_SHARE_GAP(<=0.50)/SEVERE_FEE_ON_PROTOCOL_SHARE_GAP(>0.50 or net_is_negative)/INSUFFICIENT_DATA. flags CLEAN_NET_BASE / NET_NEGATIVE_AFTER_FEE / FEE_ON_PROTOCOL_SHARE (protocol_consumed>0) / FULL_FEE_ON_PROTOCOL_SHARE (net<=0 & gross>0, fee fully on the protocol-take layer) / HIGH_PROTOCOL_TAKE (protocol_take_rate_pct>=20) / GAP_FROM_OVERRIDE. score=clamp(70*realization_ratio + 30*(1-fee_on_protocol_share_fraction),0,100); INSUFFICIENT->0. HIGHER score = perf fee charged on the net-of-protocol-share base (gross~net), fee effectively fair. recommendation TRUST_FEE_STRUCTURE/MINOR_FEE_ON_PROTOCOL_SHARE/DEMAND_NET_OF_PROTOCOL_BASE/AVOID_FEE_ON_PROTOCOL_SHARE; grade A-F; aggregate cleanest_vault/worst_protocol_share_vault/avg_score/net_negative_count/position_count; pure stdlib, atomic ring-buffer log (data/vault_performance_fee_protocol_revenue_share_base_gap_log.json, cap 100), no inf/NaN, read-only/advisory | distinct from performance_fee_gross_of_cost_base_gap (base layer = the vault's own gas/keeper/HARVEST cost), performance_fee_management_fee_base_gap (base layer = the vault's own MANAGEMENT/AUM fee, fee-on-fee), protocol_revenue_share_analyzer (analyzes a protocol's revenue DISTRIBUTION generally, NOT the perf-fee base), and the 8 other perf-fee modules (HWM-reset / volatility-tax / crystallization-frequency / hurdle-rate-gap / unrealized-clawback / cross-sleeve-netting / subscription-timing / catch-up) -- novel axis: a perf-fee BASE that is GROSS-OF the UNDERLYING-PROTOCOL revenue-share (a third, EXTERNAL cost layer) rather than net-of-protocol-share | registry Tier-B yield_quality weight 0.5 (B 465->466, ALL 657->658) | self-authored sprint: no type=code&status=ready task in KANBAN (backlog=26: 11 agent_infra needing git/launchd/keychain on Mac + USER ACTION/P0-P2; features=7 P3; ideas=3 LOW), orchestrator chose the topic after a non-overlap grep scan of analytics modules, added MP-1214 to KANBAN.json done and took it into work; updated KANBAN sprint_completed/sprint_current v8.59->v8.60 + done MP-1214 (done_count 907->908), appended sprint_log, created this push script | architect review: v8.60 ends in 0 -> review due BUT spa_core.dev_agents.architect is unavailable in the sandbox (ModuleNotFoundError: anthropic); backlog scanned manually -> no type=code&status=ready | STRICTLY READ-ONLY (SPA-BL-011): risk/execution/monitoring/allocator/cycle_runner.py/golive_checker.py untouched by this sprint"

FILES="/Users/yuriikulieshov/Documents/SPA_Claude/spa_core/analytics/defi_protocol_vault_performance_fee_protocol_revenue_share_base_gap_analyzer.py
/Users/yuriikulieshov/Documents/SPA_Claude/spa_core/tests/test_defi_protocol_vault_performance_fee_protocol_revenue_share_base_gap_analyzer.py
/Users/yuriikulieshov/Documents/SPA_Claude/data/vault_performance_fee_protocol_revenue_share_base_gap_log.json
/Users/yuriikulieshov/Documents/SPA_Claude/spa_core/analytics/_module_registry.py
/Users/yuriikulieshov/Documents/SPA_Claude/KANBAN.json
/Users/yuriikulieshov/Documents/SPA_Claude/sprint_log.md
/Users/yuriikulieshov/Documents/SPA_Claude/scripts/push_v860.sh"

# PAT resolution: Keychain -> env GITHUB_PAT_SPA -> env SPA_GITHUB_PAT -> ~/.github_pat
PAT=$(security find-generic-password -s GITHUB_PAT_SPA -w 2>/dev/null || echo "")
[ -z "$PAT" ] && PAT="${GITHUB_PAT_SPA:-${SPA_GITHUB_PAT:-}}"
[ -z "$PAT" ] && [ -f ~/.github_pat ] && PAT=$(cat ~/.github_pat)
[ -z "$PAT" ] && { echo "PAT not found — run: bash setup_pat.sh"; exit 1; }

cd ~/Documents/SPA_Claude
echo "SPA Push v8.60 — MP-1214 + tests + registry + KANBAN + sprint_log"
python3 push_to_github.py --files $FILES --message "$COMMIT_MSG" --pat "$PAT"
echo "Push v8.60 complete!"
