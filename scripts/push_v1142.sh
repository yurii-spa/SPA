#!/usr/bin/env bash
# scripts/push_v1142.sh
# Sprint v11.42 — MP-1526 Wave 9 push script + CURRENT_STATE v11.42
# Commit: "Sprint v11.42 — MP-1526 Wave 9 push script + CURRENT_STATE v11.42"
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$REPO_ROOT"

echo "=== Sprint v11.42 — MP-1526 push ==="
echo "Root: $REPO_ROOT"

echo ""
echo "--- KANBAN check ---"
python3 -c "
import json
with open('KANBAN.json') as f: k=json.load(f)
print(f'done_count={k[\"done_count\"]}, sprint_completed={k[\"sprint_completed\"]}')
"
echo ""

python3 push_to_github.py \
  --files \
    "$REPO_ROOT/scripts/run_cpa_wave9_pushes.sh" \
    "$REPO_ROOT/_push_wave9.command" \
    "$REPO_ROOT/CURRENT_STATE.md" \
    "$REPO_ROOT/KANBAN.json" \
    "$REPO_ROOT/scripts/push_v1142.sh" \
  --message "Sprint v11.42 — MP-1526 Wave 9 push script + CURRENT_STATE v11.42"

echo ""
echo "=== push_v1142.sh DONE ==="
