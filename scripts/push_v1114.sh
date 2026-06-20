#!/usr/bin/env bash
# scripts/push_v1114.sh
# Sprint v11.14 — MP-1498: Backtesting report generator (20 tests)
# Commit: "Sprint v11.14 — MP-1498 Backtest report generator (20 tests)"
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$REPO_ROOT"

echo "=== Sprint v11.14 — MP-1498 push ==="
echo "Root: $REPO_ROOT"

echo ""
echo "--- Running tests (all 4 sprints) ---"
python3 -m unittest \
  tests.test_walk_forward_validator \
  tests.test_monte_carlo \
  tests.test_backtest_paper_correlation \
  tests.test_backtest_report \
  -v 2>&1 | tail -10
echo ""

python3 push_to_github.py \
  --files \
    "$REPO_ROOT/spa_core/reporting/backtest_report.py" \
    "$REPO_ROOT/tests/test_backtest_report.py" \
    "$REPO_ROOT/scripts/push_v1114.sh" \
    "$REPO_ROOT/KANBAN.json" \
  --message "Sprint v11.14 — MP-1498 Backtest report generator (20 tests)"

echo ""
echo "=== push_v1114.sh DONE ==="
