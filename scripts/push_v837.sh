#!/bin/bash
# SPA Push v8.37
# MP-1191: DeFiProtocolVaultUtilizationPeakHeadlineRevertAnalyzer  (265 tests)
#
# SECURITY: PAT is read from macOS Keychain (service: GITHUB_PAT_SPA).
# DO NOT embed PAT or any credentials in this file.
#
# Usage: bash ~/Documents/SPA_Claude/scripts/push_v837.sh

set -e

COMMIT_MSG="feat(v8.37): MP-1191 DeFiProtocolVaultUtilizationPeakHeadlineRevertAnalyzer (265 tests) | advisory/read-only yield_quality Tier-B (weight 0.5) | For lending-style vaults supply-APR ~= borrow_apr * utilization * (1 - reserve_factor); the headline supply-APR is quoted at CURRENT utilization. When current utilization sits materially ABOVE the vault's typical/equilibrium band, the headline is transiently elevated and will mean-revert DOWN toward the equilibrium-utilization APR as utilization normalizes -> a buy-and-hold supplier realizes closer to equilibrium, not the peak snapshot. HIGHER score = headline anchored at equilibrium (no peak overstatement). | metrics: equilibrium_apr_pct, revert_haircut_pct, headline_premium_pct, utilization_excess_pct, above_equilibrium, near_full_utilization (>=90%); classification ANCHORED/MILD_PEAK/MODERATE_PEAK/SEVERE_PEAK (+ INSUFFICIENT_DATA); flags ABOVE_EQUILIBRIUM_UTIL/NEAR_FULL_UTILIZATION/LARGE_REVERT_HAIRCUT | distinct from lending_utilization_cliff_detector (proximity to kink/cliff, withdrawal risk - protocol_health), lending_utilization_elasticity_analyzer (rate sensitivity to utilization - market_conditions) and apr_lookback_window_selection_bias (which time WINDOW was selected, not the utilization LEVEL driving the snapshot) | pure stdlib, atomic ring-buffer log, no inf/NaN, read-only/advisory | registry Tier-B B=441->442, total 633->634 | architect review: last completed before this run was v8.36 (minor 36, not a multiple of 5) so no review due; spa_core.dev_agents.architect also unreachable in sandbox | STRICTLY READ-ONLY (SPA-BL-011): risk/execution/monitoring/allocator/cycle_runner.py/golive_checker.py untouched"

FILES="/Users/yuriikulieshov/Documents/SPA_Claude/spa_core/analytics/defi_protocol_vault_utilization_peak_headline_revert_analyzer.py
/Users/yuriikulieshov/Documents/SPA_Claude/spa_core/tests/test_defi_protocol_vault_utilization_peak_headline_revert_analyzer.py
/Users/yuriikulieshov/Documents/SPA_Claude/data/vault_utilization_peak_headline_revert_log.json
/Users/yuriikulieshov/Documents/SPA_Claude/spa_core/analytics/_module_registry.py
/Users/yuriikulieshov/Documents/SPA_Claude/KANBAN.json
/Users/yuriikulieshov/Documents/SPA_Claude/sprint_log.md
/Users/yuriikulieshov/Documents/SPA_Claude/scripts/push_v837.sh"

# PAT resolution: Keychain -> env GITHUB_PAT_SPA -> env SPA_GITHUB_PAT -> ~/.github_pat
PAT=$(security find-generic-password -s GITHUB_PAT_SPA -w 2>/dev/null || echo "")
[ -z "$PAT" ] && PAT="${GITHUB_PAT_SPA:-${SPA_GITHUB_PAT:-}}"
[ -z "$PAT" ] && [ -f ~/.github_pat ] && PAT=$(cat ~/.github_pat)
[ -z "$PAT" ] && { echo "PAT not found — run: bash setup_pat.sh"; exit 1; }

cd ~/Documents/SPA_Claude
echo "SPA Push v8.37 — MP-1191 + tests + registry + KANBAN + sprint_log"
python3 push_to_github.py --files $FILES --message "$COMMIT_MSG" --pat "$PAT"
echo "Push v8.37 complete!"
