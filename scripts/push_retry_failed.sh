#!/bin/bash
# push_retry_failed.sh — re-push failed scripts + all new ones from this session
# Run: bash ~/Documents/SPA_Claude/scripts/push_retry_failed.sh

set -euo pipefail
SCRIPTS_DIR="$(dirname "$0")"

PAT=$(security find-generic-password -s GITHUB_PAT_SPA -w 2>/dev/null || echo "")
[ -z "$PAT" ] && PAT="${GITHUB_PAT_SPA:-${SPA_GITHUB_PAT:-}}"
[ -z "$PAT" ] && [ -f ~/.github_pat ] && PAT=$(cat ~/.github_pat)
[ -z "$PAT" ] && { echo "❌ PAT не найден"; exit 1; }
export GITHUB_PAT_SPA="$PAT"
echo "✅ PAT resolved"

SCRIPTS=(
  push_v699.sh
  push_v701.sh
  push_v742.sh
  push_v747.sh
  push_v749.sh
  push_v750.sh
  push_v753.sh
  push_v754.sh
  push_v755.sh
  push_v756.sh
  push_v757.sh
  push_v758.sh
  push_v759.sh
  push_v760.sh
  push_v761.sh
)

DONE=0; FAILED=0
for NAME in "${SCRIPTS[@]}"; do
  echo ""
  echo "🚀 $NAME ..."
  if bash "$SCRIPTS_DIR/$NAME" 2>&1; then
    echo "✅ $NAME pushed"
    DONE=$((DONE+1))
  else
    echo "❌ $NAME FAILED"
    FAILED=$((FAILED+1))
  fi
  sleep 1
done

echo ""
echo "==============================="
echo "✅ Done: $DONE | ❌ Failed: $FAILED"
