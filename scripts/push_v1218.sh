#!/usr/bin/env bash
# FIX 2 (P0) — _apply_risk_policy_gate fail-open → fail-closed
# Fixes: cycle_runner.py exception handler now sets approved=False + logs FAIL-CLOSED
#         test_p0_fail_closed.py (13 tests)
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

python3 "${REPO_ROOT}/push_to_github.py" \
  --files \
    "${REPO_ROOT}/spa_core/paper_trading/cycle_runner.py" \
    "${REPO_ROOT}/tests/test_p0_fail_closed.py" \
    "${REPO_ROOT}/scripts/push_v1218.sh" \
  --message "FIX-P0: risk gate fail-open → fail-closed; exception blocks trade (approved=False)"
