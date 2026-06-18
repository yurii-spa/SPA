#!/bin/bash
# SPA Push v8.44
# MP-1198: DeFiProtocolVaultRangeUptimeFeeRealizationAnalyzer  (110 tests)
#
# SECURITY: PAT is read from macOS Keychain (service: GITHUB_PAT_SPA).
# DO NOT embed PAT or any credentials in this file.
#
# Usage: bash ~/Documents/SPA_Claude/scripts/push_v844.sh

set -e

COMMIT_MSG="feat(v8.44): MP-1198 DeFiProtocolVaultRangeUptimeFeeRealizationAnalyzer (110 tests) | advisory/read-only yield_quality Tier-B (weight 0.5) | A concentrated-liquidity (CLMM, Uniswap-v3-style) LP vault advertises a fee APR computed AS IF the position were IN-RANGE collecting fees 100% of the time, but a concentrated position only earns fees while price sits inside its tick band; out-of-range intervals earn ZERO trading fees (liquidity inactive, sitting in one asset). Over a finite horizon realised fee APR = headline * time_in_range_fraction. Narrower bands quote a higher in-range rate but spend more time out of range (lower uptime), so the boosted headline overstates the time-averaged realised fee yield. This module audits headline honesty from observed range-status samples and reports the fee-uptime drag. HIGHER score = high in-range uptime (realised ~ headline). | metrics: realized_fee_apr_pct = headline*uptime, fee_uptime_drag_pct = headline - realised, time_in_range_fraction / out_of_range_fraction, realization_ratio (= uptime), longest_out_of_range_streak, range_flips (in<->out transitions), churn_ratio = flips/(n-1), sample_count, uptime_from_samples, currently_out_of_range; input range_status_samples (per-interval bool / 0-1 / strings in/out/active/inactive; non-interpretable elements skipped) or a direct time_in_range_fraction override (used only when samples < MIN_SAMPLES); classification on out_of_range_fraction (scale-free) FULL_UPTIME(<=0.02)/MINOR_DRIFT(<=0.10)/MODERATE_DRIFT(<=0.30)/SEVERE_DRIFT(>0.30), + INSUFFICIENT_DATA (<2 valid samples and no valid override, or non-finite/non-positive headline); flags CURRENTLY_OUT_OF_RANGE / PERSISTENTLY_OUT_OF_RANGE (longest streak >= ceil(0.5*n)) / NARROW_BAND_LOW_UPTIME (uptime <= 0.5) / FREQUENT_REBALANCE_CHURN (churn >= 0.40) / UPTIME_FROM_OVERRIDE; score = clamp(80*uptime + 20*clamp(1-churn,0,1), 0,100) | distinct from deployment_ramp_drag (a ONE-TIME entry warm-up: idle then PERMANENTLY productive; here inactivity is RECURRING and price/band-driven), yield_variance_drag (dispersion of positive yield -> geom<arith; here out-of-range earns EXACTLY ZERO, a binary availability not a second moment), concentrated_liquidity / concentrated_liquidity_range_optimizer (PRESCRIPTIVE band choice; here DESCRIPTIVE honesty: realised = headline * OBSERVED uptime), impermanent_loss_* (divergence/IL on the position VALUE; here a FEE-INCOME shortfall from inactive liquidity, orthogonal to IL), utilization_peak_headline_revert (mean-revert lending UTILIZATION; here a binary in/out-of-range availability for LP fees) | non-interpretable samples filtered before stats | pure stdlib, atomic ring-buffer log, no inf/NaN, read-only/advisory | registry Tier-B B=448->449, total 640->641 | KANBAN sprint_completed/sprint_current v8.43->v8.44, done MP-1198, done_count 893->894 | architect review: last completed before this run was v8.43 (minor 43, not a multiple of 5) so no review required; spa_core.dev_agents.architect unreachable in sandbox anyway (ModuleNotFoundError: anthropic), backlog scanned programmatically (no ready type=code tasks) | STRICTLY READ-ONLY (SPA-BL-011): risk/execution/monitoring/allocator/cycle_runner.py/golive_checker.py untouched"

FILES="/Users/yuriikulieshov/Documents/SPA_Claude/spa_core/analytics/defi_protocol_vault_range_uptime_fee_realization_analyzer.py
/Users/yuriikulieshov/Documents/SPA_Claude/spa_core/tests/test_defi_protocol_vault_range_uptime_fee_realization_analyzer.py
/Users/yuriikulieshov/Documents/SPA_Claude/data/vault_range_uptime_fee_realization_log.json
/Users/yuriikulieshov/Documents/SPA_Claude/spa_core/analytics/_module_registry.py
/Users/yuriikulieshov/Documents/SPA_Claude/KANBAN.json
/Users/yuriikulieshov/Documents/SPA_Claude/sprint_log.md
/Users/yuriikulieshov/Documents/SPA_Claude/scripts/push_v844.sh"

# PAT resolution: Keychain -> env GITHUB_PAT_SPA -> env SPA_GITHUB_PAT -> ~/.github_pat
PAT=$(security find-generic-password -s GITHUB_PAT_SPA -w 2>/dev/null || echo "")
[ -z "$PAT" ] && PAT="${GITHUB_PAT_SPA:-${SPA_GITHUB_PAT:-}}"
[ -z "$PAT" ] && [ -f ~/.github_pat ] && PAT=$(cat ~/.github_pat)
[ -z "$PAT" ] && { echo "PAT not found — run: bash setup_pat.sh"; exit 1; }

cd ~/Documents/SPA_Claude
echo "SPA Push v8.44 — MP-1198 + tests + registry + KANBAN + sprint_log"
python3 push_to_github.py --files $FILES --message "$COMMIT_MSG" --pat "$PAT"
echo "Push v8.44 complete!"
