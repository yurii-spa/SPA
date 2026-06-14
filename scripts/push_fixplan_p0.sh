#!/bin/bash
# Push P0 dashboard fixes to GitHub:
#   P0-1 canonical dates, P0-2 localhost guards, P0-3 freshness badge
# Usage: bash scripts/push_fixplan_p0.sh

COMMIT_MSG="fix(dashboard): P0 fixes — canonical dates, localhost guards, freshness badge"

FILES="/Users/yuriikulieshov/Documents/SPA_Claude/index.html \
/Users/yuriikulieshov/Documents/SPA_Claude/data/meta.json"

# --- PAT resolution (Keychain → env → ~/.github_pat) ---
PAT=$(security find-generic-password -s GITHUB_PAT_SPA -w 2>/dev/null || echo "")
[ -z "$PAT" ] && PAT="${GITHUB_PAT_SPA:-${SPA_GITHUB_PAT:-}}"
[ -z "$PAT" ] && [ -f ~/.github_pat ] && PAT=$(cat ~/.github_pat)
[ -z "$PAT" ] && { echo "❌ PAT не найден — добавьте через: bash setup_pat.sh"; exit 1; }

cd "$(dirname "$0")/.." || exit 1

python3 push_to_github.py --files $FILES --message "$COMMIT_MSG"
