#!/bin/bash
# SPA Push v8.55
# MP-1209: DeFiProtocolVaultPerformanceFeeCrossSleeveNettingGapAnalyzer  (59 tests)
#
# SECURITY: PAT is read from macOS Keychain (service: GITHUB_PAT_SPA).
# DO NOT embed PAT or any credentials in this file.
#
# Usage: bash ~/Documents/SPA_Claude/scripts/push_v855.sh

set -e

COMMIT_MSG="feat(v8.55): MP-1209 DeFiProtocolVaultPerformanceFeeCrossSleeveNettingGapAnalyzer (59 tests) | advisory/read-only yield_quality Tier-B (weight 0.5) | a multi-sleeve vault charges a PERFORMANCE fee on the GROSS gains of its WINNING sleeves WITHOUT netting concurrent LOSING sleeves in the same fee period (no cross-sleeve loss offset), so the depositor pays a fee on sleeve winners even when the vault's NET return across all sleeves is far lower or negative; the fee is levied on un-netted gross winners while the fair fee would be levied only on the netted portfolio return. metrics: fee_frac=clamp(fee/100); offset_loss_pct=max(0,gross_winner-net_portfolio); fee_charged_pct=fee_frac*max(0,gross_winner); fair_fee_pct=fee_frac*max(0,net_portfolio); netting_gap_pct=max(0,fee_charged-fair_fee) (fee on offset winners, never netted); net_return_after_fee_pct=net_portfolio-fee_charged; net_return_fair_pct=net_portfolio-fair_fee; overstatement_pct=netting_gap; net_is_negative; fee_on_unnetted_fraction=clamp(netting_gap/fee_charged,0,1) scale-free classification basis; realization_ratio with net_fair<=0 edge mirroring the hurdle/clawback template. inputs: gross_winner_gain_pct (REQUIRED finite>0 else INSUFFICIENT_DATA), net_portfolio_gain_pct (signed, may be <winners or <0, default 0), performance_fee_pct (coerced 0..100), optional sleeve_count. override path: direct netting_gap_pct verbatim (+positive gross_winner & fee_charged) -> geometry (net/offset/fair)->None, GAP_FROM_OVERRIDE flag, geometry-only flags suppressed, realization_ratio anchored to (1-fee_on_unnetted_fraction). classification by fee_on_unnetted_fraction: CLEAN_FULLY_NETTED(<=0.05)/MILD_NETTING_GAP(<=0.20)/MODERATE_NETTING_GAP(<=0.50)/SEVERE_NETTING_GAP(>0.50 or net_is_negative)/INSUFFICIENT_DATA. flags CLEAN_FULL_NETTING / NET_NEGATIVE_AFTER_FEE / FEE_ON_OFFSET_GAINS (offset>0) / FULL_OFFSET (net<=0 and winners>0) / MANY_SLEEVES (sleeve_count>=4) / GAP_FROM_OVERRIDE. score=clamp(70*realization_ratio + 30*(1-fee_on_unnetted_fraction),0,100); INSUFFICIENT->0. HIGHER score = sleeves all net winners (net ~ gross winners), fee was effectively fair, full netting changes nothing. recommendation TRUST_FEE_STRUCTURE/MINOR_NETTING_GAP/DEMAND_CROSS_SLEEVE_NETTING/AVOID_NO_NETTING; grade A-F; aggregate cleanest_vault/worst_netting_vault/avg_score/net_negative_count/position_count; pure stdlib, atomic ring-buffer log (data/vault_performance_fee_cross_sleeve_netting_gap_log.json, cap 100), no inf/NaN, read-only/advisory | distinct from performance_fee_high_water_mark (temporal HWM-reset of one NAV series), performance_fee_volatility_tax (path-asymmetry of one series over time), performance_fee_crystallization_frequency (how OFTEN), performance_fee_hurdle_rate_gap (fee on beta vs alpha / benchmark hurdle), performance_fee_unrealized_gain_clawback_gap (temporal reversal of one unrealized mark), net_of_loss_yield_realization (yield-vs-loss NAV reconciliation) -- novel axis: a performance fee charged on GROSS winning sleeves without netting concurrent LOSING sleeves (cross-sectional, contemporaneous) | registry Tier-B B=459->460, total 651->652 | self-authored sprint: no type=code&status=ready task in KANBAN (backlog=26: agent_infra needing git/launchd/keychain on Mac + P0/P1-FIX/USER ACTION; features=7 P3; ideas=3 LOW), orchestrator chose the topic after a non-overlap grep (no netting/cross-sleeve/loss-offset module exists on the perf-fee axis; five existing perf-fee modules model other axes), added MP-1209 to KANBAN.json done and took it into work; updated KANBAN sprint_completed/sprint_current v8.54->v8.55 + done MP-1209 done_count 903->904, appended sprint_log, created this push script | architect review: last completed before this was v8.54 (not ending in 0/5) -> no separate review due; spa_core.dev_agents.architect unavailable in sandbox anyway (ModuleNotFoundError: anthropic) | STRICTLY READ-ONLY (SPA-BL-011): risk/execution/monitoring/allocator/cycle_runner.py/golive_checker.py untouched"

FILES="/Users/yuriikulieshov/Documents/SPA_Claude/spa_core/analytics/defi_protocol_vault_performance_fee_cross_sleeve_netting_gap_analyzer.py
/Users/yuriikulieshov/Documents/SPA_Claude/spa_core/tests/test_defi_protocol_vault_performance_fee_cross_sleeve_netting_gap_analyzer.py
/Users/yuriikulieshov/Documents/SPA_Claude/data/vault_performance_fee_cross_sleeve_netting_gap_log.json
/Users/yuriikulieshov/Documents/SPA_Claude/spa_core/analytics/_module_registry.py
/Users/yuriikulieshov/Documents/SPA_Claude/KANBAN.json
/Users/yuriikulieshov/Documents/SPA_Claude/sprint_log.md
/Users/yuriikulieshov/Documents/SPA_Claude/scripts/push_v855.sh"

# PAT resolution: Keychain -> env GITHUB_PAT_SPA -> env SPA_GITHUB_PAT -> ~/.github_pat
PAT=$(security find-generic-password -s GITHUB_PAT_SPA -w 2>/dev/null || echo "")
[ -z "$PAT" ] && PAT="${GITHUB_PAT_SPA:-${SPA_GITHUB_PAT:-}}"
[ -z "$PAT" ] && [ -f ~/.github_pat ] && PAT=$(cat ~/.github_pat)
[ -z "$PAT" ] && { echo "PAT not found — run: bash setup_pat.sh"; exit 1; }

cd ~/Documents/SPA_Claude
echo "SPA Push v8.55 — MP-1209 + tests + registry + KANBAN + sprint_log"
python3 push_to_github.py --files $FILES --message "$COMMIT_MSG" --pat "$PAT"
echo "Push v8.55 complete!"
