#!/usr/bin/env bash
# scripts/push_v1052.sh
# Sprint v10.52 — MP-1436: CURRENT_STATE v10.50 + Audit Closure Report
# Commit: "Sprint v10.52 — MP-1436 CURRENT_STATE v10.50 + Audit Closure Report"
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$REPO_ROOT"

echo "=== Sprint v10.52 — MP-1436 push ==="
echo "Root: $REPO_ROOT"
echo ""

python3 push_to_github.py \
  --files \
    "$REPO_ROOT/CURRENT_STATE.md" \
    "$REPO_ROOT/docs/AUDIT_CLOSURE_REPORT_20260619.md" \
    "$REPO_ROOT/scripts/push_v1052.sh" \
    "$REPO_ROOT/KANBAN.json" \
  --message "Sprint v10.52 — MP-1436 CURRENT_STATE v10.50 + Audit Closure Report"

echo ""
echo "✅ Sprint v10.52 pushed"
