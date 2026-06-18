#!/bin/bash
# SPA Push v8.49
# MP-1203: DeFiProtocolVaultPerformanceFeeVolatilityTaxAnalyzer  (173 tests)
#
# SECURITY: PAT is read from macOS Keychain (service: GITHUB_PAT_SPA).
# DO NOT embed PAT or any credentials in this file.
#
# Usage: bash ~/Documents/SPA_Claude/scripts/push_v849.sh

set -e

COMMIT_MSG="feat(v8.49): MP-1203 DeFiProtocolVaultPerformanceFeeVolatilityTaxAnalyzer (173 tests) | advisory/read-only yield_quality Tier-B (weight 0.5) | A vault charges a performance fee (perf_fee_pct) on profits over a HIGH-WATER MARK (HWM): the fee is taken on up-periods that make a new NAV high but is NOT rebated on drawdowns — it is ASYMMETRIC. So a volatile gross-return path realises a LOWER net-of-perf-fee return than a smooth path with the same gross APR (the performance-fee 'volatility tax' / fee asymmetry drag). The headline net APR usually assumes the smooth path (fee charged once on gross APR). Realised net is lower because the path's volatility interacts with the asymmetric over-HWM fee. Simulate the net-NAV path period by period (apply gross r_i to NAV; if new NAV > HWM, skim perf_fee_pct%% of the gain above HWM and reset HWM; else no fee), geom-mean the net per-period returns and annualise. metrics: gross_apr_pct, smooth_net_apr_pct (= gross*(1-fee/100) when gross>0), realised_net_apr_pct (HWM net-path sim), volatility_tax_pct (= smooth_net - realised_net; positive = asymmetry erodes yield), fee_drag_total_pct (= gross - realised_net), realisation_ratio (= clamp(realised_net/smooth_net,0,1)), gross_return_vol_pct (pstdev of per-period gross), crystallization_count (up-periods where fee skimmed). Override path for <MIN_SAMPLES(=2) samples uses heuristic tax ~ perf_fee_frac*0.5*(vol/100)^2*ppy*100 bounded [0,smooth_net]. HIGHER score = realised_net ~ smooth_net (low vol / neutral asymmetry -> depositor realises the headline net); LOWER score = large volatility tax (high vol x high perf_fee -> realised far below headline). flags HIGH_VOLATILITY_TAX / HIGH_PERF_FEE / HIGH_GROSS_VOL / NEGATIVE_GROSS / INSUFFICIENT_DATA; pure stdlib, atomic ring-buffer log (data/vault_performance_fee_volatility_tax_log.json, cap 100), no inf/NaN, read-only/advisory | distinct from performance_fee_high_water_mark (snapshot above/below HWM state; here a path-dependent volatility-tax over the whole return path), performance_fee_crystallization_frequency (timing/cadence of fee crystallisation; here the magnitude of the asymmetric drag from path volatility), vault_yield_variance_drag (geom-vs-arith compounding penalty on a GROSS base with no fee; here the penalty comes from the ASYMMETRIC over-HWM perf fee and vanishes at perf_fee=0), vault_management_fee_accrual (linear management fee; here a non-linear perf fee with HWM) | registry Tier-B B=453->454, total 645->646 | self-authored sprint: no type=code&status=ready task in KANBAN, orchestrator chose the topic, added MP-1203 to KANBAN.json and took it into work; updated KANBAN sprint_completed/sprint_current v8.48->v8.49 + done MP-1203, appended sprint_log, created this push script | architect review: last completed before this was v8.48 (minor 48, not ending 0/5) so no review was due | STRICTLY READ-ONLY (SPA-BL-011): risk/execution/monitoring/allocator/cycle_runner.py/golive_checker.py untouched"

FILES="/Users/yuriikulieshov/Documents/SPA_Claude/spa_core/analytics/defi_protocol_vault_performance_fee_volatility_tax_analyzer.py
/Users/yuriikulieshov/Documents/SPA_Claude/spa_core/tests/test_defi_protocol_vault_performance_fee_volatility_tax_analyzer.py
/Users/yuriikulieshov/Documents/SPA_Claude/data/vault_performance_fee_volatility_tax_log.json
/Users/yuriikulieshov/Documents/SPA_Claude/spa_core/analytics/_module_registry.py
/Users/yuriikulieshov/Documents/SPA_Claude/KANBAN.json
/Users/yuriikulieshov/Documents/SPA_Claude/sprint_log.md
/Users/yuriikulieshov/Documents/SPA_Claude/scripts/push_v849.sh"

# PAT resolution: Keychain -> env GITHUB_PAT_SPA -> env SPA_GITHUB_PAT -> ~/.github_pat
PAT=$(security find-generic-password -s GITHUB_PAT_SPA -w 2>/dev/null || echo "")
[ -z "$PAT" ] && PAT="${GITHUB_PAT_SPA:-${SPA_GITHUB_PAT:-}}"
[ -z "$PAT" ] && [ -f ~/.github_pat ] && PAT=$(cat ~/.github_pat)
[ -z "$PAT" ] && { echo "PAT not found — run: bash setup_pat.sh"; exit 1; }

cd ~/Documents/SPA_Claude
echo "SPA Push v8.49 — MP-1203 + tests + registry + KANBAN + sprint_log"
python3 push_to_github.py --files $FILES --message "$COMMIT_MSG" --pat "$PAT"
echo "Push v8.49 complete!"
