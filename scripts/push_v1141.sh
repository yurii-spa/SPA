#!/usr/bin/env bash
# scripts/push_v1141.sh
# Sprint v11.41 — MP-1525 Backup + restore scripts (20 tests)
# Commit: "Sprint v11.41 — MP-1525 Backup + restore scripts (20 tests)"
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$REPO_ROOT"

echo "=== Sprint v11.41 — MP-1525 push ==="
echo "Root: $REPO_ROOT"

echo ""
echo "--- Running tests ---"
python3 -m unittest tests.test_backup_restore -v 2>&1 | tail -10
echo ""

python3 push_to_github.py \
  --files \
    "$REPO_ROOT/scripts/backup_spa_data.py" \
    "$REPO_ROOT/scripts/restore_spa_data.py" \
    "$REPO_ROOT/tests/test_backup_restore.py" \
    "$REPO_ROOT/scripts/push_v1141.sh" \
    "$REPO_ROOT/KANBAN.json" \
  --message "Sprint v11.41 — MP-1525 Backup + restore scripts (20 tests)"

echo ""
echo "=== push_v1141.sh DONE ==="
