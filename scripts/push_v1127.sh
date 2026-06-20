#!/usr/bin/env bash
# Sprint v11.27 — MP-1511: S20 Curve/Convex + S21 Aave Loop strategies (30 tests)
set -euo pipefail
REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$REPO_ROOT"

python3 push_to_github.py \
  --files \
    "$REPO_ROOT/spa_core/strategies/s20_curve_convex.py" \
    "$REPO_ROOT/spa_core/strategies/s21_aave_loop.py" \
    "$REPO_ROOT/tests/test_s20_s21_strategies.py" \
    "$REPO_ROOT/scripts/push_v1127.sh" \
  --message "Sprint v11.27 — MP-1511 S20 Curve/Convex + S21 Aave Loop strategies (30 tests)"
