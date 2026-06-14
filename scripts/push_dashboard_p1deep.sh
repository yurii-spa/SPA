#!/bin/bash
# Push dashboard P1-deep fixes:
# FIX-A: SPA naming (already was Stable Portfolio Agent)
# FIX-B: P2-3 skeleton loading + updatePendingMetrics
# FIX-C: P1-1 duplicate equity canvas hidden on is-public
# FIX-D: P1-1 Decisions block hidden in Ops tab on is-public
set -euo pipefail

COMMIT_MSG="fix(dashboard): P1-deep equity dedup, P2-3 skeletons/pending metrics, P2-5 SPA naming"
FILES="/Users/yuriikulieshov/Documents/SPA_Claude/index.html"

PAT=$(security find-generic-password -s GITHUB_PAT_SPA -w 2>/dev/null || true)
[ -z "$PAT" ] && PAT="${GITHUB_PAT_SPA:-${SPA_GITHUB_PAT:-}}"
[ -z "$PAT" ] && [ -f ~/.github_pat ] && PAT=$(cat ~/.github_pat)
if [ -z "$PAT" ]; then
  echo "❌ PAT не найден (keychain: GITHUB_PAT_SPA, env: GITHUB_PAT_SPA/SPA_GITHUB_PAT, ~/.github_pat)"
  exit 1
fi

cd "$(dirname "$0")/.." || exit 1
echo "▶ Pushing: $FILES"
python3 push_to_github.py --files $FILES --message "$COMMIT_MSG"
echo "✅ Done"
