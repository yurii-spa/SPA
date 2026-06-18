#!/bin/bash
# SPA Push v8.41
# MP-1195: DeFiProtocolVaultDeploymentRampDragAnalyzer  (160 tests)
#
# SECURITY: PAT is read from macOS Keychain (service: GITHUB_PAT_SPA).
# DO NOT embed PAT or any credentials in this file.
#
# Usage: bash ~/Documents/SPA_Claude/scripts/push_v841.sh

set -e

COMMIT_MSG="feat(v8.41): MP-1195 DeFiProtocolVaultDeploymentRampDragAnalyzer (160 tests) | advisory/read-only yield_quality Tier-B (weight 0.5) | A vault's HEADLINE APR implicitly assumes capital is productive from t0, but many vaults impose a DEPLOYMENT RAMP: fresh capital sits idle (queued/warming-up/awaiting allocation) for N days at 0% before earning. Over a finite holding horizon the REALIZED annualized APR = headline * max(0, horizon - ramp)/horizon. The ramp is a pure non-earning TIME drag on principal (no explicit fee) and bites hardest on SHORT horizons where a fixed ramp consumes a large share of the window. HIGHER score = realized APR close to headline (ramp negligible vs horizon) -> headline honest for the holding window. | metrics: realized_apr_pct, drag_pct = headline - realized, realization_ratio, productive_fraction = max(0,horizon-ramp)/horizon, ramp_fraction, productive_days, full_horizon_lost, short_horizon (<=30d), long_ramp (>=7d); classification NEGLIGIBLE_RAMP/MINOR_RAMP/MODERATE_RAMP/SEVERE_RAMP (ramp_fraction thresholds 0.01/0.05/0.15, scale-free; + INSUFFICIENT_DATA); score = clamp(100*productive_fraction,0,100) | distinct from entry_fee_amortization/gas_breakeven/round_trip_cost (amortize a FIXED one-off COST, not a non-earning time lag), harvest_cycle_entry_timing/epoch_reward_timing (REWARD-capture timing, not principal deployment), pending_harvest_premium (opposite sign), withdrawal_fee_decay/lockup_opportunity_cost (exit-side frictions) | NaN/inf ramp validated on RAW input before clamp | pure stdlib, atomic ring-buffer log, no inf/NaN, read-only/advisory | registry Tier-B B=445->446, total 637->638 | KANBAN sprint_completed/sprint_current v8.40->v8.41, done MP-1195, done_count 890->891 | architect review: last completed before this run was v8.40 (minor 40, multiple of 5) so review was due, but spa_core.dev_agents.architect is unreachable in sandbox (ModuleNotFoundError: anthropic) — skipped with note, backlog scanned programmatically (no ready code tasks) | STRICTLY READ-ONLY (SPA-BL-011): risk/execution/monitoring/allocator/cycle_runner.py/golive_checker.py untouched"

FILES="/Users/yuriikulieshov/Documents/SPA_Claude/spa_core/analytics/defi_protocol_vault_deployment_ramp_drag_analyzer.py
/Users/yuriikulieshov/Documents/SPA_Claude/spa_core/tests/test_defi_protocol_vault_deployment_ramp_drag_analyzer.py
/Users/yuriikulieshov/Documents/SPA_Claude/data/vault_deployment_ramp_drag_log.json
/Users/yuriikulieshov/Documents/SPA_Claude/spa_core/analytics/_module_registry.py
/Users/yuriikulieshov/Documents/SPA_Claude/KANBAN.json
/Users/yuriikulieshov/Documents/SPA_Claude/sprint_log.md
/Users/yuriikulieshov/Documents/SPA_Claude/scripts/push_v841.sh"

# PAT resolution: Keychain -> env GITHUB_PAT_SPA -> env SPA_GITHUB_PAT -> ~/.github_pat
PAT=$(security find-generic-password -s GITHUB_PAT_SPA -w 2>/dev/null || echo "")
[ -z "$PAT" ] && PAT="${GITHUB_PAT_SPA:-${SPA_GITHUB_PAT:-}}"
[ -z "$PAT" ] && [ -f ~/.github_pat ] && PAT=$(cat ~/.github_pat)
[ -z "$PAT" ] && { echo "PAT not found — run: bash setup_pat.sh"; exit 1; }

cd ~/Documents/SPA_Claude
echo "SPA Push v8.41 — MP-1195 + tests + registry + KANBAN + sprint_log"
python3 push_to_github.py --files $FILES --message "$COMMIT_MSG" --pat "$PAT"
echo "Push v8.41 complete!"
