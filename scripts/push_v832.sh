#!/bin/bash
# SPA Push v8.32
# MP-1182: DeFiProtocolVaultSharePricePremiumAnalyzer        (183 tests)
# MP-1183: DeFiProtocolVaultUnclaimedRewardForfeitureAnalyzer (182 tests)
#
# SECURITY: PAT is read from macOS Keychain (service: GITHUB_PAT_SPA).
# DO NOT embed PAT or any credentials in this file.
#
# Usage: bash ~/Documents/SPA_Claude/scripts/push_v832.sh

set -e

COMMIT_MSG="feat(v8.32): MP-1182 VaultSharePricePremiumAnalyzer + MP-1183 VaultUnclaimedRewardForfeitureAnalyzer | 183+182=365 tests | advisory/read-only | share-price premium: a vault share / secondary-market price can trade ABOVE its NAV, so entering pays a premium that erodes returns as the price converges back to NAV over a horizon; this is the ENTRY-side mirror of the exit-side vault_instant_exit_nav_discount (which is about exiting at a discount) (premium_pct, annualized_drag_pct, payback_days; AT_OR_BELOW_NAV/SLIGHT/MODERATE/HIGH/EXTREME_PREMIUM; higher score=cheaper entry) [category yield_quality] + unclaimed-reward forfeiture: accrued-but-unclaimed rewards can face a hard claim-window deadline after which they are partially/fully forfeited; this measures forfeiture risk from time-to-deadline vs actual claim cadence, distinct from reward_claim_timing_optimizer (MP-1144, gas-vs-volatility timing with NO hard deadline) (urgency_ratio, miss_probability, expected_forfeit_usd/pct; SAFE/WATCH/AT_RISK/CRITICAL/EXPIRED; higher score=safer) [category yield_quality] | registry Tier-B +2 (B=434, total 626) | pure stdlib, atomic ring-buffer logs, no inf/NaN | architect review: v8.31 not a multiple of 5 -> no separate review required (spa_core.dev_agents.architect unreachable in sandbox anyway)"

FILES="/Users/yuriikulieshov/Documents/SPA_Claude/spa_core/analytics/defi_protocol_vault_share_price_premium_analyzer.py
/Users/yuriikulieshov/Documents/SPA_Claude/spa_core/analytics/defi_protocol_vault_unclaimed_reward_forfeiture_analyzer.py
/Users/yuriikulieshov/Documents/SPA_Claude/spa_core/tests/test_defi_protocol_vault_share_price_premium_analyzer.py
/Users/yuriikulieshov/Documents/SPA_Claude/spa_core/tests/test_defi_protocol_vault_unclaimed_reward_forfeiture_analyzer.py
/Users/yuriikulieshov/Documents/SPA_Claude/data/vault_share_price_premium_log.json
/Users/yuriikulieshov/Documents/SPA_Claude/data/vault_unclaimed_reward_forfeiture_log.json
/Users/yuriikulieshov/Documents/SPA_Claude/spa_core/analytics/_module_registry.py
/Users/yuriikulieshov/Documents/SPA_Claude/KANBAN.json
/Users/yuriikulieshov/Documents/SPA_Claude/sprint_log.md
/Users/yuriikulieshov/Documents/SPA_Claude/scripts/push_v832.sh"

# PAT resolution: Keychain → env GITHUB_PAT_SPA → env SPA_GITHUB_PAT → ~/.github_pat
PAT=$(security find-generic-password -s GITHUB_PAT_SPA -w 2>/dev/null || echo "")
[ -z "$PAT" ] && PAT="${GITHUB_PAT_SPA:-${SPA_GITHUB_PAT:-}}"
[ -z "$PAT" ] && [ -f ~/.github_pat ] && PAT=$(cat ~/.github_pat)
[ -z "$PAT" ] && { echo "PAT not found — run: bash setup_pat.sh"; exit 1; }

cd ~/Documents/SPA_Claude
echo "SPA Push v8.32 — MP-1182 + MP-1183 + tests + registry + KANBAN + sprint_log"
python3 push_to_github.py --files $FILES --message "$COMMIT_MSG" --pat "$PAT"
echo "Push v8.32 complete!"
