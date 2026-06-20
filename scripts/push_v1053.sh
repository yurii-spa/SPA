#!/usr/bin/env bash
# scripts/push_v1053.sh
# Sprint v10.53 — MP-1437: Tests for 3 untested analytics modules, 61 tests
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$REPO_ROOT"

echo "=== Sprint v10.53 — MP-1437 push ==="
echo "Root: $REPO_ROOT"
echo ""

python3 push_to_github.py \
  --files \
    "$REPO_ROOT/tests/test_rebalance_cost_estimator.py" \
    "$REPO_ROOT/tests/test_yield_compressor_score.py" \
    "$REPO_ROOT/tests/test_yield_forecast_engine.py" \
    "$REPO_ROOT/scripts/push_v1053.sh" \
    "$REPO_ROOT/KANBAN.json" \
  --message "Sprint v10.53 — MP-1437 Tests for 3 untested analytics modules, 61 tests"

echo ""
echo "✅ Sprint v10.53 pushed"
