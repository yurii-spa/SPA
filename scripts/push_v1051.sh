#!/usr/bin/env bash
# scripts/push_v1051.sh
# Sprint v10.51 — MP-1435: Wave 5 consolidated push script (v10.29-v10.50)
# Commit: "Sprint v10.51 — MP-1435 Wave 5 consolidated push script (v10.29-v10.50)"
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$REPO_ROOT"

echo "=== Sprint v10.51 — MP-1435 push ==="
echo "Root: $REPO_ROOT"
echo ""

python3 push_to_github.py \
  --files \
    "$REPO_ROOT/scripts/run_cpa_wave5_pushes.sh" \
    "$REPO_ROOT/_push_wave5.command" \
    "$REPO_ROOT/scripts/push_v1051.sh" \
    "$REPO_ROOT/KANBAN.json" \
  --message "Sprint v10.51 — MP-1435 Wave 5 consolidated push script (v10.29-v10.50)"

echo ""
echo "✅ Sprint v10.51 pushed"
