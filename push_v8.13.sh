#!/bin/bash
# Push script for Sprint v8.13 — MP-1108 + MP-1109
# DO NOT RUN FROM SANDBOX — requires macOS Keychain for PAT
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")" && pwd)"

python3 "$REPO_ROOT/push_to_github.py" \
  --files \
    "$REPO_ROOT/spa_core/analytics/defi_protocol_insurance_fund_adequacy_analyzer.py" \
    "$REPO_ROOT/spa_core/tests/test_defi_protocol_insurance_fund_adequacy_analyzer.py" \
    "$REPO_ROOT/spa_core/analytics/defi_protocol_yield_harvesting_frequency_optimizer.py" \
    "$REPO_ROOT/spa_core/tests/test_defi_protocol_yield_harvesting_frequency_optimizer.py" \
    "$REPO_ROOT/KANBAN.json" \
  --message "sprint v8.13: MP-1108 InsuranceFundAdequacyAnalyzer (67t) + MP-1109 YieldHarvestingFrequencyOptimizer (64t) — 131 tests GREEN"
