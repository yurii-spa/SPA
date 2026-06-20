#!/usr/bin/env bash
# FIX 5 (P1) — Close in_progress KANBAN tickets P1-FIX-002 and P1-FIX-003
# P1-FIX-002: cycle_health_monitor already reads paper_trading_status.json (confirmed)
# P1-FIX-003: analytics_report_full.json exists (signal_aggregator already ran)
# KANBAN.json: both tickets moved to 'done'
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

python3 "${REPO_ROOT}/push_to_github.py" \
  --files \
    "${REPO_ROOT}/KANBAN.json" \
    "${REPO_ROOT}/scripts/push_v1221.sh" \
  --message "FIX-P1: close P1-FIX-002 (cycle_health_monitor) + P1-FIX-003 (analytics_tier_c) in KANBAN"
