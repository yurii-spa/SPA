#!/usr/bin/env bash
# Sprint v11.28 — MP-1512: Tournament runner v2 with Sharpe ranking (25 tests)
set -euo pipefail
REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$REPO_ROOT"

python3 push_to_github.py \
  --files \
    "$REPO_ROOT/spa_core/backtesting/tournament_runner_v2.py" \
    "$REPO_ROOT/tests/test_tournament_runner_v2.py" \
    "$REPO_ROOT/scripts/push_v1128.sh" \
  --message "Sprint v11.28 — MP-1512 Tournament runner v2 with Sharpe ranking (25 tests)"
