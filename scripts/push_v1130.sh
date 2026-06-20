#!/usr/bin/env bash
# Sprint v11.30 — MP-1514: Strategy leaderboard dashboard + KANBAN update
set -euo pipefail
REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$REPO_ROOT"

python3 push_to_github.py \
  --files \
    "$REPO_ROOT/index.html" \
    "$REPO_ROOT/KANBAN.json" \
    "$REPO_ROOT/scripts/push_v1130.sh" \
  --message "Sprint v11.30 — MP-1514 Strategy leaderboard dashboard"
