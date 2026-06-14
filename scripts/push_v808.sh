#!/bin/bash
# SPA Push v8.08
# MP-1140: DeFiProtocolStablecoinYieldBasisSpreadAnalyzer   (105 tests)
# MP-1141: DeFiProtocolYieldAfterTaxDragAnalyzer            (109 tests)
#
# SECURITY: PAT is read from macOS Keychain (service: GITHUB_PAT_SPA).
# DO NOT embed PAT or any credentials in this file.
#
# Usage: bash ~/Documents/SPA_Claude/scripts/push_v808.sh

set -e

COMMIT_MSG="feat(v8.08): MP-1140 StablecoinYieldBasisSpreadAnalyzer + MP-1141 YieldAfterTaxDragAnalyzer | 105+109=214 tests | excess basis over risk-free + depeg-haircut real carry | after-tax APR & tax drag (marginal/harvest-freq/ST-vs-LT) | pure stdlib, atomic ring-buffer logs"

FILES="/Users/yuriikulieshov/Documents/SPA_Claude/spa_core/analytics/defi_protocol_stablecoin_yield_basis_spread_analyzer.py
/Users/yuriikulieshov/Documents/SPA_Claude/spa_core/analytics/defi_protocol_yield_after_tax_drag_analyzer.py
/Users/yuriikulieshov/Documents/SPA_Claude/spa_core/tests/test_defi_protocol_stablecoin_yield_basis_spread_analyzer.py
/Users/yuriikulieshov/Documents/SPA_Claude/spa_core/tests/test_defi_protocol_yield_after_tax_drag_analyzer.py
/Users/yuriikulieshov/Documents/SPA_Claude/KANBAN.json
/Users/yuriikulieshov/Documents/SPA_Claude/sprint_log.md
/Users/yuriikulieshov/Documents/SPA_Claude/scripts/push_v808.sh"

# PAT resolution: Keychain → env GITHUB_PAT_SPA → env SPA_GITHUB_PAT → ~/.github_pat
PAT=$(security find-generic-password -s GITHUB_PAT_SPA -w 2>/dev/null || echo "")
[ -z "$PAT" ] && PAT="${GITHUB_PAT_SPA:-${SPA_GITHUB_PAT:-}}"
[ -z "$PAT" ] && [ -f ~/.github_pat ] && PAT=$(cat ~/.github_pat)
[ -z "$PAT" ] && { echo "PAT not found — run: bash setup_pat.sh"; exit 1; }

cd ~/Documents/SPA_Claude
echo "SPA Push v8.08 — MP-1140 + MP-1141 + tests + KANBAN + sprint_log"
python3 push_to_github.py --files $FILES --message "$COMMIT_MSG" --pat "$PAT"
echo "Push v8.08 complete!"
