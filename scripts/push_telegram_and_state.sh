#!/bin/bash
# SPA Push — Telegram bot plist + CURRENT_STATE.md + install_agents.sh + uptime_monitor
#
# Pushes:
#   * scripts/com.spa.bot_commands.plist   — launchd plist for the Telegram bot
#   * CURRENT_STATE.md                     — refreshed infra facts (autopush installed,
#                                            analytics_tier_c + bot_commands agents, 19 agents,
#                                            578 analytics modules, kill-switch inactive)
#   * scripts/install_agents.sh            — analytics_tier_c + bot_commands in AGENTS array
#   * spa_core/monitoring/uptime_monitor.py — monitor analytics_tier_c + bot_commands
#
# SECURITY: PAT is read from macOS Keychain (service: GITHUB_PAT_SPA).
# DO NOT embed PAT or any credentials in this file.
#
# Usage: bash ~/Documents/SPA_Claude/scripts/push_telegram_and_state.sh

set -e

COMMIT_MSG="feat: Telegram bot plist; update CURRENT_STATE.md; analytics_tier_c in install"

FILES="/Users/yuriikulieshov/Documents/SPA_Claude/scripts/com.spa.bot_commands.plist
/Users/yuriikulieshov/Documents/SPA_Claude/CURRENT_STATE.md
/Users/yuriikulieshov/Documents/SPA_Claude/scripts/install_agents.sh
/Users/yuriikulieshov/Documents/SPA_Claude/spa_core/monitoring/uptime_monitor.py"

# PAT resolution: Keychain → env GITHUB_PAT_SPA → env SPA_GITHUB_PAT → ~/.github_pat
PAT=$(security find-generic-password -s GITHUB_PAT_SPA -w 2>/dev/null || echo "")
[ -z "$PAT" ] && PAT="${GITHUB_PAT_SPA:-${SPA_GITHUB_PAT:-}}"
[ -z "$PAT" ] && [ -f ~/.github_pat ] && PAT=$(cat ~/.github_pat)
[ -z "$PAT" ] && { echo "PAT not found — run: bash setup_pat.sh"; exit 1; }

cd ~/Documents/SPA_Claude
echo "SPA Push — Telegram bot plist + CURRENT_STATE.md + install_agents.sh + uptime_monitor"
python3 push_to_github.py --files $FILES --message "$COMMIT_MSG" --pat "$PAT"
echo "Push Telegram + state complete!"
