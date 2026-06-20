#!/usr/bin/env bash
# Sprint v10.87 — MP-1471: Atomic batch 8 reporting+telegram+database
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"

python3 "$REPO_ROOT/push_to_github.py" \
  --files \
    "$REPO_ROOT/spa_core/utils/atomic.py" \
    "$REPO_ROOT/spa_core/reporting/tear_sheet.py" \
    "$REPO_ROOT/spa_core/reporting/pdf_report.py" \
    "$REPO_ROOT/spa_core/telegram/bot.py" \
    "$REPO_ROOT/spa_core/reports/investor_report.py" \
    "$REPO_ROOT/spa_core/tests/test_tear_sheet.py" \
    "$REPO_ROOT/spa_core/tests/test_pdf_report.py" \
    "$REPO_ROOT/spa_core/tests/test_investor_report.py" \
    "$REPO_ROOT/scripts/push_v1087.sh" \
  --message "Sprint v10.87 — MP-1471 Atomic batch 8 reporting+telegram+database"
