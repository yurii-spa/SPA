#!/bin/bash
# Push governance_watcher fix: retry + timeout + health-check fields.
# Restores live Snapshot/Tally fetch path and fixes the over-eager
# fallback_used flag (empty-but-healthy scans were wrongly marked fallback).

COMMIT_MSG="fix: governance_watcher retry+timeout; Snapshot live API restored"
FILES="spa_core/alerts/governance_watcher.py \
spa_core/tests/test_governance_watcher.py"

PAT=$(security find-generic-password -s GITHUB_PAT_SPA -w 2>/dev/null || echo "")
[ -z "$PAT" ] && PAT=$(security find-generic-password -s GITHUB_PAT -w 2>/dev/null || echo "")
[ -z "$PAT" ] && PAT="${GITHUB_PAT_SPA:-${SPA_GITHUB_PAT:-${GITHUB_PAT:-}}}"
[ -z "$PAT" ] && [ -f ~/.github_pat ] && PAT=$(cat ~/.github_pat)
[ -z "$PAT" ] && { echo "❌ PAT не найден"; exit 1; }

echo "📦 Pushing governance_watcher fix..."
cd "$(dirname "$0")/.." || exit 1
python3 push_to_github.py --files $FILES --message "$COMMIT_MSG" --pat "$PAT"
echo "✅ governance_watcher fix pushed"
