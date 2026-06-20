#!/usr/bin/env bash
set -euo pipefail
REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
python3 "$REPO_ROOT/push_to_github.py" \
  --files \
    "$REPO_ROOT/docs/SPRINT_RETROSPECTIVE_v10.md" \
    "$REPO_ROOT/KANBAN.json" \
    "$REPO_ROOT/scripts/push_v1098.sh" \
  --message "Sprint v10.98 — MP-1482 Sprint retrospective + KANBAN cleanup"
