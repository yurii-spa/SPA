#!/bin/bash
# SPA Push v8.29
# MP-1176: DeFiProtocolVaultDepositActivationLagAnalyzer        (175 tests)
# MP-1177: DeFiProtocolVaultRewardAutosellSlippageAnalyzer      (167 tests)
#
# SECURITY: PAT is read from macOS Keychain (service: GITHUB_PAT_SPA).
# DO NOT embed PAT or any credentials in this file.
#
# Usage: bash ~/Documents/SPA_Claude/scripts/push_v829.sh

set -e

COMMIT_MSG="feat(v8.29): MP-1176 VaultDepositActivationLagAnalyzer + MP-1177 VaultRewardAutosellSlippageAnalyzer | 175+167=342 tests | advisory/read-only | deposit activation lag: new capital sits idle (warmup/deposit-queue/epoch boundary) before it starts earning, dragging the effective realized APR over the holder's horizon; distinct from idle_cash_drag (structural reserve), redemption_cooldown (exit lock) and harvest_cycle_entry_timing MP-1173 (lag_days, effective_apr_pct, yield_drag_pct, drag_ratio, lag_exceeds_hold; INSTANT/MINOR/MATERIAL/SEVERE_LAG; higher score=faster deploy) [category yield_quality] + reward auto-sell slippage: an auto-compounder periodically sells the reward token to reinvest; if the recurring sale is large vs the reward token's market depth the compounding itself incurs slippage that erodes realized yield below headline; distinct from reward_token_price_exposure MP-1170, bribe_dependency MP-1175 and gas_cost_breakeven (sell_to_depth_ratio, est_slippage_pct, realized_headline_apr_pct, thin_market; NO_AUTOSELL/NEGLIGIBLE/LOW/MODERATE/HIGH_SLIPPAGE; higher score=cleaner compounding) [category yield_quality] | registry Tier-B +2 (B=428, total 620) | pure stdlib, atomic ring-buffer logs, no inf/NaN"

FILES="/Users/yuriikulieshov/Documents/SPA_Claude/spa_core/analytics/defi_protocol_vault_deposit_activation_lag_analyzer.py
/Users/yuriikulieshov/Documents/SPA_Claude/spa_core/analytics/defi_protocol_vault_reward_autosell_slippage_analyzer.py
/Users/yuriikulieshov/Documents/SPA_Claude/spa_core/tests/test_defi_protocol_vault_deposit_activation_lag_analyzer.py
/Users/yuriikulieshov/Documents/SPA_Claude/spa_core/tests/test_defi_protocol_vault_reward_autosell_slippage_analyzer.py
/Users/yuriikulieshov/Documents/SPA_Claude/data/vault_deposit_activation_lag_log.json
/Users/yuriikulieshov/Documents/SPA_Claude/data/vault_reward_autosell_slippage_log.json
/Users/yuriikulieshov/Documents/SPA_Claude/spa_core/analytics/_module_registry.py
/Users/yuriikulieshov/Documents/SPA_Claude/KANBAN.json
/Users/yuriikulieshov/Documents/SPA_Claude/sprint_log.md
/Users/yuriikulieshov/Documents/SPA_Claude/scripts/push_v829.sh"

# PAT resolution: Keychain → env GITHUB_PAT_SPA → env SPA_GITHUB_PAT → ~/.github_pat
PAT=$(security find-generic-password -s GITHUB_PAT_SPA -w 2>/dev/null || echo "")
[ -z "$PAT" ] && PAT="${GITHUB_PAT_SPA:-${SPA_GITHUB_PAT:-}}"
[ -z "$PAT" ] && [ -f ~/.github_pat ] && PAT=$(cat ~/.github_pat)
[ -z "$PAT" ] && { echo "PAT not found — run: bash setup_pat.sh"; exit 1; }

cd ~/Documents/SPA_Claude
echo "SPA Push v8.29 — MP-1176 + MP-1177 + tests + registry + KANBAN + sprint_log"
python3 push_to_github.py --files $FILES --message "$COMMIT_MSG" --pat "$PAT"
echo "Push v8.29 complete!"
