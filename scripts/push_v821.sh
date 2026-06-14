#!/bin/bash
# SPA Push v8.21
# MP-1160: DeFiProtocolVaultStrategyMigrationRiskAnalyzer  (157 tests)
# MP-1161: DeFiProtocolVaultWithdrawalFeeDecayAnalyzer     (146 tests)
#
# SECURITY: PAT is read from macOS Keychain (service: GITHUB_PAT_SPA).
# DO NOT embed PAT or any credentials in this file.
#
# Usage: bash ~/Documents/SPA_Claude/scripts/push_v821.sh

set -e

COMMIT_MSG="feat(v8.21): MP-1160 VaultStrategyMigrationRiskAnalyzer + MP-1161 VaultWithdrawalFeeDecayAnalyzer | 157+146=303 tests | advisory/read-only | strategy-migration event risk window (new-strategy maturity, migrated_tvl_pct, governance timelock, settledness, share-price continuity, 90d churn; LOW/MODERATE/ELEVATED/HIGH_MIGRATION_RISK; higher score=safer) [category vault_safety] + time-decaying early-withdrawal (loyalty) fee schedule (current_fee_pct at days_held via linear initial->floor decay, days_to_floor, fee_savings_if_wait, yield_while_waiting, at_floor; MATURED/LOW/MODERATE/HIGH_EXIT_FEE; higher score=cheaper to exit now) [category cost_efficiency] | registry Tier-B +2 (B=408) | pure stdlib, atomic ring-buffer logs"

FILES="/Users/yuriikulieshov/Documents/SPA_Claude/spa_core/analytics/defi_protocol_vault_strategy_migration_risk_analyzer.py
/Users/yuriikulieshov/Documents/SPA_Claude/spa_core/analytics/defi_protocol_vault_withdrawal_fee_decay_analyzer.py
/Users/yuriikulieshov/Documents/SPA_Claude/spa_core/tests/test_defi_protocol_vault_strategy_migration_risk_analyzer.py
/Users/yuriikulieshov/Documents/SPA_Claude/spa_core/tests/test_defi_protocol_vault_withdrawal_fee_decay_analyzer.py
/Users/yuriikulieshov/Documents/SPA_Claude/data/vault_strategy_migration_risk_log.json
/Users/yuriikulieshov/Documents/SPA_Claude/data/vault_withdrawal_fee_decay_log.json
/Users/yuriikulieshov/Documents/SPA_Claude/spa_core/analytics/_module_registry.py
/Users/yuriikulieshov/Documents/SPA_Claude/KANBAN.json
/Users/yuriikulieshov/Documents/SPA_Claude/sprint_log.md
/Users/yuriikulieshov/Documents/SPA_Claude/scripts/push_v821.sh"

# PAT resolution: Keychain → env GITHUB_PAT_SPA → env SPA_GITHUB_PAT → ~/.github_pat
PAT=$(security find-generic-password -s GITHUB_PAT_SPA -w 2>/dev/null || echo "")
[ -z "$PAT" ] && PAT="${GITHUB_PAT_SPA:-${SPA_GITHUB_PAT:-}}"
[ -z "$PAT" ] && [ -f ~/.github_pat ] && PAT=$(cat ~/.github_pat)
[ -z "$PAT" ] && { echo "PAT not found — run: bash setup_pat.sh"; exit 1; }

cd ~/Documents/SPA_Claude
echo "SPA Push v8.21 — MP-1160 + MP-1161 + tests + registry + KANBAN + sprint_log"
python3 push_to_github.py --files $FILES --message "$COMMIT_MSG" --pat "$PAT"
echo "Push v8.21 complete!"
