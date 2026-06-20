#!/usr/bin/env bash
# scripts/push_v1112.sh
# Sprint v11.12 — MP-1496: Monte Carlo simulation for strategy robustness (30 tests)
# Commit: "Sprint v11.12 — MP-1496 Monte Carlo simulation (30 tests)"
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$REPO_ROOT"

echo "=== Sprint v11.12 — MP-1496 push ==="
echo "Root: $REPO_ROOT"

echo ""
echo "--- Running tests ---"
python3 -m unittest tests.test_monte_carlo -v 2>&1 | tail -5
echo ""

python3 push_to_github.py \
  --files \
    "$REPO_ROOT/spa_core/analytics/monte_carlo.py" \
    "$REPO_ROOT/tests/test_monte_carlo.py" \
    "$REPO_ROOT/scripts/push_v1112.sh" \
    "$REPO_ROOT/KANBAN.json" \
  --message "Sprint v11.12 — MP-1496 Monte Carlo simulation (30 tests)"

echo ""
echo "=== push_v1112.sh DONE ==="
