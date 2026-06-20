#!/usr/bin/env bash
# Sprint v10.66 — MP-1450: Wave 6 push script + CURRENT_STATE update
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"

python3 "$REPO_ROOT/push_to_github.py" \
  --files \
    "$REPO_ROOT/scripts/run_cpa_wave6_pushes.sh" \
    "$REPO_ROOT/_push_wave6.command" \
    "$REPO_ROOT/CURRENT_STATE.md" \
    "$REPO_ROOT/scripts/push_v1066.sh" \
    "$REPO_ROOT/KANBAN.json" \
  --message "Sprint v10.66 — MP-1450 Wave 6 push script + CURRENT_STATE v10.66 (BaseAnalytics Phase 4 43 classes, SPAError Batch 5 13 files)"
