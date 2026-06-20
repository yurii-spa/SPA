#!/usr/bin/env bash
# scripts/push_v1132.sh
# Sprint v11.32 — MP-1516 Operations RUNBOOK (600+ words)
# Commit: "Sprint v11.32 — MP-1516 Operations RUNBOOK (600+ words)"
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$REPO_ROOT"

echo "=== Sprint v11.32 — MP-1516 push ==="
echo "Root: $REPO_ROOT"

echo ""
echo "--- Running tests ---"
python3 -m unittest tests.test_runbook_exists -v 2>&1 | tail -10
echo ""

python3 push_to_github.py \
  --files \
    "$REPO_ROOT/docs/RUNBOOK.md" \
    "$REPO_ROOT/tests/test_runbook_exists.py" \
    "$REPO_ROOT/scripts/push_v1132.sh" \
    "$REPO_ROOT/KANBAN.json" \
  --message "Sprint v11.32 — MP-1516 Operations RUNBOOK (600+ words)"

echo ""
echo "=== push_v1132.sh DONE ==="
