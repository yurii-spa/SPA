#!/bin/bash
# SPA Push v8.48 (reconcile)
# MP-1202: DeFiProtocolVaultDollarWeightedReturnGapAnalyzer  (160 tests)
#
# SECURITY: PAT is read from macOS Keychain (service: GITHUB_PAT_SPA).
# DO NOT embed PAT or any credentials in this file.
#
# Usage: bash ~/Documents/SPA_Claude/scripts/push_v848.sh

set -e

COMMIT_MSG="feat(v8.48): MP-1202 DeFiProtocolVaultDollarWeightedReturnGapAnalyzer (160 tests) | advisory/read-only yield_quality Tier-B (weight 0.5) | A vault advertises a headline trailing APY that is a TIME-WEIGHTED return (TWR): it geometrically links the per-period returns and is INDEPENDENT of depositor cash-flow timing (twr_period_geom_mean = prod(1+r_i/100)^(1/n)-1; twr_apr = ((1+gm)^ppy-1)*100). But the return the AVERAGE DEPOSITOR earns is the DOLLAR-WEIGHTED (money-weighted) return (DWR/MWR), which weights each period's return by the CAPITAL actually invested then: simulate the balance path (apply r_i to the beginning balance, add end-of-period external flow); dwr_period = sum(capital_i*r_i)/sum(capital_i); dwr_apr = dwr_period*ppy. When large inflows arrive right before low-return periods (capital chases a hot streak that mean-reverts) or capital leaves before high-return periods, the realised dollar-weighted return diverges BELOW the advertised TWR: behavior_gap = twr_apr - dwr_apr (positive = depositors earned LESS) — the classic investor-return/behavior gap (Morningstar investor returns vs fund returns) applied to a DeFi vault. HIGHER score = dwr ~ twr (flow timing neutral/aligned -> depositors realise the headline); LOWER score = large positive behavior gap (adverse flow timing -> realised far below headline). | metrics: twr_apr_pct, dollar_weighted_apr_pct, gap_baseline_apr_pct, behavior_gap_pct (= twr-dwr), realization_ratio (= dwr/twr, clamp), gap_fraction (scale-free in [0,1], classification basis), twr_period_pct, dwr_period_pct, total_net_flow, peak_capital, mean_capital, flow_volatility, coefficient_of_variation, periods_per_year (default 365), sample_count, used_samples, used_override; input return_samples (per-period %, newest last) + flow_samples / initial_capital (end-of-period external flows), OR direct overrides twr_apr_pct + dollar_weighted_apr_pct (MIN_SAMPLES=2); classification on gap_fraction ALIGNED(<=0.05)/MILD_GAP(<=0.20)/MODERATE_GAP(<=0.50)/SEVERE_GAP(>0.50), + INSUFFICIENT_DATA; flags ALIGNED_TIMING / LATE_LARGE_INFLOW / FLOWS_DOMINATE / STABLE_FLOWS / GAP_FROM_OVERRIDE; recommendation TRUST_HEADLINE / DISCOUNT_* / AVOID_OR_VERIFY; grade A-F | distinct from time_weighted_return_calculator (MP-718, Tier-C: merely COMPUTES a TWR to strip out flow timing; here we COMPARE TWR vs DWR and quantify the gap FROM flow timing - opposite question), deployment_ramp_drag (vault's own idle/undeployed capital ramp; here depositor-cohort cashflow timing), marginal_deposit_apr_dilution (new deposits diluting a fixed emission - a rate MECHANISM; here the rate path is given and we measure how flow TIMING diverges DWR from TWR), price_return_contamination (MP-1199: recurring-yield vs price-return first-moment split; here a TWR-vs-DWR cashflow-timing gap), yield_variance_drag (dispersion -> geom<arith second-moment penalty on one capital base; here the gap arises from CAPITAL WEIGHTING across periods) | pure stdlib, atomic ring-buffer log, no inf/NaN, read-only/advisory | registry Tier-B B=452->453, total 644->645 | RECONCILE: module+test+registry were created by a prior run but KANBAN/sprint_log/push were left un-updated; this run verified (160 tests, compile OK, forbidden-import CLEAN, CLI --run exit0 all-finite) and completed KANBAN sprint_completed/sprint_current v8.47->v8.48, done MP-1202, done_count 897->898, appended sprint_log, created this push script (no new sprint, to avoid a duplicate) | architect review: last completed before reconcile was v8.47 (minor 47, not a multiple of 5, not ending 0/5) so no review was due; spa_core.dev_agents.architect is in any case unreachable in sandbox (ModuleNotFoundError: anthropic) | STRICTLY READ-ONLY (SPA-BL-011): risk/execution/monitoring/allocator/cycle_runner.py/golive_checker.py untouched"

FILES="/Users/yuriikulieshov/Documents/SPA_Claude/spa_core/analytics/defi_protocol_vault_dollar_weighted_return_gap_analyzer.py
/Users/yuriikulieshov/Documents/SPA_Claude/spa_core/tests/test_defi_protocol_vault_dollar_weighted_return_gap_analyzer.py
/Users/yuriikulieshov/Documents/SPA_Claude/data/vault_dollar_weighted_return_gap_log.json
/Users/yuriikulieshov/Documents/SPA_Claude/spa_core/analytics/_module_registry.py
/Users/yuriikulieshov/Documents/SPA_Claude/KANBAN.json
/Users/yuriikulieshov/Documents/SPA_Claude/sprint_log.md
/Users/yuriikulieshov/Documents/SPA_Claude/scripts/push_v848.sh"

# PAT resolution: Keychain -> env GITHUB_PAT_SPA -> env SPA_GITHUB_PAT -> ~/.github_pat
PAT=$(security find-generic-password -s GITHUB_PAT_SPA -w 2>/dev/null || echo "")
[ -z "$PAT" ] && PAT="${GITHUB_PAT_SPA:-${SPA_GITHUB_PAT:-}}"
[ -z "$PAT" ] && [ -f ~/.github_pat ] && PAT=$(cat ~/.github_pat)
[ -z "$PAT" ] && { echo "PAT not found — run: bash setup_pat.sh"; exit 1; }

cd ~/Documents/SPA_Claude
echo "SPA Push v8.48 — MP-1202 + tests + registry + KANBAN + sprint_log"
python3 push_to_github.py --files $FILES --message "$COMMIT_MSG" --pat "$PAT"
echo "Push v8.48 complete!"
