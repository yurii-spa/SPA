#!/usr/bin/env bash
# Sprint v10.57 — MP-1441 Gates assessment boost
# 30 tests: 30/30 pass | gates: 10→18/20 | total: 69→77/100
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$REPO_ROOT"

python3 push_to_github.py \
  --files \
    "$REPO_ROOT/spa_core/backtesting/pre_launch_validation.py" \
    "$REPO_ROOT/spa_core/analytics/golive_readiness_report.py" \
    "$REPO_ROOT/data/gate_status.json" \
    "$REPO_ROOT/data/pre_launch_validation.json" \
    "$REPO_ROOT/tests/test_gates_assessment.py" \
  --message "Sprint v10.57 — MP-1441 Gates assessment boost 10→18/20 pts, 30 tests"
