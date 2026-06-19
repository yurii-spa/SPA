#!/usr/bin/env bash
# Push Sprint v10.20 — MP-1404 Dead code scanner v2
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"

python3 "$REPO_ROOT/push_to_github.py" \
  --files \
    "$REPO_ROOT/scripts/dead_code_scanner.py" \
    "$REPO_ROOT/tests/test_dead_code_scanner.py" \
    "$REPO_ROOT/scripts/push_v1019.sh" \
    "$REPO_ROOT/scripts/push_v1020.sh" \
    "$REPO_ROOT/KANBAN.json" \
  --message "Sprint v10.20 — MP-1404 Dead code scanner v2, 31 tests"
