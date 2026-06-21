#!/usr/bin/env bash
# scripts/push_v1264.sh
# v12.64 — S46–S50 income-generation strategy batch (registry → 50+ strategies)
#
#   S46 Stable-Only Safe Harbor   — 100% T1, no T2 ever (~3.8%, lowest risk)
#   S47 Monthly Income Optimizer  — predictability-weighted T1 (~3.9%, ~$322/mo)
#   S48 Utilization-Aware         — Aave-APY regime proxy (adaptive 4.2–4.8%)
#   S49 Diversified Maximum       — 7 venues, no single >20% (~4.4%)
#   S50 Tournament Champion       — meta: copies the current leader's weights
#
#   + shared _income_common.py helper, 42 tests in tests/test_s46_s50.py
#
# Usage: bash scripts/push_v1264.sh
#
# NOTE: never push scripts/cf_install_token.command (contains a tunnel token).

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"

python3 "$REPO_ROOT/push_to_github.py" \
  --files \
    "$REPO_ROOT/spa_core/strategies/_income_common.py" \
    "$REPO_ROOT/spa_core/strategies/s46_safe_harbor.py" \
    "$REPO_ROOT/spa_core/strategies/s47_monthly_income.py" \
    "$REPO_ROOT/spa_core/strategies/s48_utilization_aware.py" \
    "$REPO_ROOT/spa_core/strategies/s49_diversified_max.py" \
    "$REPO_ROOT/spa_core/strategies/s50_tournament_champion.py" \
    "$REPO_ROOT/spa_core/strategies/strategy_registry.py" \
    "$REPO_ROOT/tests/test_s46_s50.py" \
    "$REPO_ROOT/scripts/push_v1264.sh" \
  --message "v12.64 — S46–S50 income strategy batch (Safe Harbor/Monthly Income/Utilization-Aware/Diversified Max/Tournament Champion), 42 tests"
