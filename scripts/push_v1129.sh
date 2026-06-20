#!/usr/bin/env bash
# Sprint v11.29 — MP-1513: Demotion engine (20 tests)
set -euo pipefail
REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$REPO_ROOT"

python3 push_to_github.py \
  --files \
    "$REPO_ROOT/spa_core/backtesting/demotion_engine.py" \
    "$REPO_ROOT/tests/test_demotion_engine.py" \
    "$REPO_ROOT/scripts/push_v1129.sh" \
  --message "Sprint v11.29 — MP-1513 Demotion engine (20 tests)"
