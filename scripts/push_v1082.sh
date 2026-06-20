#!/usr/bin/env bash
# Sprint v10.82 — MP-1466: Telegram daily evidence report, 24 tests
set -e
REPO="$(cd "$(dirname "$0")/.." && pwd)"
python3 "$REPO/push_to_github.py" \
  --files \
    "$REPO/spa_core/alerts/daily_evidence_report.py" \
    "$REPO/tests/test_daily_evidence_report.py" \
    "$REPO/scripts/push_v1082.sh" \
  --message "Sprint v10.82 — MP-1466 Telegram daily evidence report, 24 tests"
