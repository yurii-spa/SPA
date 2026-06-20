#!/usr/bin/env bash
# Sprint v10.74 — MP-1458: Final GoLive Score 82/100 + Wave 7 push script + CURRENT_STATE v10.74
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"

python3 "$REPO_ROOT/push_to_github.py" \
  --files \
    "$REPO_ROOT/CURRENT_STATE.md" \
    "$REPO_ROOT/scripts/run_cpa_wave7_pushes.sh" \
    "$REPO_ROOT/_push_wave7.command" \
    "$REPO_ROOT/scripts/push_v1074.sh" \
    "$REPO_ROOT/data/golive_status.json" \
    "$REPO_ROOT/KANBAN.json" \
  --message "Sprint v10.74 — MP-1458 GoLive Score 82/100 achieved, Wave 7 push scripts, CURRENT_STATE v10.74 (evidence 15/25, infra 18/20)"
