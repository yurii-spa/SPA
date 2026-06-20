#!/usr/bin/env bash
# scripts/push_v1113.sh
# Sprint v11.13 — MP-1497: Backtest-paper correlation tracker (25 tests)
# Commit: "Sprint v11.13 — MP-1497 Backtest-paper correlation tracker (25 tests)"
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$REPO_ROOT"

echo "=== Sprint v11.13 — MP-1497 push ==="
echo "Root: $REPO_ROOT"

echo ""
echo "--- Running tests ---"
python3 -m unittest tests.test_backtest_paper_correlation -v 2>&1 | tail -5
echo ""

python3 push_to_github.py \
  --files \
    "$REPO_ROOT/spa_core/backtesting/backtest_paper_correlation.py" \
    "$REPO_ROOT/tests/test_backtest_paper_correlation.py" \
    "$REPO_ROOT/scripts/push_v1113.sh" \
    "$REPO_ROOT/KANBAN.json" \
  --message "Sprint v11.13 — MP-1497 Backtest-paper correlation tracker (25 tests)"

echo ""
echo "=== push_v1113.sh DONE ==="
