#!/bin/bash
# SPA Push v8.38
# MP-1192: DeFiProtocolVaultBoostTierHeadlineRealizationAnalyzer  (298 tests)
#
# SECURITY: PAT is read from macOS Keychain (service: GITHUB_PAT_SPA).
# DO NOT embed PAT or any credentials in this file.
#
# Usage: bash ~/Documents/SPA_Claude/scripts/push_v838.sh

set -e

COMMIT_MSG="feat(v8.38): MP-1192 DeFiProtocolVaultBoostTierHeadlineRealizationAnalyzer (298 tests) | advisory/read-only yield_quality Tier-B (weight 0.5) | In gauge/ve-model vaults (Curve/Convex-style) the HEADLINE APR is the MAX boosted rate, achievable only with a maximum veToken lock (max_boost_multiplier, e.g. 2.5x). An unboosted depositor realizes the BASE rate = headline / max_boost_multiplier; a partially boosted depositor realizes headline * (depositor_boost / max_boost). Discount the headline to the depositor's actual boost tier. HIGHER score = headline matches the depositor's realizable boost (no boost-tier overstatement). | metrics: base_apr_pct, realized_apr_pct, realization_ratio, boost_gap_multiplier, boost_haircut_pct, boost_premium_pct; classification FULLY_REALIZED/MILD_BOOST_GAP/MODERATE_BOOST_GAP/SEVERE_BOOST_GAP (+ INSUFFICIENT_DATA); flags UNBOOSTED/MAX_BOOST_REQUIRED/LARGE_BOOST_HAIRCUT | distinct from yield_booster_detector (detects boost programs & sustainability/value), defi_protocol_vault_trailing_window_boost_backdating_analyzer (expired boost inside the trailing window), protocol_defi_ve_token_lock_optimizer/vetoken_governance_power (optimize the lock decision) | pure stdlib, atomic ring-buffer log, no inf/NaN, read-only/advisory | registry Tier-B B=442->443, total 634->635 | architect review: last completed before this run was v8.37 (minor 37, not a multiple of 5) so no review due; spa_core.dev_agents.architect also unreachable in sandbox | STRICTLY READ-ONLY (SPA-BL-011): risk/execution/monitoring/allocator/cycle_runner.py/golive_checker.py untouched"

FILES="/Users/yuriikulieshov/Documents/SPA_Claude/spa_core/analytics/defi_protocol_vault_boost_tier_headline_realization_analyzer.py
/Users/yuriikulieshov/Documents/SPA_Claude/spa_core/tests/test_defi_protocol_vault_boost_tier_headline_realization_analyzer.py
/Users/yuriikulieshov/Documents/SPA_Claude/data/vault_boost_tier_headline_realization_log.json
/Users/yuriikulieshov/Documents/SPA_Claude/spa_core/analytics/_module_registry.py
/Users/yuriikulieshov/Documents/SPA_Claude/KANBAN.json
/Users/yuriikulieshov/Documents/SPA_Claude/sprint_log.md
/Users/yuriikulieshov/Documents/SPA_Claude/scripts/push_v838.sh"

# PAT resolution: Keychain -> env GITHUB_PAT_SPA -> env SPA_GITHUB_PAT -> ~/.github_pat
PAT=$(security find-generic-password -s GITHUB_PAT_SPA -w 2>/dev/null || echo "")
[ -z "$PAT" ] && PAT="${GITHUB_PAT_SPA:-${SPA_GITHUB_PAT:-}}"
[ -z "$PAT" ] && [ -f ~/.github_pat ] && PAT=$(cat ~/.github_pat)
[ -z "$PAT" ] && { echo "PAT not found — run: bash setup_pat.sh"; exit 1; }

cd ~/Documents/SPA_Claude
echo "SPA Push v8.38 — MP-1192 + tests + registry + KANBAN + sprint_log"
python3 push_to_github.py --files $FILES --message "$COMMIT_MSG" --pat "$PAT"
echo "Push v8.38 complete!"
