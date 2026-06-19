#!/usr/bin/env bash
# scripts/push_v1027.sh
# Sprint v10.27 — MP-1411: Wave 4 consolidated push script (v10.7-v10.28)
# Commit: "Sprint v10.27 — MP-1411 Wave 4 consolidated push script (v10.7-v10.28)"
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$REPO_ROOT"

echo "=== Sprint v10.27 — MP-1411 push ==="
echo "Root: $REPO_ROOT"
echo ""

python3 push_to_github.py \
  --files \
    "$REPO_ROOT/scripts/run_cpa_wave4_pushes.sh" \
    "$REPO_ROOT/_push_wave4.command" \
    "$REPO_ROOT/scripts/push_v1027.sh" \
    "$REPO_ROOT/KANBAN.json" \
  --message "Sprint v10.27 — MP-1411 Wave 4 consolidated push script (v10.7-v10.28)"

echo ""
echo "✅ Sprint v10.27 pushed"
