#!/usr/bin/env bash
# scripts/push_v1140.sh
# Sprint v11.40 — MP-1524 System health check diagnostic (20 tests)
# Commit: "Sprint v11.40 — MP-1524 System health check diagnostic (20 tests)"
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$REPO_ROOT"

echo "=== Sprint v11.40 — MP-1524 push ==="
echo "Root: $REPO_ROOT"

echo ""
echo "--- Running tests ---"
python3 -m unittest tests.test_system_health_check -v 2>&1 | tail -10
echo ""

python3 push_to_github.py \
  --files \
    "$REPO_ROOT/scripts/system_health_check.py" \
    "$REPO_ROOT/tests/test_system_health_check.py" \
    "$REPO_ROOT/scripts/push_v1140.sh" \
    "$REPO_ROOT/KANBAN.json" \
  --message "Sprint v11.40 — MP-1524 System health check diagnostic (20 tests)"

echo ""
echo "=== push_v1140.sh DONE ==="
