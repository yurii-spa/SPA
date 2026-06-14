#!/bin/bash
# SPA Push — Uptime Monitor launchd-status fix
#
# Problem: uptime_monitor.py judged ALL launchd agents by a live PID. Periodic
# agents (StartInterval / StartCalendarInterval) exit between runs, so they have
# no PID while idle — which is NORMAL — yet were reported as FAIL (all 17 red).
#
# Fix: type-aware check_agent():
#   - KeepAlive daemons (httpserver, cloudflared, bot_commands) → live PID / TCP port
#   - Periodic agents → output-file freshness (check_agent_by_output, AGENT_OUTPUT_FILES)
#   + Added 18th agent com.spa.analytics_tier_c (uptime_monitor + agent_status.sh)
#   + 14 new tests (TestCheckAgentByOutput, TestCheckAgent)
#
# SECURITY: PAT is read from macOS Keychain (service: GITHUB_PAT_SPA).
# DO NOT embed PAT or any credentials in this file.
#
# Usage: bash ~/Documents/SPA_Claude/scripts/push_uptime_fix.sh

set -e

COMMIT_MSG="fix: uptime_monitor fallback to output-file age check for launchd status"

FILES="/Users/yuriikulieshov/Documents/SPA_Claude/spa_core/monitoring/uptime_monitor.py
/Users/yuriikulieshov/Documents/SPA_Claude/scripts/agent_status.sh
/Users/yuriikulieshov/Documents/SPA_Claude/spa_core/tests/test_uptime_monitor.py
/Users/yuriikulieshov/Documents/SPA_Claude/scripts/push_uptime_fix.sh"

# PAT resolution: Keychain → env GITHUB_PAT_SPA → env SPA_GITHUB_PAT → ~/.github_pat
PAT=$(security find-generic-password -s GITHUB_PAT_SPA -w 2>/dev/null || echo "")
[ -z "$PAT" ] && PAT="${GITHUB_PAT_SPA:-${SPA_GITHUB_PAT:-}}"
[ -z "$PAT" ] && [ -f ~/.github_pat ] && PAT=$(cat ~/.github_pat)
[ -z "$PAT" ] && { echo "PAT not found — run: bash setup_pat.sh"; exit 1; }

cd ~/Documents/SPA_Claude
echo "SPA Push — Uptime Monitor launchd-status fix"
python3 push_to_github.py --files $FILES --message "$COMMIT_MSG" --pat "$PAT"
echo "Push uptime_fix complete!"
