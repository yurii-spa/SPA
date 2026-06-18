#!/bin/bash
# SPA Push v8.42
# MP-1196: DeFiProtocolVaultFundingRateCarryPersistenceAnalyzer  (211 tests)
#
# SECURITY: PAT is read from macOS Keychain (service: GITHUB_PAT_SPA).
# DO NOT embed PAT or any credentials in this file.
#
# Usage: bash ~/Documents/SPA_Claude/scripts/push_v842.sh

set -e

COMMIT_MSG="feat(v8.42): MP-1196 DeFiProtocolVaultFundingRateCarryPersistenceAnalyzer (211 tests) | advisory/read-only yield_quality Tier-B (weight 0.5) | Delta-neutral / basis-trade vaults (long spot + short perp, Ethena-style) earn yield from PERPETUAL FUNDING RATES, and the HEADLINE APR is just the CURRENT funding rate annualized. But funding is a SIGNED carry that mean-reverts and FLIPS NEGATIVE in crowded/bearish regimes where the vault PAYS funding. The honest realized carry over a window is the blended (mean) of the signed funding samples, which can be far below the headline or negative. This module measures how reliable/persistent the positive-funding regime is and how overstated the headline is vs the blended realized carry. HIGHER score = funding reliably positive AND realized blended carry close to headline. | metrics: realized_blended_apr_pct = mean(signed samples), overstatement_pct = headline - realized, realization_ratio, negative_funding_fraction, positive_funding_fraction, avg_negative_funding_apr, avg_positive_funding_apr, min/max_funding_apr, sign_flips, sample_count; flags FUNDING_FLIPS_NEGATIVE / DEEP_NEGATIVE_REGIME (<=-10pp) / HEADLINE_FROM_SPIKE (headline>=1.25x blended) / REALIZED_NEGATIVE_CARRY / STABLE_CARRY; classification PERSISTENT_POSITIVE/MOSTLY_POSITIVE/REGIME_MIXED/FUNDING_UNRELIABLE (neg_frac thresholds 0.05/0.20/0.45; + INSUFFICIENT_DATA <2 valid samples); score = clamp(60*(1-neg_frac) + 40*clamp(realized/headline,0,1), 0,100) | distinct from headline_spot_snapshot_vs_twap (spike-representativeness of a generally-POSITIVE rate vs its TWAP; here carry is SIGNED and can be a COST - core risk is negative-regime frequency & sign flips), utilization_peak_headline_revert (lending UTILIZATION mean-reversion of always-positive borrow APR), and the Tier-C funding_rate_arbitrage_* / perpetual_funding_rate analyzers (cross-venue ARBITRAGE detection, not vault headline honesty) | non-finite funding samples filtered before stats | pure stdlib, atomic ring-buffer log, no inf/NaN, read-only/advisory | registry Tier-B B=446->447, total 638->639 | KANBAN sprint_completed/sprint_current v8.41->v8.42, done MP-1196, done_count 891->892 | architect review: last completed before this run was v8.41 (minor 41, not a multiple of 5) so no review required; spa_core.dev_agents.architect unreachable in sandbox anyway (ModuleNotFoundError: anthropic), backlog scanned programmatically (no ready type=code tasks) | STRICTLY READ-ONLY (SPA-BL-011): risk/execution/monitoring/allocator/cycle_runner.py/golive_checker.py untouched"

FILES="/Users/yuriikulieshov/Documents/SPA_Claude/spa_core/analytics/defi_protocol_vault_funding_rate_carry_persistence_analyzer.py
/Users/yuriikulieshov/Documents/SPA_Claude/spa_core/tests/test_defi_protocol_vault_funding_rate_carry_persistence_analyzer.py
/Users/yuriikulieshov/Documents/SPA_Claude/data/vault_funding_rate_carry_persistence_log.json
/Users/yuriikulieshov/Documents/SPA_Claude/spa_core/analytics/_module_registry.py
/Users/yuriikulieshov/Documents/SPA_Claude/KANBAN.json
/Users/yuriikulieshov/Documents/SPA_Claude/sprint_log.md
/Users/yuriikulieshov/Documents/SPA_Claude/scripts/push_v842.sh"

# PAT resolution: Keychain -> env GITHUB_PAT_SPA -> env SPA_GITHUB_PAT -> ~/.github_pat
PAT=$(security find-generic-password -s GITHUB_PAT_SPA -w 2>/dev/null || echo "")
[ -z "$PAT" ] && PAT="${GITHUB_PAT_SPA:-${SPA_GITHUB_PAT:-}}"
[ -z "$PAT" ] && [ -f ~/.github_pat ] && PAT=$(cat ~/.github_pat)
[ -z "$PAT" ] && { echo "PAT not found — run: bash setup_pat.sh"; exit 1; }

cd ~/Documents/SPA_Claude
echo "SPA Push v8.42 — MP-1196 + tests + registry + KANBAN + sprint_log"
python3 push_to_github.py --files $FILES --message "$COMMIT_MSG" --pat "$PAT"
echo "Push v8.42 complete!"
