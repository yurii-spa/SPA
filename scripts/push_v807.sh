#!/bin/bash
# SPA Push v8.07
# MP-1138: DeFiProtocolGasCostBreakevenAnalyzer            (82 tests)
# MP-1139: ProtocolDeFiRewardTokenLockupDiscountAnalyzer   (83 tests)
#
# SECURITY: PAT is read from macOS Keychain (service: GITHUB_PAT_SPA).
# DO NOT embed PAT or any credentials in this file.
#
# Usage: bash ~/Documents/SPA_Claude/scripts/push_v807.sh

set -e

COMMIT_MSG="feat(v8.07): MP-1138 GasCostBreakevenAnalyzer + MP-1139 RewardTokenLockupDiscountAnalyzer | 82+83=165 tests | gas entry/exit/harvest breakeven (days+size) | locked-reward time-value/price-risk/early-exit discount → realisable APR | pure stdlib, atomic ring-buffer logs"

FILES="/Users/yuriikulieshov/Documents/SPA_Claude/spa_core/analytics/defi_protocol_gas_cost_breakeven_analyzer.py
/Users/yuriikulieshov/Documents/SPA_Claude/spa_core/analytics/protocol_defi_reward_token_lockup_discount_analyzer.py
/Users/yuriikulieshov/Documents/SPA_Claude/spa_core/tests/test_defi_protocol_gas_cost_breakeven_analyzer.py
/Users/yuriikulieshov/Documents/SPA_Claude/spa_core/tests/test_protocol_defi_reward_token_lockup_discount_analyzer.py
/Users/yuriikulieshov/Documents/SPA_Claude/KANBAN.json
/Users/yuriikulieshov/Documents/SPA_Claude/sprint_log.md
/Users/yuriikulieshov/Documents/SPA_Claude/scripts/push_v807.sh"

# PAT resolution: Keychain → env GITHUB_PAT_SPA → env SPA_GITHUB_PAT → ~/.github_pat
PAT=$(security find-generic-password -s GITHUB_PAT_SPA -w 2>/dev/null || echo "")
[ -z "$PAT" ] && PAT="${GITHUB_PAT_SPA:-${SPA_GITHUB_PAT:-}}"
[ -z "$PAT" ] && [ -f ~/.github_pat ] && PAT=$(cat ~/.github_pat)
[ -z "$PAT" ] && { echo "PAT not found — run: bash setup_pat.sh"; exit 1; }

cd ~/Documents/SPA_Claude
echo "SPA Push v8.07 — MP-1138 + MP-1139 + tests + KANBAN + sprint_log"
python3 push_to_github.py --files $FILES --message "$COMMIT_MSG" --pat "$PAT"
echo "Push v8.07 complete!"
