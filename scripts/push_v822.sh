#!/bin/bash
# SPA Push v8.22
# MP-1162: DeFiProtocolVaultRewardLockDiscountAnalyzer       (178 tests)
# MP-1163: DeFiProtocolVaultInstantExitNavDiscountAnalyzer   (178 tests)
#
# SECURITY: PAT is read from macOS Keychain (service: GITHUB_PAT_SPA).
# DO NOT embed PAT or any credentials in this file.
#
# Usage: bash ~/Documents/SPA_Claude/scripts/push_v822.sh

set -e

COMMIT_MSG="feat(v8.22): MP-1162 VaultRewardLockDiscountAnalyzer + MP-1163 VaultInstantExitNavDiscountAnalyzer | 178+178=356 tests | advisory/read-only | locked/vesting reward-token APR haircut: present-value discount of the locked reward portion over lock_days (pv_factor, discounted_reward_apr, liquid_equivalent_apr, apr_haircut, locked_share_pct, early_unlock_penalty; MOSTLY_LIQUID/MODERATE_LOCK/HEAVY_LOCK/FULLY_LOCKED; higher score=more liquid/durable yield) [category yield_quality] + instant-exit-vs-NAV decision: instant exit discount paid now vs opportunity cost of capital stuck in the redemption queue (instant_exit_discount_pct, wait_opportunity_cost_pct, breakeven_wait_days, instant_cheaper, savings_by_waiting; MINIMAL/LOW/MODERATE/STEEP_DISCOUNT; EXIT_INSTANT/WAIT_FOR_NAV; higher score=lower exit friction) [category exit_liquidity] | registry Tier-B +2 (B=412) | pure stdlib, atomic ring-buffer logs"

FILES="/Users/yuriikulieshov/Documents/SPA_Claude/spa_core/analytics/defi_protocol_vault_reward_lock_discount_analyzer.py
/Users/yuriikulieshov/Documents/SPA_Claude/spa_core/analytics/defi_protocol_vault_instant_exit_nav_discount_analyzer.py
/Users/yuriikulieshov/Documents/SPA_Claude/spa_core/tests/test_defi_protocol_vault_reward_lock_discount_analyzer.py
/Users/yuriikulieshov/Documents/SPA_Claude/spa_core/tests/test_defi_protocol_vault_instant_exit_nav_discount_analyzer.py
/Users/yuriikulieshov/Documents/SPA_Claude/data/vault_reward_lock_discount_log.json
/Users/yuriikulieshov/Documents/SPA_Claude/data/vault_instant_exit_nav_discount_log.json
/Users/yuriikulieshov/Documents/SPA_Claude/spa_core/analytics/_module_registry.py
/Users/yuriikulieshov/Documents/SPA_Claude/KANBAN.json
/Users/yuriikulieshov/Documents/SPA_Claude/sprint_log.md
/Users/yuriikulieshov/Documents/SPA_Claude/scripts/push_v822.sh"

# PAT resolution: Keychain → env GITHUB_PAT_SPA → env SPA_GITHUB_PAT → ~/.github_pat
PAT=$(security find-generic-password -s GITHUB_PAT_SPA -w 2>/dev/null || echo "")
[ -z "$PAT" ] && PAT="${GITHUB_PAT_SPA:-${SPA_GITHUB_PAT:-}}"
[ -z "$PAT" ] && [ -f ~/.github_pat ] && PAT=$(cat ~/.github_pat)
[ -z "$PAT" ] && { echo "PAT not found — run: bash setup_pat.sh"; exit 1; }

cd ~/Documents/SPA_Claude
echo "SPA Push v8.22 — MP-1162 + MP-1163 + tests + registry + KANBAN + sprint_log"
python3 push_to_github.py --files $FILES --message "$COMMIT_MSG" --pat "$PAT"
echo "Push v8.22 complete!"
