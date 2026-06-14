#!/bin/bash
# SPA Push v8.14
# LendingUtilizationElasticity  (APR sensitivity to utilization moves along the kink curve)
# CrossChainYieldBasisRisk      (same-asset cross-chain yield basis + bridge/peg basis risk)
# 132 tests total
#
# SECURITY: PAT is read from macOS Keychain (service: GITHUB_PAT_SPA).
# DO NOT embed PAT or any credentials in this file.
#
# Usage: bash ~/Documents/SPA_Claude/scripts/push_v814.sh

set -e

COMMIT_MSG="feat(v8.14): LendingUtilizationElasticityAnalyzer + CrossChainYieldBasisRiskAnalyzer | 132 tests | advisory/read-only | lending utilization elasticity (supply APR sensitivity to utilization/kink proximity, elasticity score) + cross-chain yield basis risk (same-asset chain yield spread net of bridge/peg basis, basis-risk score) | registry Tier-B +2 | pure stdlib, atomic ring-buffer logs"

FILES="/Users/yuriikulieshov/Documents/SPA_Claude/spa_core/analytics/defi_protocol_lending_utilization_elasticity_analyzer.py
/Users/yuriikulieshov/Documents/SPA_Claude/spa_core/analytics/defi_protocol_cross_chain_yield_basis_risk_analyzer.py
/Users/yuriikulieshov/Documents/SPA_Claude/spa_core/tests/test_defi_protocol_lending_utilization_elasticity_analyzer.py
/Users/yuriikulieshov/Documents/SPA_Claude/spa_core/tests/test_defi_protocol_cross_chain_yield_basis_risk_analyzer.py
/Users/yuriikulieshov/Documents/SPA_Claude/spa_core/analytics/_module_registry.py
/Users/yuriikulieshov/Documents/SPA_Claude/KANBAN.json
/Users/yuriikulieshov/Documents/SPA_Claude/sprint_log.md
/Users/yuriikulieshov/Documents/SPA_Claude/scripts/push_v814.sh"

# PAT resolution: Keychain → env GITHUB_PAT_SPA → env SPA_GITHUB_PAT → ~/.github_pat
PAT=$(security find-generic-password -s GITHUB_PAT_SPA -w 2>/dev/null || echo "")
[ -z "$PAT" ] && PAT="${GITHUB_PAT_SPA:-${SPA_GITHUB_PAT:-}}"
[ -z "$PAT" ] && [ -f ~/.github_pat ] && PAT=$(cat ~/.github_pat)
[ -z "$PAT" ] && { echo "PAT not found — run: bash setup_pat.sh"; exit 1; }

cd ~/Documents/SPA_Claude
echo "SPA Push v8.14 — LendingUtilizationElasticity + CrossChainYieldBasisRisk + tests + registry + KANBAN + sprint_log"
python3 push_to_github.py --files $FILES --message "$COMMIT_MSG" --pat "$PAT"
echo "Push v8.14 complete!"
