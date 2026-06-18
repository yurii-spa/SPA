#!/bin/bash
# SPA Push v8.54
# MP-1208: DeFiProtocolVaultPerformanceFeeUnrealizedGainClawbackGapAnalyzer  (220 tests)
#
# SECURITY: PAT is read from macOS Keychain (service: GITHUB_PAT_SPA).
# DO NOT embed PAT or any credentials in this file.
#
# Usage: bash ~/Documents/SPA_Claude/scripts/push_v854.sh

set -e

COMMIT_MSG="feat(v8.54): MP-1208 DeFiProtocolVaultPerformanceFeeUnrealizedGainClawbackGapAnalyzer (220 tests) | advisory/read-only yield_quality Tier-B (weight 0.5) | a vault crystallizes a PERFORMANCE fee on UNREALIZED (paper / mark-to-market) peak gains but provides NO clawback when those gains later reverse, so the depositor paid a fee on profit that evaporated and the net realized return is overstated by the fee charged on the un-recovered (reverted) portion of the gain. metrics: fee_frac=clamp(fee/100); reverted_gain_pct=max(0,peak-realized); fee_paid_on_peak_pct=fee_frac*max(0,peak); fair_fee_pct=fee_frac*max(0,realized); clawback_gap_pct=max(0,fee_paid_on_peak-fair_fee) (fee levied on vanished gains, never clawed back); net_realized_pct=realized-fee_paid_on_peak; net_realized_fair_pct=realized-fair_fee; overstatement_pct=clawback_gap; net_is_negative; fee_on_reverted_fraction=clamp(clawback_gap/fee_paid_on_peak,0,1) scale-free classification basis; realization_ratio with net_fair<=0 edge mirroring the hurdle template gross_alpha==0 defensive pattern. inputs: peak_unrealized_gain_pct (REQUIRED finite>0 else INSUFFICIENT_DATA), realized_gain_pct (signed, may be <peak or <0), performance_fee_pct (coerced 0..100), optional crystallizations. override path: direct clawback_gap_pct verbatim (+ positive peak & fee_paid_on_peak) -> geometry (reverted/realized/fair)->None, GAP_FROM_OVERRIDE flag, geometry-only flags suppressed, realization_ratio anchored to (1-fee_on_reverted_fraction). classification by fee_on_reverted_fraction: CLEAN_PERSISTENT_GAIN(<=0.05)/MILD_CLAWBACK_GAP(<=0.20)/MODERATE_CLAWBACK_GAP(<=0.50)/SEVERE_CLAWBACK_GAP(>0.50 or net_is_negative)/INSUFFICIENT_DATA. flags CLEAN_NO_REVERSAL / NET_NEGATIVE_AFTER_FEE / FEE_ON_VANISHED_GAINS (reverted>0) / FULL_REVERSAL (realized<=0 and peak>0) / MULTIPLE_CRYSTALLIZATIONS (crystallizations>=2) / GAP_FROM_OVERRIDE. score=clamp(70*realization_ratio + 30*(1-fee_on_reverted_fraction),0,100); INSUFFICIENT->0. HIGHER score = gains persisted (realized ~ peak), fee was effectively fair, no clawback needed. recommendation TRUST_FEE_STRUCTURE/MINOR_CLAWBACK_GAP/DEMAND_CLAWBACK_PROVISION/AVOID_NO_CLAWBACK; grade A-F; aggregate cleanest_vault/worst_clawback_vault/avg_score/net_negative_count/position_count; pure stdlib, atomic ring-buffer log (data/vault_performance_fee_unrealized_gain_clawback_gap_log.json, cap 100), no inf/NaN, read-only/advisory | distinct from performance_fee_high_water_mark (HWM-reset mechanics), performance_fee_volatility_tax (path-asymmetry of HWM fee on volatile gross path), performance_fee_crystallization_frequency (how OFTEN fee crystallises), performance_fee_hurdle_rate_gap (fee on beta vs alpha / benchmark hurdle), real_yield_vs_paper_yield (real fee/interest vs token-price paper yield) -- novel axis: fee on unrealized peak gains that later reversed without clawback | registry Tier-B B=458->459, total 650->651 | self-authored sprint: no type=code&status=ready task in KANBAN (backlog=26: agent_infra needing git/launchd/keychain on Mac + P0/P1-FIX/USER ACTION; features=7 P3; ideas=3 LOW), orchestrator chose the topic after a non-overlap grep (no clawback/unrealized/mark_to_market/provisional module exists; four existing perf-fee modules model other axes), added MP-1208 to KANBAN.json done and took it into work; updated KANBAN sprint_completed/sprint_current v8.53->v8.54 + done MP-1208 done_count 902->903, appended sprint_log, created this push script | architect review: last completed before this was v8.53 (not ending in 0/5) -> no separate review due; spa_core.dev_agents.architect unavailable in sandbox anyway (ModuleNotFoundError: anthropic) | STRICTLY READ-ONLY (SPA-BL-011): risk/execution/monitoring/allocator/cycle_runner.py/golive_checker.py untouched"

FILES="/Users/yuriikulieshov/Documents/SPA_Claude/spa_core/analytics/defi_protocol_vault_performance_fee_unrealized_gain_clawback_gap_analyzer.py
/Users/yuriikulieshov/Documents/SPA_Claude/spa_core/tests/test_defi_protocol_vault_performance_fee_unrealized_gain_clawback_gap_analyzer.py
/Users/yuriikulieshov/Documents/SPA_Claude/data/vault_performance_fee_unrealized_gain_clawback_gap_log.json
/Users/yuriikulieshov/Documents/SPA_Claude/spa_core/analytics/_module_registry.py
/Users/yuriikulieshov/Documents/SPA_Claude/KANBAN.json
/Users/yuriikulieshov/Documents/SPA_Claude/sprint_log.md
/Users/yuriikulieshov/Documents/SPA_Claude/.gitignore
/Users/yuriikulieshov/Documents/SPA_Claude/scripts/push_v854.sh"

# PAT resolution: Keychain -> env GITHUB_PAT_SPA -> env SPA_GITHUB_PAT -> ~/.github_pat
PAT=$(security find-generic-password -s GITHUB_PAT_SPA -w 2>/dev/null || echo "")
[ -z "$PAT" ] && PAT="${GITHUB_PAT_SPA:-${SPA_GITHUB_PAT:-}}"
[ -z "$PAT" ] && [ -f ~/.github_pat ] && PAT=$(cat ~/.github_pat)
[ -z "$PAT" ] && { echo "PAT not found — run: bash setup_pat.sh"; exit 1; }

cd ~/Documents/SPA_Claude
echo "SPA Push v8.54 — MP-1208 + tests + registry + KANBAN + sprint_log"
python3 push_to_github.py --files $FILES --message "$COMMIT_MSG" --pat "$PAT"
echo "Push v8.54 complete!"
