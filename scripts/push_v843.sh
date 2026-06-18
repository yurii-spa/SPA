#!/bin/bash
# SPA Push v8.43
# MP-1197: DeFiProtocolVaultYieldVarianceDragRealizationAnalyzer  (178 tests)
#
# SECURITY: PAT is read from macOS Keychain (service: GITHUB_PAT_SPA).
# DO NOT embed PAT or any credentials in this file.
#
# Usage: bash ~/Documents/SPA_Claude/scripts/push_v843.sh

set -e

COMMIT_MSG="feat(v8.43): MP-1197 DeFiProtocolVaultYieldVarianceDragRealizationAnalyzer (178 tests) | advisory/read-only yield_quality Tier-B (weight 0.5) | A vault HEADLINE APR is almost always the ARITHMETIC mean of its per-period yields annualised, but a compounding holder realises the GEOMETRIC mean, which by AM-GM (Jensen) is always <= the arithmetic mean once the per-period yields are VOLATILE. The gap is the VARIANCE DRAG (volatility drag): a structural, fee-free, downtime-free shortfall that grows with the dispersion of the yield stream. A volatile yield therefore realises materially less than its arithmetic-mean headline even when the average is perfectly honest. This module compares the arithmetic-mean reference vs the geometric-mean (realisable) annualised return and reports the variance drag from the sample dispersion. HIGHER score = smooth yield (geometric ~ arithmetic, small drag) -> headline realisable. | metrics: arithmetic_apr_pct = mean(samples)*ppy, geometric_apr_pct = per-period geomean*ppy (realisable), variance_drag_pct = arith - geom, drag_fraction = 1 - geom/arith (scale-free in ppy; classification basis), realization_ratio, headline_vs_arith_gap_pct, period_mean_pct, period_volatility_pct (pstdev), coefficient_of_variation, periods_per_year (default 365), sample_count; geomean via sum-of-logs (safer than running product); flags CAPITAL_WIPEOUT_PERIOD (any (1+s/100)<=0 -> total loss, geom=-100%) / HIGH_VOLATILITY (CV>=1) / HEADLINE_ABOVE_ARITHMETIC (headline>=1.05x arith) / SMOOTH_YIELD; classification on drag_fraction NEGLIGIBLE(<=0.02)/MINOR(<=0.08)/MODERATE(<=0.20)/SEVERE(>0.20), wipeout->SEVERE, + INSUFFICIENT_DATA (<2 valid samples or non-finite/non-positive headline); score = clamp(70*clamp(1-drag_fraction,0,1) + 30*clamp(1-CV,0,1), 0,100) | distinct from trading_fee_apr_volatility (measures the VOLATILITY of a fee-APR itself; here we convert dispersion into the SPECIFIC geometric-vs-arithmetic shortfall a compounding holder eats), apy_volatility_forecaster (forecasts volatility, not realised gap), headline_spot_snapshot_vs_twap (a LEVEL question - spot vs TWAP, first moment; here a SECOND-moment effect: even a representative average loses to its own volatility when compounded), funding_rate_carry_persistence (SIGN frequency of a signed carry), deployment_ramp_drag (TIME-availability linear scaling; here every period earns but dispersion drags the geometric mean down) | non-finite samples filtered before stats | pure stdlib, atomic ring-buffer log, no inf/NaN, read-only/advisory | registry Tier-B B=447->448, total 639->640 | KANBAN sprint_completed/sprint_current v8.42->v8.43, done MP-1197, done_count 892->893 | architect review: last completed before this run was v8.42 (minor 42, not a multiple of 5) so no review required; spa_core.dev_agents.architect unreachable in sandbox anyway (ModuleNotFoundError: anthropic), backlog scanned programmatically (no ready type=code tasks) | STRICTLY READ-ONLY (SPA-BL-011): risk/execution/monitoring/allocator/cycle_runner.py/golive_checker.py untouched"

FILES="/Users/yuriikulieshov/Documents/SPA_Claude/spa_core/analytics/defi_protocol_vault_yield_variance_drag_realization_analyzer.py
/Users/yuriikulieshov/Documents/SPA_Claude/spa_core/tests/test_defi_protocol_vault_yield_variance_drag_realization_analyzer.py
/Users/yuriikulieshov/Documents/SPA_Claude/data/vault_yield_variance_drag_realization_log.json
/Users/yuriikulieshov/Documents/SPA_Claude/spa_core/analytics/_module_registry.py
/Users/yuriikulieshov/Documents/SPA_Claude/KANBAN.json
/Users/yuriikulieshov/Documents/SPA_Claude/sprint_log.md
/Users/yuriikulieshov/Documents/SPA_Claude/scripts/push_v843.sh"

# PAT resolution: Keychain -> env GITHUB_PAT_SPA -> env SPA_GITHUB_PAT -> ~/.github_pat
PAT=$(security find-generic-password -s GITHUB_PAT_SPA -w 2>/dev/null || echo "")
[ -z "$PAT" ] && PAT="${GITHUB_PAT_SPA:-${SPA_GITHUB_PAT:-}}"
[ -z "$PAT" ] && [ -f ~/.github_pat ] && PAT=$(cat ~/.github_pat)
[ -z "$PAT" ] && { echo "PAT not found — run: bash setup_pat.sh"; exit 1; }

cd ~/Documents/SPA_Claude
echo "SPA Push v8.43 — MP-1197 + tests + registry + KANBAN + sprint_log"
python3 push_to_github.py --files $FILES --message "$COMMIT_MSG" --pat "$PAT"
echo "Push v8.43 complete!"
