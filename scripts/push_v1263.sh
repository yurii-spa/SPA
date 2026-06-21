#!/usr/bin/env bash
# Push MP-1263 — T2 aggregate concentration early-warning monitor
#   * spa_core/risk/concentration_monitor.py  (tiered 42/45/50% alerts, advisory)
#   * cycle_runner integration (smart-modules step 6, fail-safe)
#   * tests/test_t2_concentration_alert.py     (23 tests)
# Absolute paths required (relative collapse to basename). PAT from Keychain.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"

python3 "$REPO_ROOT/push_to_github.py" \
  --files \
    "$REPO_ROOT/spa_core/risk/concentration_monitor.py" \
    "$REPO_ROOT/spa_core/paper_trading/cycle_runner.py" \
    "$REPO_ROOT/tests/test_t2_concentration_alert.py" \
    "$REPO_ROOT/scripts/push_v1263.sh" \
  --message "MP-1263 — T2 concentration early-warning (42/45/50% tiered alerts), 23 tests"
