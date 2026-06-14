#!/bin/bash
# SPA Push v8.19
# MP-1156: DeFiProtocolVaultShareInflationAttackExposureAnalyzer  (137 tests)
# MP-1157: DeFiProtocolVaultIdleCashDragAnalyzer                  (129 tests)
#
# SECURITY: PAT is read from macOS Keychain (service: GITHUB_PAT_SPA).
# DO NOT embed PAT or any credentials in this file.
#
# Usage: bash ~/Documents/SPA_Claude/scripts/push_v819.sh

set -e

COMMIT_MSG="feat(v8.19): MP-1156 VaultShareInflationAttackExposureAnalyzer + MP-1157 VaultIdleCashDragAnalyzer | 137+129=266 tests | advisory/read-only | ERC-4626 share-inflation / first-depositor donation exposure (share_price, effective_protection, donation_to_inflate, rounding_loss_shares_pct, vulnerability_score; WELL_PROTECTED/LOW/MODERATE/HIGH_RISK) [new category vault_safety] + idle/uninvested capital drag (idle_pct/deployed_pct, effective_apr, apr_drag, excess_idle, recoverable_apr, efficiency_score; FULLY_DEPLOYED/LEAN/HEAVY_BUFFER/MOSTLY_IDLE) [new category capital_efficiency] | registry Tier-B +2 | pure stdlib, atomic ring-buffer logs"

FILES="/Users/yuriikulieshov/Documents/SPA_Claude/spa_core/analytics/defi_protocol_vault_share_inflation_attack_exposure_analyzer.py
/Users/yuriikulieshov/Documents/SPA_Claude/spa_core/analytics/defi_protocol_vault_idle_cash_drag_analyzer.py
/Users/yuriikulieshov/Documents/SPA_Claude/spa_core/tests/test_defi_protocol_vault_share_inflation_attack_exposure_analyzer.py
/Users/yuriikulieshov/Documents/SPA_Claude/spa_core/tests/test_defi_protocol_vault_idle_cash_drag_analyzer.py
/Users/yuriikulieshov/Documents/SPA_Claude/spa_core/analytics/_module_registry.py
/Users/yuriikulieshov/Documents/SPA_Claude/KANBAN.json
/Users/yuriikulieshov/Documents/SPA_Claude/sprint_log.md
/Users/yuriikulieshov/Documents/SPA_Claude/scripts/push_v819.sh"

# PAT resolution: Keychain → env GITHUB_PAT_SPA → env SPA_GITHUB_PAT → ~/.github_pat
PAT=$(security find-generic-password -s GITHUB_PAT_SPA -w 2>/dev/null || echo "")
[ -z "$PAT" ] && PAT="${GITHUB_PAT_SPA:-${SPA_GITHUB_PAT:-}}"
[ -z "$PAT" ] && [ -f ~/.github_pat ] && PAT=$(cat ~/.github_pat)
[ -z "$PAT" ] && { echo "PAT not found — run: bash setup_pat.sh"; exit 1; }

cd ~/Documents/SPA_Claude
echo "SPA Push v8.19 — MP-1156 + MP-1157 + tests + registry + KANBAN + sprint_log"
python3 push_to_github.py --files $FILES --message "$COMMIT_MSG" --pat "$PAT"
echo "Push v8.19 complete!"
