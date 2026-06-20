#!/usr/bin/env bash
# Sprint v10.89 — MP-1473: Landing site comprehensive review + status page
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"

python3 "$REPO_ROOT/push_to_github.py" \
  --files \
    "$REPO_ROOT/landing/src/pages/status.astro" \
    "$REPO_ROOT/scripts/push_v1089.sh" \
  --message "Sprint v10.89 — MP-1473 Landing site comprehensive review + status page"
