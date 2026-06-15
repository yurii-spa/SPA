#!/bin/bash
# SPA Push v8.23
# MP-1164: DeFiProtocolVaultGasBreakevenAnalyzer    (175 tests)
# MP-1165: DeFiProtocolVaultDepegRecoveryAnalyzer   (178 tests)
#
# SECURITY: PAT is read from macOS Keychain (service: GITHUB_PAT_SPA).
# DO NOT embed PAT or any credentials in this file.
#
# Usage: bash ~/Documents/SPA_Claude/scripts/push_v823.sh

set -e

COMMIT_MSG="feat(v8.23): MP-1164 VaultGasBreakevenAnalyzer + MP-1165 VaultDepegRecoveryAnalyzer | 175+178=353 tests | advisory/read-only | fixed gas (deposit/withdrawal/compound) vs yield: does a position size + APR edge cover round-trip + annual compound gas? (total_gas_usd, gas_drag_pct, net_apr_pct, breakeven_position_usd, breakeven_days, covers_horizon; NEGLIGIBLE/LOW/MODERATE/HIGH_GAS/NEVER_BREAKS_EVEN; higher score=less gas drag) [category cost_efficiency] + depegged pegged-asset hold-vs-exit decision: current discount-to-peg weighed against historical recovery profile + backing (depeg_pct, discount_to_peg_pct, recovery_rate_pct, upside_if_recovers_pct, is_stale_depeg, collateral_ratio; AT_PEG/MINOR/MODERATE/SEVERE_DEPEG; HOLD_FOR_RECOVERY/EXIT_PARTIAL/EXIT; higher score=safer/more likely to recover) [category peg_stability] | registry Tier-B +2 (B=414) | pure stdlib, atomic ring-buffer logs"

FILES="/Users/yuriikulieshov/Documents/SPA_Claude/spa_core/analytics/defi_protocol_vault_gas_breakeven_analyzer.py
/Users/yuriikulieshov/Documents/SPA_Claude/spa_core/analytics/defi_protocol_vault_depeg_recovery_analyzer.py
/Users/yuriikulieshov/Documents/SPA_Claude/spa_core/tests/test_defi_protocol_vault_gas_breakeven_analyzer.py
/Users/yuriikulieshov/Documents/SPA_Claude/spa_core/tests/test_defi_protocol_vault_depeg_recovery_analyzer.py
/Users/yuriikulieshov/Documents/SPA_Claude/data/vault_gas_breakeven_log.json
/Users/yuriikulieshov/Documents/SPA_Claude/data/vault_depeg_recovery_log.json
/Users/yuriikulieshov/Documents/SPA_Claude/spa_core/analytics/_module_registry.py
/Users/yuriikulieshov/Documents/SPA_Claude/KANBAN.json
/Users/yuriikulieshov/Documents/SPA_Claude/sprint_log.md
/Users/yuriikulieshov/Documents/SPA_Claude/scripts/push_v823.sh"

# PAT resolution: Keychain → env GITHUB_PAT_SPA → env SPA_GITHUB_PAT → ~/.github_pat
PAT=$(security find-generic-password -s GITHUB_PAT_SPA -w 2>/dev/null || echo "")
[ -z "$PAT" ] && PAT="${GITHUB_PAT_SPA:-${SPA_GITHUB_PAT:-}}"
[ -z "$PAT" ] && [ -f ~/.github_pat ] && PAT=$(cat ~/.github_pat)
[ -z "$PAT" ] && { echo "PAT not found — run: bash setup_pat.sh"; exit 1; }

cd ~/Documents/SPA_Claude
echo "SPA Push v8.23 — MP-1164 + MP-1165 + tests + registry + KANBAN + sprint_log"
python3 push_to_github.py --files $FILES --message "$COMMIT_MSG" --pat "$PAT"
echo "Push v8.23 complete!"
