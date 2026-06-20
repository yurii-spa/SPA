#!/usr/bin/env bash
# scripts/push_v1249.sh
# MP-1249 — Portfolio Optimizer (grid search over historical APY) + 35 tests
# Usage: bash scripts/push_v1249.sh

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"

python3 "$REPO_ROOT/push_to_github.py" \
  --files \
    "$REPO_ROOT/spa_core/analytics/portfolio_optimizer.py" \
    "$REPO_ROOT/data/optimizer_results.json" \
    "$REPO_ROOT/tests/test_portfolio_optimizer.py" \
    "$REPO_ROOT/scripts/push_v1249.sh" \
  --message "MP-1249 — Portfolio Optimizer (grid search, optimal allocation) + 35 tests"
