#!/usr/bin/env bash
# Sprint v10.81 — MP-1465: Paper trading evidence tracker in dashboard
set -e
REPO="$(cd "$(dirname "$0")/.." && pwd)"
python3 "$REPO/push_to_github.py" \
  --files \
    "$REPO/landing/src/pages/dashboard.astro" \
    "$REPO/scripts/push_v1081.sh" \
  --message "Sprint v10.81 — MP-1465 Paper trading evidence tracker in dashboard"
