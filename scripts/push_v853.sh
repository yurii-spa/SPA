#!/bin/bash
# SPA Push v8.53
# MP-1207: DeFiProtocolVaultPerformanceFeeHurdleRateGapAnalyzer  (207 tests)
#
# SECURITY: PAT is read from macOS Keychain (service: GITHUB_PAT_SPA).
# DO NOT embed PAT or any credentials in this file.
#
# Usage: bash ~/Documents/SPA_Claude/scripts/push_v853.sh

set -e

COMMIT_MSG="feat(v8.53): MP-1207 DeFiProtocolVaultPerformanceFeeHurdleRateGapAnalyzer (207 tests) | advisory/read-only yield_quality Tier-B (weight 0.5) | a vault charges performance fee on gross gains WITHOUT a hurdle rate (or with a hurdle BELOW the risk-free/benchmark baseline), so the depositor pays perf fee on BETA — returns earnable passively at the benchmark — as if it were ALPHA; the headline net APR overstates the manager's true value-add because part of the fee is levied on sub-hurdle (beta-level) returns that required no skill. metrics: fee_frac=clamp(fee/100); fee_charged_apr=fee_frac*max(0,gross-hurdle); fair_fee_apr=fee_frac*max(0,gross-benchmark); hurdle_gap_apr=benchmark-hurdle; excess_fee_apr=max(0,fee_charged-fair_fee) (fee leaked onto beta); net_apr_charged/net_apr_fair; gross_alpha_apr=max(0,gross-benchmark); net_alpha_apr=gross_alpha-fee_charged (may be <0); net_alpha_is_negative; alpha_realization_ratio=clamp(net_alpha/gross_alpha,0,1) (gross_alpha==0 -> 1.0 if fee_charged==0 else 0.0); fee_on_beta_fraction=clamp(excess_fee/fee_charged,0,1) scale-free classification basis; overstatement=excess_fee. override path: direct excess_fee_apr_pct (+ positive gross + positive fee_charged) -> verbatim, geometry (hurdle/benchmark/hurdle_gap)->None, GAP_FROM_OVERRIDE flag, geometry-only flags suppressed, alpha_realization_ratio anchored to (1-fee_on_beta_fraction). classification by fee_on_beta_fraction: CLEAN_HURDLE(<=0.05)/MILD_BETA_TAX(<=0.20)/MODERATE_BETA_TAX(<=0.50)/SEVERE_BETA_TAX(>0.50 or net_alpha_is_negative)/INSUFFICIENT_DATA(non-finite/<=0 gross; invalid fee). flags CLEAN_HURDLE_CONFIRMED / NET_ALPHA_NEGATIVE_AFTER_FEE / NO_HURDLE_APPLIED (hurdle==0 and benchmark>0) / FEE_EXCEEDS_ALPHA (fee_charged>gross_alpha) / GAP_FROM_OVERRIDE. score=clamp(70*alpha_realization_ratio + 30*(1-fee_on_beta_fraction),0,100); INSUFFICIENT->0. HIGHER score = hurdle ~ benchmark, fee falls on alpha (paying for skill, not beta). recommendation TRUST_FEE_STRUCTURE/MINOR_HURDLE_GAP/NEGOTIATE_HURDLE/AVOID_NO_HURDLE_FEE; grade A-F; aggregate cleanest_hurdle_vault/worst_beta_tax_vault/avg_score/net_alpha_negative_count/position_count; pure stdlib, atomic ring-buffer log (data/vault_performance_fee_hurdle_rate_gap_log.json, cap 100), no inf/NaN, read-only/advisory | distinct from performance_fee_high_water_mark (HWM-reset mechanics; here orthogonal HURDLE/benchmark axis), performance_fee_volatility_tax (path-asymmetry of HWM fee on volatile gross path; here single first-moment benchmark-hurdle gap), performance_fee_crystallization_frequency (how OFTEN fee crystallises; here what BASE it applies to), risk_adjusted_yield_hurdle (whether the YIELD clears a risk-premium hurdle for tail loss; here whether the FEE respects a benchmark hurdle), headline_yield_honesty_composite (bottom-up roll-up; this is one feeding mechanism) | registry Tier-B B=457->458, total 649->650 | self-authored sprint: no type=code&status=ready task in KANBAN (backlog=26: agent_infra needing git/launchd/keychain on Mac + P0/P1-FIX/USER ACTION; features=7 P3; ideas=3 LOW), orchestrator chose the topic after non-overlap check vs the three existing perf-fee modules + risk_adjusted_yield_hurdle, added MP-1207 to KANBAN.json done and took it into work; updated KANBAN sprint_completed/sprint_current v8.52->v8.53 + done MP-1207 done_count 901->902, appended sprint_log, created this push script | architect review: last completed before this was v8.52 (not ending in 0/5) -> no separate review due; spa_core.dev_agents.architect unavailable in sandbox anyway (ModuleNotFoundError: anthropic) | STRICTLY READ-ONLY (SPA-BL-011): risk/execution/monitoring/allocator/cycle_runner.py/golive_checker.py untouched"

FILES="/Users/yuriikulieshov/Documents/SPA_Claude/spa_core/analytics/defi_protocol_vault_performance_fee_hurdle_rate_gap_analyzer.py
/Users/yuriikulieshov/Documents/SPA_Claude/spa_core/tests/test_defi_protocol_vault_performance_fee_hurdle_rate_gap_analyzer.py
/Users/yuriikulieshov/Documents/SPA_Claude/data/vault_performance_fee_hurdle_rate_gap_log.json
/Users/yuriikulieshov/Documents/SPA_Claude/spa_core/analytics/_module_registry.py
/Users/yuriikulieshov/Documents/SPA_Claude/KANBAN.json
/Users/yuriikulieshov/Documents/SPA_Claude/sprint_log.md
/Users/yuriikulieshov/Documents/SPA_Claude/.gitignore
/Users/yuriikulieshov/Documents/SPA_Claude/scripts/push_v853.sh"

# PAT resolution: Keychain -> env GITHUB_PAT_SPA -> env SPA_GITHUB_PAT -> ~/.github_pat
PAT=$(security find-generic-password -s GITHUB_PAT_SPA -w 2>/dev/null || echo "")
[ -z "$PAT" ] && PAT="${GITHUB_PAT_SPA:-${SPA_GITHUB_PAT:-}}"
[ -z "$PAT" ] && [ -f ~/.github_pat ] && PAT=$(cat ~/.github_pat)
[ -z "$PAT" ] && { echo "PAT not found — run: bash setup_pat.sh"; exit 1; }

cd ~/Documents/SPA_Claude
echo "SPA Push v8.53 — MP-1207 + tests + registry + KANBAN + sprint_log"
python3 push_to_github.py --files $FILES --message "$COMMIT_MSG" --pat "$PAT"
echo "Push v8.53 complete!"
