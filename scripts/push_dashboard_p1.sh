#!/bin/bash
COMMIT_MSG="fix(dashboard): P1 — hide 6 tabs on public, fix lang switcher"
FILES="/Users/yuriikulieshov/Documents/SPA_Claude/index.html"
PAT=$(security find-generic-password -s GITHUB_PAT_SPA -w 2>/dev/null || echo "")
[ -z "$PAT" ] && PAT="${GITHUB_PAT_SPA:-${SPA_GITHUB_PAT:-}}"
[ -z "$PAT" ] && [ -f ~/.github_pat ] && PAT=$(cat ~/.github_pat)
[ -z "$PAT" ] && { echo "❌ PAT не найден"; exit 1; }
cd "$(dirname "$0")/.." || exit 1
python3 push_to_github.py --files $FILES --message "$COMMIT_MSG"
