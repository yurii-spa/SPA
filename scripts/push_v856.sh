#!/bin/bash
# SPA Push v8.56
# MP-1210: DeFiProtocolVaultPerformanceFeeSubscriptionTimingEqualizationGapAnalyzer  (69 tests)
#
# SECURITY: PAT is read from macOS Keychain (service: GITHUB_PAT_SPA).
# DO NOT embed PAT or any credentials in this file.
#
# Usage: bash ~/Documents/SPA_Claude/scripts/push_v856.sh

set -e

COMMIT_MSG="feat(v8.56): MP-1210 DeFiProtocolVaultPerformanceFeeSubscriptionTimingEqualizationGapAnalyzer (69 tests) | advisory/read-only yield_quality Tier-B (weight 0.5) | a vault crystallizes a PERFORMANCE fee on the FULL-PERIOD NAV gain, but a depositor who SUBSCRIBED MID-PERIOD only earned the gain accrued AFTER his entry; without equalization (series accounting / equalization credits) the mid-period subscriber pays a fee on PRE-ENTRY gains he never earned -- the fee is levied on the full-period gain while the fair fee would be levied only on the post-entry (since-subscription) gain. metrics: fee_frac=clamp(fee/100); pre_entry_gain_pct=max(0,full_period_gain-post_entry_gain); fee_charged_pct=fee_frac*max(0,full_period_gain); fair_fee_pct=fee_frac*max(0,post_entry_gain); equalization_gap_pct=max(0,fee_charged-fair_fee) (fee on pre-entry gains, never equalized); net_return_after_fee_pct=post_entry_gain-fee_charged; net_return_fair_pct=post_entry_gain-fair_fee; overstatement_pct=equalization_gap; net_is_negative; fee_on_pre_entry_fraction=clamp(equalization_gap/fee_charged,0,1) scale-free classification basis; realization_ratio with net_fair<=0 edge mirroring the hurdle/clawback/netting template. inputs: full_period_gain_pct (REQUIRED finite>0 else INSUFFICIENT_DATA), post_entry_gain_pct (signed, may be <full or <0, default 0 = entered at the peak), performance_fee_pct (coerced 0..100), optional entry_fraction_of_period (0..1). override path: direct equalization_gap_pct verbatim (+positive full & fee_charged) -> geometry (pre_entry/fair)->None, GAP_FROM_OVERRIDE flag, geometry-only flags suppressed, realization_ratio anchored to (1-fee_on_pre_entry_fraction). classification by fee_on_pre_entry_fraction: CLEAN_FULLY_EQUALIZED(<=0.05)/MILD_EQUALIZATION_GAP(<=0.20)/MODERATE_EQUALIZATION_GAP(<=0.50)/SEVERE_EQUALIZATION_GAP(>0.50 or net_is_negative)/INSUFFICIENT_DATA. flags CLEAN_FULL_EQUALIZATION / NET_NEGATIVE_AFTER_FEE / FEE_ON_PRE_ENTRY_GAINS (pre_entry>0) / FULL_PRE_ENTRY (post_entry<=0 and full>0) / LATE_SUBSCRIPTION (entry_fraction>=0.5) / GAP_FROM_OVERRIDE. score=clamp(70*realization_ratio + 30*(1-fee_on_pre_entry_fraction),0,100); INSUFFICIENT->0. HIGHER score = subscriber entered at period start (post_entry ~ full), fee was effectively fair, equalization changes nothing. recommendation TRUST_FEE_STRUCTURE/MINOR_EQUALIZATION_GAP/DEMAND_EQUALIZATION_ACCOUNTING/AVOID_NO_EQUALIZATION; grade A-F; aggregate cleanest_vault/worst_equalization_vault/avg_score/net_negative_count/position_count; pure stdlib, atomic ring-buffer log (data/vault_performance_fee_subscription_timing_equalization_gap_log.json, cap 100), no inf/NaN, read-only/advisory | distinct from performance_fee_high_water_mark (temporal HWM-reset of one NAV series), performance_fee_volatility_tax (path-asymmetry of one series over time), performance_fee_crystallization_frequency (how OFTEN), performance_fee_hurdle_rate_gap (fee on beta vs alpha / benchmark hurdle), performance_fee_unrealized_gain_clawback_gap (temporal reversal of one unrealized mark), performance_fee_cross_sleeve_netting_gap (cross-sectional sleeve winners vs losers) -- novel axis: a performance fee charged on the FULL-PERIOD gain for a MID-PERIOD subscriber with NO equalization (pre-entry gains never earned by the subscriber) | registry Tier-B yield_quality weight 0.5 | self-authored sprint: no type=code&status=ready task in KANBAN (backlog=26: agent_infra needing git/launchd/keychain on Mac + P0/P1-FIX/USER ACTION; features=7 P3; ideas=3 LOW), orchestrator chose the topic after a non-overlap scan (no subscription-timing / equalization / series-accounting module exists on the perf-fee axis; six existing perf-fee modules model other axes), added MP-1210 to KANBAN.json done and took it into work; updated KANBAN sprint_completed/sprint_current v8.55->v8.56 + done MP-1210 done_count 904->905, appended sprint_log, created this push script | architect review: last completed before this run was v8.55 (ends in 5 -> review due, BUT spa_core.dev_agents.architect is unavailable in the sandbox: ModuleNotFoundError: anthropic; backlog scanned manually instead -> no type=code&status=ready) | STRICTLY READ-ONLY (SPA-BL-011): risk/execution/monitoring/allocator/cycle_runner.py/golive_checker.py untouched by this sprint"

FILES="/Users/yuriikulieshov/Documents/SPA_Claude/spa_core/analytics/defi_protocol_vault_performance_fee_subscription_timing_equalization_gap_analyzer.py
/Users/yuriikulieshov/Documents/SPA_Claude/spa_core/tests/test_defi_protocol_vault_performance_fee_subscription_timing_equalization_gap_analyzer.py
/Users/yuriikulieshov/Documents/SPA_Claude/data/vault_performance_fee_subscription_timing_equalization_gap_log.json
/Users/yuriikulieshov/Documents/SPA_Claude/spa_core/analytics/_module_registry.py
/Users/yuriikulieshov/Documents/SPA_Claude/KANBAN.json
/Users/yuriikulieshov/Documents/SPA_Claude/sprint_log.md
/Users/yuriikulieshov/Documents/SPA_Claude/scripts/push_v856.sh"

# PAT resolution: Keychain -> env GITHUB_PAT_SPA -> env SPA_GITHUB_PAT -> ~/.github_pat
PAT=$(security find-generic-password -s GITHUB_PAT_SPA -w 2>/dev/null || echo "")
[ -z "$PAT" ] && PAT="${GITHUB_PAT_SPA:-${SPA_GITHUB_PAT:-}}"
[ -z "$PAT" ] && [ -f ~/.github_pat ] && PAT=$(cat ~/.github_pat)
[ -z "$PAT" ] && { echo "PAT not found — run: bash setup_pat.sh"; exit 1; }

cd ~/Documents/SPA_Claude
echo "SPA Push v8.56 — MP-1210 + tests + registry + KANBAN + sprint_log"
python3 push_to_github.py --files $FILES --message "$COMMIT_MSG" --pat "$PAT"
echo "Push v8.56 complete!"
