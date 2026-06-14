#!/bin/bash
# SPA Push v8.03
# MP-1130: DeFiProtocolInsuranceCoverageAnalyzer (154 tests)
# MP-1131: ProtocolDeFiPositionSizingOptimizer   (156 tests)
#
# SECURITY: PAT is read from macOS Keychain (service: GITHUB_PAT_SPA).
# DO NOT embed PAT or any credentials in this file.
#
# Usage: bash ~/Documents/SPA_Claude/scripts/push_v803.sh

set -e

COMMIT_MSG="feat(v8.03): MP-1130 DeFiProtocolInsuranceCoverageAnalyzer + MP-1131 ProtocolDeFiPositionSizingOptimizer | 154+156=310 tests | Kelly criterion DeFi | insurance label logic | atomic ring-buffer logs"

FILES="/Users/yuriikulieshov/Documents/SPA_Claude/spa_core/analytics/defi_protocol_insurance_coverage_analyzer.py
/Users/yuriikulieshov/Documents/SPA_Claude/spa_core/analytics/protocol_defi_position_sizing_optimizer.py
/Users/yuriikulieshov/Documents/SPA_Claude/spa_core/tests/test_defi_protocol_insurance_coverage_analyzer.py
/Users/yuriikulieshov/Documents/SPA_Claude/spa_core/tests/test_protocol_defi_position_sizing_optimizer.py
/Users/yuriikulieshov/Documents/SPA_Claude/KANBAN.json
/Users/yuriikulieshov/Documents/SPA_Claude/scripts/push_v803.sh"

# PAT resolution: Keychain → env GITHUB_PAT_SPA → env SPA_GITHUB_PAT → ~/.github_pat
PAT=$(security find-generic-password -s GITHUB_PAT_SPA -w 2>/dev/null || echo "")
[ -z "$PAT" ] && PAT="${GITHUB_PAT_SPA:-${SPA_GITHUB_PAT:-}}"
[ -z "$PAT" ] && [ -f ~/.github_pat ] && PAT=$(cat ~/.github_pat)
[ -z "$PAT" ] && { echo "PAT not found — run: bash setup_pat.sh"; exit 1; }

cd ~/Documents/SPA_Claude
echo "SPA Push v8.03 — MP-1130 + MP-1131 + tests + KANBAN"
python3 push_to_github.py --files $FILES --message "$COMMIT_MSG" --pat "$PAT"
echo "Push v8.03 complete!"
