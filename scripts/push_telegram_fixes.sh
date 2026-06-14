#!/bin/bash
COMMIT_MSG="fix(telegram): stale alert filter (>24h), bot_commands launchd plist, install script"
FILES="spa_core/alerts/red_flag_monitor.py \
launchd/com.spa.bot_commands.plist \
scripts/install_bot_commands.sh"
PAT=$(security find-generic-password -s GITHUB_PAT_SPA -w 2>/dev/null || echo "")
[ -z "$PAT" ] && PAT="${GITHUB_PAT_SPA:-${SPA_GITHUB_PAT:-}}"
[ -z "$PAT" ] && [ -f ~/.github_pat ] && PAT=$(cat ~/.github_pat)
[ -z "$PAT" ] && { echo "❌ PAT не найден"; exit 1; }
cd "$(dirname "$0")/.." || exit 1
python3 push_to_github.py --files $FILES --message "$COMMIT_MSG" --pat "$PAT"
