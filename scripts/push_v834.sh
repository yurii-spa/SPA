#!/bin/bash
# SPA Push v8.34
# MP-1186: DeFiProtocolVaultRewardEmissionExpiryCliffAnalyzer       (201 tests)
# MP-1187: DeFiProtocolVaultDenominationCurrencyYieldBasisAnalyzer  (197 tests)
#
# SECURITY: PAT is read from macOS Keychain (service: GITHUB_PAT_SPA).
# DO NOT embed PAT or any credentials in this file.
#
# Usage: bash ~/Documents/SPA_Claude/scripts/push_v834.sh

set -e

COMMIT_MSG="feat(v8.34): MP-1186 VaultRewardEmissionExpiryCliffAnalyzer + MP-1187 VaultDenominationCurrencyYieldBasisAnalyzer | 201+197=398 tests | advisory/read-only | reward emission expiry cliff: part of a vault headline APR rests on a token-emission/incentive program with a SCHEDULED END DATE (a cliff); on that date the reward APR drops to ~0 and the headline collapses to base APR, so the forward-effective APR over your holding horizon can be far below the headline; quantifies emission_share, days_to_cliff, forward_apr_pct/forward_drop_pct, distinct from trailing_window_boost_backdating (a PAST boost still inflating a backward trailing average) and gauge_emission_decay_forecaster / protocol_incentive_decay_monitor (SMOOTH gradual decay) — this is a DISCRETE future expiry cliff (higher score=headline durable past your horizon) [category yield_quality] + denomination currency yield basis: a headline APR is quoted in the vault DENOMINATION token (e.g. an ETH vault quotes APR in ETH terms), so a numeraire (USD) holder realizes token_apr + annualized price drift; the more volatile the denomination token and the larger its possible drift over the horizon, the less the token-denominated headline reflects the holder numeraire outcome; quantifies numeraire_apr_pct (with low/high band), horizon_basis_gap_pct, distinct from reward_token_price_exposure (price risk of the REWARD token) — this is the principal/denomination token in which the headline yield itself is quoted (higher score=headline close to numeraire outcome) [category yield_quality] | registry Tier-B +2 (B=438, total 630) | pure stdlib, atomic ring-buffer logs, no inf/NaN | architect review: v8.34 not a multiple of 5 -> no separate review required (spa_core.dev_agents.architect unreachable in sandbox anyway)"

FILES="/Users/yuriikulieshov/Documents/SPA_Claude/spa_core/analytics/defi_protocol_vault_reward_emission_expiry_cliff_analyzer.py
/Users/yuriikulieshov/Documents/SPA_Claude/spa_core/analytics/defi_protocol_vault_denomination_currency_yield_basis_analyzer.py
/Users/yuriikulieshov/Documents/SPA_Claude/spa_core/tests/test_defi_protocol_vault_reward_emission_expiry_cliff_analyzer.py
/Users/yuriikulieshov/Documents/SPA_Claude/spa_core/tests/test_defi_protocol_vault_denomination_currency_yield_basis_analyzer.py
/Users/yuriikulieshov/Documents/SPA_Claude/data/vault_reward_emission_expiry_cliff_log.json
/Users/yuriikulieshov/Documents/SPA_Claude/data/vault_denomination_currency_yield_basis_log.json
/Users/yuriikulieshov/Documents/SPA_Claude/spa_core/analytics/_module_registry.py
/Users/yuriikulieshov/Documents/SPA_Claude/KANBAN.json
/Users/yuriikulieshov/Documents/SPA_Claude/sprint_log.md
/Users/yuriikulieshov/Documents/SPA_Claude/scripts/push_v834.sh"

# PAT resolution: Keychain → env GITHUB_PAT_SPA → env SPA_GITHUB_PAT → ~/.github_pat
PAT=$(security find-generic-password -s GITHUB_PAT_SPA -w 2>/dev/null || echo "")
[ -z "$PAT" ] && PAT="${GITHUB_PAT_SPA:-${SPA_GITHUB_PAT:-}}"
[ -z "$PAT" ] && [ -f ~/.github_pat ] && PAT=$(cat ~/.github_pat)
[ -z "$PAT" ] && { echo "PAT not found — run: bash setup_pat.sh"; exit 1; }

cd ~/Documents/SPA_Claude
echo "SPA Push v8.34 — MP-1186 + MP-1187 + tests + registry + KANBAN + sprint_log"
python3 push_to_github.py --files $FILES --message "$COMMIT_MSG" --pat "$PAT"
echo "Push v8.34 complete!"
