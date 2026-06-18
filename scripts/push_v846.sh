#!/bin/bash
# SPA Push v8.46
# MP-1200: DeFiProtocolVaultHarvestYieldConcentrationAnalyzer  (186 tests)
#
# SECURITY: PAT is read from macOS Keychain (service: GITHUB_PAT_SPA).
# DO NOT embed PAT or any credentials in this file.
#
# Usage: bash ~/Documents/SPA_Claude/scripts/push_v846.sh

set -e

COMMIT_MSG="feat(v8.46): MP-1200 DeFiProtocolVaultHarvestYieldConcentrationAnalyzer (186 tests) | advisory/read-only yield_quality Tier-B (weight 0.5) | A vault's headline trailing APR annualises the SUM of yield collected over a window, but that total is frequently DOMINATED by a few large NON-REPEATABLE harvest events (a one-off airdrop, a single fat bribe epoch, a liquidation windfall, a retro bonus). When the trailing total is concentrated into a handful of lumps, the implied forward RUN-RATE is overstated: those lumps will not recur at the same cadence, so a depositor arriving after them earns far less than the annualised headline implies. This module measures the TEMPORAL distribution of per-harvest yield contributions and estimates a deconcentrated, repeatable run-rate by anchoring on the TYPICAL (median) harvest instead of the windfall-inflated mean: realization_ratio = clamp(median(harvest)*n/sum(harvest), 0,1); recurring_apr = headline*realization_ratio; overstatement = headline - recurring. HIGHER score = yield spread evenly across many recurring harvests (typical ~ average -> headline is a repeatable run-rate); LOWER score = a windfall lump inflating the annualised headline. | metrics: recurring_apr_pct, realization_ratio, overstatement_pct, concentration_index (Herfindahl-normalised (hhi-1/n)/(1-1/n) in [0,1], scale-free classification basis), hhi (sum of squared shares), effective_harvests (1/hhi N_eff), top_event_share / top3_event_share, gini, windfall_count / windfall_share (harvest > windfall_multiple*typical; default x4.0, base=median fallback mean), coefficient_of_variation (pstdev/mean), harvest_total, median_harvest, sample_count; input harvest_yield_samples (per-harvest magnitudes, newest last; negative/non-finite skipped; bool rejected; MIN_SAMPLES=2) OR direct recurring_apr_pct override (<2 samples; concentration_index = 1-realization_ratio, sample metrics None); classification on concentration_index DIVERSE_RECURRING(<=0.10)/MILDLY_LUMPY(<=0.30)/CONCENTRATED(<=0.60)/WINDFALL_DOMINATED(>0.60), + INSUFFICIENT_DATA (non-finite/<=0 headline, <2 valid samples & no override, all-zero harvests, negative/NaN override); flags SINGLE_EVENT_DOMINATED (top_event_share>=0.5) / WINDFALL_PRESENT (windfall_count>=1) / HIGH_DISPERSION (CV>=1.0) / FEW_HARVESTS (n<4) / SMOOTH_RECURRING / RUN_RATE_FROM_OVERRIDE; score = clamp(70*realization_ratio + 30*(1-concentration_index), 0,100) | distinct from yield_variance_drag (geom<arith second-moment compounding penalty from dispersion of per-period RETURNS; here CONCENTRATION of the trailing SUM into a few events -> repeatability/run-rate, not a compounding penalty), relative_yield_outlier (outlier ACROSS PEERS; here concentration WITHIN one vault's harvest series over TIME), yield_source_concentration_risk / strategy_diversification_scorer (concentration across yield SOURCES; here across harvest EVENTS in time), harvest_cycle_entry_timing / pending_harvest_premium (TIMING of capturing an accrued harvest; here repeatable stream vs one-off lump), price_return_contamination (subtracts a PRICE component from NAV growth; here every harvest is yield, the issue is a lumpy non-repeatable trailing total) | pure stdlib, atomic ring-buffer log, no inf/NaN, read-only/advisory | registry Tier-B B=450->451, total 642->643 | KANBAN sprint_completed/sprint_current v8.45->v8.46, done MP-1200, done_count 895->896 | architect review: last completed before this run was v8.45 (minor 45, multiple of 5) so a review was due, but spa_core.dev_agents.architect is unreachable in sandbox (ModuleNotFoundError: anthropic) so it was skipped with a note as in prior runs; backlog scanned programmatically (no ready type=code tasks) | STRICTLY READ-ONLY (SPA-BL-011): risk/execution/monitoring/allocator/cycle_runner.py/golive_checker.py untouched"

FILES="/Users/yuriikulieshov/Documents/SPA_Claude/spa_core/analytics/defi_protocol_vault_harvest_yield_concentration_analyzer.py
/Users/yuriikulieshov/Documents/SPA_Claude/spa_core/tests/test_defi_protocol_vault_harvest_yield_concentration_analyzer.py
/Users/yuriikulieshov/Documents/SPA_Claude/data/vault_harvest_yield_concentration_log.json
/Users/yuriikulieshov/Documents/SPA_Claude/spa_core/analytics/_module_registry.py
/Users/yuriikulieshov/Documents/SPA_Claude/KANBAN.json
/Users/yuriikulieshov/Documents/SPA_Claude/sprint_log.md
/Users/yuriikulieshov/Documents/SPA_Claude/scripts/push_v846.sh"

# PAT resolution: Keychain -> env GITHUB_PAT_SPA -> env SPA_GITHUB_PAT -> ~/.github_pat
PAT=$(security find-generic-password -s GITHUB_PAT_SPA -w 2>/dev/null || echo "")
[ -z "$PAT" ] && PAT="${GITHUB_PAT_SPA:-${SPA_GITHUB_PAT:-}}"
[ -z "$PAT" ] && [ -f ~/.github_pat ] && PAT=$(cat ~/.github_pat)
[ -z "$PAT" ] && { echo "PAT not found — run: bash setup_pat.sh"; exit 1; }

cd ~/Documents/SPA_Claude
echo "SPA Push v8.46 — MP-1200 + tests + registry + KANBAN + sprint_log"
python3 push_to_github.py --files $FILES --message "$COMMIT_MSG" --pat "$PAT"
echo "Push v8.46 complete!"
