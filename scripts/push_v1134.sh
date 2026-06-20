#!/usr/bin/env bash
# scripts/push_v1134.sh
# Sprint v11.34 — MP-1518 Engineering changelog + generator script
# Commit: "Sprint v11.34 — MP-1518 Engineering changelog + generator script"
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$REPO_ROOT"

echo "=== Sprint v11.34 — MP-1518 push ==="
echo "Root: $REPO_ROOT"

echo ""
echo "--- Running tests ---"
python3 -m unittest tests.test_changelog_generator -v 2>&1 | tail -10
echo ""

python3 push_to_github.py \
  --files \
    "$REPO_ROOT/docs/CHANGELOG_ENGINEERING.md" \
    "$REPO_ROOT/scripts/generate_changelog.py" \
    "$REPO_ROOT/tests/test_changelog_generator.py" \
    "$REPO_ROOT/scripts/push_v1134.sh" \
    "$REPO_ROOT/KANBAN.json" \
  --message "Sprint v11.34 — MP-1518 Engineering changelog + generator script"

echo ""
echo "=== push_v1134.sh DONE ==="
