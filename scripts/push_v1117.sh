#!/usr/bin/env bash
set -euo pipefail
REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
python3 "$REPO_ROOT/push_to_github.py" \
  --files \
    "$REPO_ROOT/spa_core/safety/drawdown_circuit_breaker.py" \
    "$REPO_ROOT/tests/test_drawdown_circuit_breaker.py" \
    "$REPO_ROOT/scripts/push_v1117.sh" \
  --message "Sprint v11.17 — MP-1501 Drawdown circuit breaker (25 tests)"
