#!/bin/bash
# SPA Push v8.40
# MP-1194: DeFiProtocolVaultMarginalDepositAPRDilutionAnalyzer  (201 tests)
#
# SECURITY: PAT is read from macOS Keychain (service: GITHUB_PAT_SPA).
# DO NOT embed PAT or any credentials in this file.
#
# Usage: bash ~/Documents/SPA_Claude/scripts/push_v840.sh

set -e

COMMIT_MSG="feat(v8.40): MP-1194 DeFiProtocolVaultMarginalDepositAPRDilutionAnalyzer (201 tests) | advisory/read-only yield_quality Tier-B (weight 0.5) | A vault's HEADLINE blended APR is an allocation-weighted AVERAGE across sub-strategy sleeves. A NEW marginal deposit cannot earn that average because the highest-yielding sleeves are often capacity-constrained: new capital is routed greedily (descending APR) only into sleeves with remaining capacity and any undeployable remainder sits idle at 0%, so the MARGINAL APR earned by new dollars is typically LOWER than the headline. HIGHER score = marginal deposit APR close to/above the headline (top sleeves have ample capacity) -> headline honest for new capital. | metrics: marginal_apr_pct (greedy capacity-limited routing), weighted_avg_apr_pct, dilution_pct = headline - marginal, top_sleeve_apr/capacity_remaining, deployable/undeployed_usd, fully_absorbed, top_sleeve_constrained; classification MARGINAL_ABOVE_HEADLINE/ALIGNED/MINOR_DILUTION/MODERATE_DILUTION/SEVERE_DILUTION (|dil|<=0.5 aligned, <=3 minor, <=8 moderate, >8 severe; + INSUFFICIENT_DATA); flags TOP_SLEEVE_CAPACITY_CONSTRAINED/DEPOSIT_NOT_FULLY_ABSORBED/HEADLINE_ABOVE_CURRENT_AVERAGE/SPARSE_SLEEVES | distinct from defi_protocol_vault_capacity_dilution_analyzer (aggregate TVL-growth reward dilution, not per-sleeve marginal routing), defi_protocol_yield_source_diversification_scorer, protocol_defi_apy_decomposition_analyzer, defi_protocol_vault_boost_tier_headline_realization_analyzer | pure stdlib, atomic ring-buffer log, no inf/NaN, read-only/advisory | registry Tier-B B=444->445, total 636->637 | KANBAN sprint_completed/sprint_current v8.39->v8.40, done MP-1194, done_count 889->890 | architect review: last completed before this run was v8.39 (minor 39, not a multiple of 5) so no review due; spa_core.dev_agents.architect also unreachable in sandbox | STRICTLY READ-ONLY (SPA-BL-011): risk/execution/monitoring/allocator/cycle_runner.py/golive_checker.py untouched"

FILES="/Users/yuriikulieshov/Documents/SPA_Claude/spa_core/analytics/defi_protocol_vault_marginal_deposit_apr_dilution_analyzer.py
/Users/yuriikulieshov/Documents/SPA_Claude/spa_core/tests/test_defi_protocol_vault_marginal_deposit_apr_dilution_analyzer.py
/Users/yuriikulieshov/Documents/SPA_Claude/data/vault_marginal_deposit_apr_dilution_log.json
/Users/yuriikulieshov/Documents/SPA_Claude/spa_core/analytics/_module_registry.py
/Users/yuriikulieshov/Documents/SPA_Claude/KANBAN.json
/Users/yuriikulieshov/Documents/SPA_Claude/sprint_log.md
/Users/yuriikulieshov/Documents/SPA_Claude/scripts/push_v840.sh"

# PAT resolution: Keychain -> env GITHUB_PAT_SPA -> env SPA_GITHUB_PAT -> ~/.github_pat
PAT=$(security find-generic-password -s GITHUB_PAT_SPA -w 2>/dev/null || echo "")
[ -z "$PAT" ] && PAT="${GITHUB_PAT_SPA:-${SPA_GITHUB_PAT:-}}"
[ -z "$PAT" ] && [ -f ~/.github_pat ] && PAT=$(cat ~/.github_pat)
[ -z "$PAT" ] && { echo "PAT not found — run: bash setup_pat.sh"; exit 1; }

cd ~/Documents/SPA_Claude
echo "SPA Push v8.40 — MP-1194 + tests + registry + KANBAN + sprint_log"
python3 push_to_github.py --files $FILES --message "$COMMIT_MSG" --pat "$PAT"
echo "Push v8.40 complete!"
