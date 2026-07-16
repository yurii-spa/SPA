#!/bin/bash
# SPA Push — P2-3 /api/agents endpoint + P3-2 Telegram agent-down alerts
#
# Pushes:
#   * spa_core/family_fund/http_server.py     — new GET /api/agents endpoint
#                                               (reads data/uptime_status.json,
#                                               marks stale when >10 min old)
#   * spa_core/monitoring/uptime_monitor.py   — Telegram down-alert on
#                                               running→down transition,
#                                               rate-limited 1/h per agent,
#                                               state in data/uptime_prev_state.json
#   * tests/test_uptime_alerts.py             — 5 tests for the alert logic
#
# SECURITY: PAT is read from macOS Keychain (service: GITHUB_PAT_SPA).
# DO NOT embed PAT or any credentials in this file.
#
# Usage: bash ~/Documents/SPA_Claude/scripts/push_p2_improvements.sh

set -e

COMMIT_MSG="feat: /api/agents endpoint, Telegram downtime alerts for agent monitoring"

FILES="/Users/yuriikulieshov/Documents/SPA_Claude/spa_core/family_fund/http_server.py
/Users/yuriikulieshov/Documents/SPA_Claude/spa_core/monitoring/uptime_monitor.py
/Users/yuriikulieshov/Documents/SPA_Claude/tests/test_uptime_alerts.py"

# PAT resolution: Keychain → env GITHUB_PAT_SPA → env SPA_GITHUB_PAT → ~/.github_pat
PAT=$(security find-generic-password -s GITHUB_PAT_SPA -w 2>/dev/null || echo "")
[ -z "$PAT" ] && PAT="${GITHUB_PAT_SPA:-${SPA_GITHUB_PAT:-}}"
[ -z "$PAT" ] && [ -f ~/.github_pat ] && PAT=$(cat ~/.github_pat)
[ -z "$PAT" ] && { echo "PAT not found — run: bash setup_pat.sh"; exit 1; }

cd ~/Documents/SPA_Claude
echo "SPA Push — P2-3 /api/agents + P3-2 Telegram agent-down alerts"
python3 push_to_github.py --files $FILES --message "$COMMIT_MSG" --pat "$PAT"
echo "Push P2 improvements complete!"
