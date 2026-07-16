#!/bin/bash
# Push SPA Telegram Bot v2.0 — new module, tests, package init, updated plist.
COMMIT_MSG="feat: Telegram Bot v2.0 — 9 commands, polling, inline buttons, graceful errors"
FILES="spa_core/telegram/__init__.py \
spa_core/telegram/bot.py \
tests/test_telegram_bot_v2.py \
scripts/com.spa.bot_commands.plist"

PAT=$(security find-generic-password -s GITHUB_PAT_SPA -w 2>/dev/null || echo "")
[ -z "$PAT" ] && PAT="${GITHUB_PAT_SPA:-${SPA_GITHUB_PAT:-}}"
[ -z "$PAT" ] && [ -f ~/.github_pat ] && PAT=$(cat ~/.github_pat)
[ -z "$PAT" ] && { echo "❌ PAT не найден (GITHUB_PAT_SPA / env / ~/.github_pat)"; exit 1; }

cd "$(dirname "$0")/.." || exit 1
python3 push_to_github.py --files $FILES --message "$COMMIT_MSG" --pat "$PAT"
