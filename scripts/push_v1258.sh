#!/usr/bin/env bash
# Sprint v12.26 — MP-1581 APY spike monitor (yield-spike detection), 26 tests
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

python3 "${REPO_ROOT}/push_to_github.py" \
  --files \
    "${REPO_ROOT}/spa_core/alerts/apy_spike_monitor.py" \
    "${REPO_ROOT}/tests/test_apy_spike_monitor.py" \
    "${REPO_ROOT}/scripts/push_v1258.sh" \
    "${REPO_ROOT}/KANBAN.json" \
  --message "Sprint v12.26 — MP-1581 APY spike monitor (yield-spike detection), 26 tests"
