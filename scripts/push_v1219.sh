#!/usr/bin/env bash
# FIX 3 (P1) — Single source of limits: allocator reads caps from policy.py
# Fixes: allocator.py T1_CAP/T2_CAP/TVL_FLOOR_USD/T2_TOTAL_CAP from RiskConfig()
#         test_p1_single_source_limits.py (15 tests)
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

python3 "${REPO_ROOT}/push_to_github.py" \
  --files \
    "${REPO_ROOT}/spa_core/allocator/allocator.py" \
    "${REPO_ROOT}/tests/test_p1_single_source_limits.py" \
    "${REPO_ROOT}/scripts/push_v1219.sh" \
  --message "FIX-P1: allocator limits read from RiskConfig (policy.py) — single source of truth"
