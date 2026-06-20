#!/usr/bin/env bash
# scripts/push_v1060.sh
# Sprint v10.60 — MP-1444: SPAError batch 4 final sweep + coverage report
# Result: 100% coverage (34/34 files), 0 bare Exception/RuntimeError remaining
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$REPO_ROOT"

echo "=== Sprint v10.60 — MP-1444 SPAError final sweep push ==="
echo "Root: $REPO_ROOT"
echo ""

python3 push_to_github.py \
  --files \
    "$REPO_ROOT/scripts/spaerror_coverage_report.sh" \
    "$REPO_ROOT/scripts/push_v1060.sh" \
    "$REPO_ROOT/KANBAN.json" \
  --message "Sprint v10.60 — MP-1444 SPAError batch 4 final sweep + coverage report"

echo ""
echo "✅ Sprint v10.60 pushed"
