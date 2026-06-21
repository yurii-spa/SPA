#!/usr/bin/env bash
# scripts/git_push.sh — правильный git push через PAT из Keychain.
# Использование: bash scripts/git_push.sh "commit message"
# Заменяет push_to_github.py для новых коммитов.
#
# Что делает:
#   git add -A → git commit → git push
# PAT берёт из Keychain (GITHUB_PAT_SPA).
# Не дублирует коммиты, не конфликтует с remote.

set -euo pipefail

REPO="$(cd "$(dirname "$0")/.." && pwd)"
MSG="${1:-"chore: auto-commit $(date +%Y-%m-%d)"}"

cd "$REPO"

# PAT из Keychain
PAT=$(security find-generic-password -s "GITHUB_PAT_SPA" -w 2>/dev/null || true)
if [ -z "$PAT" ]; then
    echo "❌ PAT not found in Keychain (GITHUB_PAT_SPA)"
    exit 1
fi

REMOTE_URL=$(git remote get-url origin)
# Inject PAT into URL
AUTH_URL=$(echo "$REMOTE_URL" | sed "s|https://|https://${PAT}@|")

# Check for changes
if git diff --quiet && git diff --cached --quiet && [ -z "$(git ls-files --others --exclude-standard)" ]; then
    echo "Nothing to commit."
    exit 0
fi

git add -A
git commit -m "$MSG"
git push "$AUTH_URL" HEAD:main

echo "✅ Pushed: $MSG"
