#!/bin/bash
# SPA Push — Agent Fixes (AGENT_AUDIT.md backlog)
# AGT-P0-3  fix python interpreter in 2 plist files
# AGT-P0-4  consolidate autopush → auto_push.sh
# AGT-P0-6  cloudflared path (left as-is: cloudflared NOT installed)
# AGT-P1-1  uptime_monitor LAUNCHD_SERVICES → 17 agents
# AGT-P1-2  scripts/agent_status.sh
# AGT-P1-3  install_agents.sh → +daily-paper-report/weekly_backup/checkpoint-7day
#
# SECURITY: PAT is read from macOS Keychain (service: GITHUB_PAT_SPA).
# DO NOT embed PAT or any credentials in this file.
#
# Usage: bash ~/Documents/SPA_Claude/scripts/push_agent_fixes.sh

set -e

COMMIT_MSG="fix(agents): AGENT_AUDIT backlog — plist python paths (daily-paper-report, checkpoint-7day), autopush→auto_push.sh, uptime_monitor 17 services, agent_status.sh, install_agents.sh +3 daily/weekly/checkpoint plists"

FILES="/Users/yuriikulieshov/Documents/SPA_Claude/scripts/com.spa.daily-paper-report.plist
/Users/yuriikulieshov/Documents/SPA_Claude/scripts/com.spa.checkpoint-7day.plist
/Users/yuriikulieshov/Documents/SPA_Claude/scripts/com.spa.autopush.plist
/Users/yuriikulieshov/Documents/SPA_Claude/spa_core/monitoring/uptime_monitor.py
/Users/yuriikulieshov/Documents/SPA_Claude/scripts/agent_status.sh
/Users/yuriikulieshov/Documents/SPA_Claude/scripts/auto_push.sh
/Users/yuriikulieshov/Documents/SPA_Claude/scripts/install_agents.sh
/Users/yuriikulieshov/Documents/SPA_Claude/scripts/push_agent_fixes.sh"

# PAT resolution: Keychain → env GITHUB_PAT_SPA → env SPA_GITHUB_PAT → ~/.github_pat
PAT=$(security find-generic-password -s GITHUB_PAT_SPA -w 2>/dev/null || echo "")
[ -z "$PAT" ] && PAT="${GITHUB_PAT_SPA:-${SPA_GITHUB_PAT:-}}"
[ -z "$PAT" ] && [ -f ~/.github_pat ] && PAT=$(cat ~/.github_pat)
[ -z "$PAT" ] && { echo "PAT not found — run: bash setup_pat.sh"; exit 1; }

cd ~/Documents/SPA_Claude
echo "SPA Push — Agent Fixes (AGENT_AUDIT backlog)"
python3 push_to_github.py --files $FILES --message "$COMMIT_MSG" --pat "$PAT"
echo "Push agent_fixes complete!"
