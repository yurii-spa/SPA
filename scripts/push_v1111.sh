#!/usr/bin/env bash
# scripts/push_v1111.sh
# Sprint v11.11 — MP-1495: Walk-forward validation engine (30 tests)
# Commit: "Sprint v11.11 — MP-1495 Walk-forward validation engine (30 tests)"
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$REPO_ROOT"

echo "=== Sprint v11.11 — MP-1495 push ==="
echo "Root: $REPO_ROOT"

echo ""
echo "--- Running tests ---"
python3 -m unittest tests.test_walk_forward_validator -v 2>&1 | tail -5
echo ""

python3 push_to_github.py \
  --files \
    "$REPO_ROOT/spa_core/backtesting/walk_forward_validator.py" \
    "$REPO_ROOT/tests/test_walk_forward_validator.py" \
    "$REPO_ROOT/scripts/push_v1111.sh" \
    "$REPO_ROOT/KANBAN.json" \
  --message "Sprint v11.11 — MP-1495 Walk-forward validation engine (30 tests)"

echo ""
echo "=== push_v1111.sh DONE ==="
