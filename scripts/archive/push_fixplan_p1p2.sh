#!/bin/bash
# Push P1/P2 dashboard fixes to GitHub
# PAT is read from macOS Keychain — never embedded here

COMMIT_MSG="fix(dashboard): P1/P2 — language cleanup, dataBase dedup, touch tooltips, SPA name"
FILES="index.html"

PAT=$(security find-generic-password -s GITHUB_PAT_SPA -w 2>/dev/null || echo "")
[ -z "$PAT" ] && PAT="${GITHUB_PAT_SPA:-${SPA_GITHUB_PAT:-}}"
[ -z "$PAT" ] && [ -f ~/.github_pat ] && PAT=$(cat ~/.github_pat)
[ -z "$PAT" ] && { echo "❌ PAT не найден (Keychain: GITHUB_PAT_SPA)"; exit 1; }

cd "$(dirname "$0")/.." || exit 1
python3 push_to_github.py --files $FILES --message "$COMMIT_MSG"
