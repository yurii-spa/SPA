#!/usr/bin/env bash
# FIX 1 (P0) — Canonical paper-track start date 2026-06-10
# Fixes: progress_tracker.py _extract_paper_start + _count_real_paper_days,
#         golive/daily_check.py error-fallback date, test_p0_track_start.py (14 tests)
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

python3 "${REPO_ROOT}/push_to_github.py" \
  --files \
    "${REPO_ROOT}/spa_core/paper_trading/progress_tracker.py" \
    "${REPO_ROOT}/spa_core/golive/daily_check.py" \
    "${REPO_ROOT}/tests/test_p0_track_start.py" \
    "${REPO_ROOT}/scripts/push_v1217.sh" \
  --message "FIX-P0: canonical paper-track start 2026-06-10 in progress_tracker + golive fallback"
