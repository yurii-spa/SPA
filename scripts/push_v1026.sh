#!/usr/bin/env bash
# scripts/push_v1026.sh
# MP-1410 (v10.26) — Daily Cycle Evidence Hook + 30 tests
# Usage: bash scripts/push_v1026.sh

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"

python3 "$REPO_ROOT/push_to_github.py" \
  --files \
    "$REPO_ROOT/spa_core/backtesting/cpa_cycle_with_evidence.py" \
    "$REPO_ROOT/tests/test_cpa_cycle_evidence.py" \
    "$REPO_ROOT/scripts/push_v1026.sh" \
  --message "Sprint v10.26 — MP-1410 Daily cycle evidence hook, 30 tests"
