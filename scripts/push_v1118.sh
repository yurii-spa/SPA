#!/usr/bin/env bash
set -euo pipefail
REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
python3 "$REPO_ROOT/push_to_github.py" \
  --files \
    "$REPO_ROOT/index.html" \
    "$REPO_ROOT/scripts/push_v1118.sh" \
  --message "Sprint v11.18 — MP-1502 Risk monitor dashboard panel"
