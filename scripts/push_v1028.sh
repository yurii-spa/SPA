#!/usr/bin/env bash
# scripts/push_v1028.sh
# Sprint v10.28 — MP-1412: CURRENT_STATE v10.20 updated
# Commit: "Sprint v10.28 — MP-1412 CURRENT_STATE v10.20 updated"
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$REPO_ROOT"

echo "=== Sprint v10.28 — MP-1412 push ==="
echo "Root: $REPO_ROOT"
echo ""

python3 push_to_github.py \
  --files \
    "$REPO_ROOT/CURRENT_STATE.md" \
    "$REPO_ROOT/scripts/push_v1028.sh" \
    "$REPO_ROOT/KANBAN.json" \
  --message "Sprint v10.28 — MP-1412 CURRENT_STATE v10.20 updated"

echo ""
echo "✅ Sprint v10.28 pushed"
