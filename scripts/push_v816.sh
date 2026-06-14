#!/bin/bash
# SPA Push v8.16
# MP-1150: DeFiProtocolMinimumProfitablePositionSizeAnalyzer  (100 tests)
# MP-1151: DeFiProtocolAutoCompoundKeeperReliabilityAnalyzer  (107 tests)
#
# SECURITY: PAT is read from macOS Keychain (service: GITHUB_PAT_SPA).
# DO NOT embed PAT or any credentials in this file.
#
# Usage: bash ~/Documents/SPA_Claude/scripts/push_v816.sh

set -e

COMMIT_MSG="feat(v8.16): MP-1150 MinimumProfitablePositionSizeAnalyzer + MP-1151 AutoCompoundKeeperReliabilityAnalyzer | 100+107=207 tests | advisory/read-only yield-quality | min profitable position size (roundtrip gas, min-profitable-position, entry-breakeven days, gas-as-pct, yield-per-gas, net-excess, capital-efficiency score; DEPLOY/DEPLOY_LARGER/SKIP) + auto-compound keeper reliability (harvest staleness ratio, completion/missed-harvest rate, realized-vs-theoretical APY drag, keeper centralization, reliability score) | registry Tier-B +2 (yield_quality) | pure stdlib, atomic ring-buffer logs"

FILES="/Users/yuriikulieshov/Documents/SPA_Claude/spa_core/analytics/defi_protocol_minimum_profitable_position_size_analyzer.py
/Users/yuriikulieshov/Documents/SPA_Claude/spa_core/analytics/defi_protocol_autocompound_keeper_reliability_analyzer.py
/Users/yuriikulieshov/Documents/SPA_Claude/spa_core/tests/test_defi_protocol_minimum_profitable_position_size_analyzer.py
/Users/yuriikulieshov/Documents/SPA_Claude/spa_core/tests/test_defi_protocol_autocompound_keeper_reliability_analyzer.py
/Users/yuriikulieshov/Documents/SPA_Claude/spa_core/analytics/_module_registry.py
/Users/yuriikulieshov/Documents/SPA_Claude/KANBAN.json
/Users/yuriikulieshov/Documents/SPA_Claude/sprint_log.md
/Users/yuriikulieshov/Documents/SPA_Claude/scripts/push_v816.sh"

# PAT resolution: Keychain → env GITHUB_PAT_SPA → env SPA_GITHUB_PAT → ~/.github_pat
PAT=$(security find-generic-password -s GITHUB_PAT_SPA -w 2>/dev/null || echo "")
[ -z "$PAT" ] && PAT="${GITHUB_PAT_SPA:-${SPA_GITHUB_PAT:-}}"
[ -z "$PAT" ] && [ -f ~/.github_pat ] && PAT=$(cat ~/.github_pat)
[ -z "$PAT" ] && { echo "PAT not found — run: bash setup_pat.sh"; exit 1; }

cd ~/Documents/SPA_Claude
echo "SPA Push v8.16 — MP-1150 + MP-1151 + tests + registry + KANBAN + sprint_log"
python3 push_to_github.py --files $FILES --message "$COMMIT_MSG" --pat "$PAT"
echo "Push v8.16 complete!"
