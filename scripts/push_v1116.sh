#!/usr/bin/env bash
set -euo pipefail
REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
python3 "$REPO_ROOT/push_to_github.py" \
  --files \
    "$REPO_ROOT/spa_core/safety/position_limit_enforcer.py" \
    "$REPO_ROOT/tests/test_position_limit_enforcer.py" \
    "$REPO_ROOT/scripts/push_v1116.sh" \
  --message "Sprint v11.16 — MP-1500 Position limit enforcer (25 tests)"
