#!/usr/bin/env bash
set -euo pipefail
REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
python3 "$REPO_ROOT/push_to_github.py" \
  --files \
    "$REPO_ROOT/spa_core/analytics/var_calculator.py" \
    "$REPO_ROOT/tests/test_var_calculator.py" \
    "$REPO_ROOT/scripts/push_v1115.sh" \
  --message "Sprint v11.15 — MP-1499 VaR + CVaR calculator (30 tests)"
