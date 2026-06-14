#!/bin/bash
# Push script for Sprint v8.12 — MP-1106 + MP-1107
# DO NOT RUN FROM SANDBOX — requires macOS Keychain for PAT
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")" && pwd)"

python3 "$REPO_ROOT/push_to_github.py" \
  --files \
    "$REPO_ROOT/spa_core/analytics/defi_protocol_mev_protection_effectiveness_analyzer.py" \
    "$REPO_ROOT/spa_core/tests/test_defi_protocol_mev_protection_effectiveness_analyzer.py" \
    "$REPO_ROOT/spa_core/analytics/defi_protocol_borrower_concentration_risk_analyzer.py" \
    "$REPO_ROOT/spa_core/tests/test_defi_protocol_borrower_concentration_risk_analyzer.py" \
    "$REPO_ROOT/KANBAN.json" \
  --message "sprint v8.12: MP-1106 MEVProtectionEffectivenessAnalyzer (73t) + MP-1107 BorrowerConcentrationRiskAnalyzer (68t) — 141 tests GREEN"
