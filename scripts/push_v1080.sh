#!/usr/bin/env bash
# Sprint v10.80 — MP-1464: Financial category complete 15/15 pts
set -e
REPO="$(cd "$(dirname "$0")/.." && pwd)"
python3 "$REPO/push_to_github.py" \
  --files \
    "$REPO/data/equity_curve_daily.json" \
    "$REPO/tests/test_financial_complete.py" \
    "$REPO/scripts/push_v1080.sh" \
  --message "Sprint v10.80 — MP-1464 Financial category complete 15/15 pts"
