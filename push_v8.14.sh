#!/bin/bash
# Push script for Sprint v8.14 — MP-1110 + MP-1111
# DO NOT RUN FROM SANDBOX — requires macOS Keychain for PAT
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")" && pwd)"

python3 "$REPO_ROOT/push_to_github.py" \
  --files \
    "$REPO_ROOT/spa_core/analytics/defi_protocol_lending_utilization_elasticity_analyzer.py" \
    "$REPO_ROOT/spa_core/tests/test_defi_protocol_lending_utilization_elasticity_analyzer.py" \
    "$REPO_ROOT/spa_core/analytics/defi_protocol_cross_chain_yield_basis_risk_analyzer.py" \
    "$REPO_ROOT/spa_core/tests/test_defi_protocol_cross_chain_yield_basis_risk_analyzer.py" \
    "$REPO_ROOT/KANBAN.json" \
  --message "sprint v8.14: MP-1110 LendingUtilizationElasticityAnalyzer (67t) + MP-1111 CrossChainYieldBasisRiskAnalyzer (65t) — 132 tests GREEN"
