#!/bin/bash
# run_all_pushes.sh — Sequential push runner for all pending push_vNNN.sh scripts
# Reads PAT from Keychain (GITHUB_PAT_SPA) → env → ~/.github_pat
# NEVER embeds PAT

set -euo pipefail
SCRIPTS_DIR="$(dirname "$0")"
LOG="$SCRIPTS_DIR/.push_log"
FAILED_LOG="$SCRIPTS_DIR/.push_failed"

# Resolve PAT once
PAT=$(security find-generic-password -s GITHUB_PAT_SPA -w 2>/dev/null || echo "")
[ -z "$PAT" ] && PAT="${GITHUB_PAT_SPA:-${SPA_GITHUB_PAT:-}}"
[ -z "$PAT" ] && [ -f ~/.github_pat ] && PAT=$(cat ~/.github_pat)
[ -z "$PAT" ] && { echo "❌ PAT не найден — запусти: security add-generic-password -s GITHUB_PAT_SPA -a spa -w YOUR_PAT"; exit 1; }

echo "✅ PAT resolved from Keychain"
echo "📋 Push log: $LOG"

# Touch log files
touch "$LOG" "$FAILED_LOG"

# Get all push scripts, sorted numerically
ALL_SCRIPTS=$(ls "$SCRIPTS_DIR"/push_v*.sh 2>/dev/null | sort -t v -k2 -n)
TOTAL=$(echo "$ALL_SCRIPTS" | wc -l | tr -d ' ')
DONE=0
SKIPPED=0
FAILED=0

echo "📦 Found $TOTAL push scripts"
echo "============================================"

for SCRIPT in $ALL_SCRIPTS; do
  NAME=$(basename "$SCRIPT")
  
  # Skip if already pushed
  if grep -qF "$NAME" "$LOG" 2>/dev/null; then
    echo "⏭️  SKIP $NAME (already pushed)"
    SKIPPED=$((SKIPPED+1))
    continue
  fi
  
  echo ""
  echo "🚀 Pushing $NAME ..."
  
  # Export PAT so child scripts can also pick it up
  export GITHUB_PAT_SPA="$PAT"
  
  if bash "$SCRIPT" 2>&1; then
    echo "$NAME — $(date -u +%Y-%m-%dT%H:%M:%SZ)" >> "$LOG"
    echo "✅ $NAME pushed"
    DONE=$((DONE+1))
  else
    echo "❌ $NAME FAILED"
    echo "$NAME — FAILED $(date -u +%Y-%m-%dT%H:%M:%SZ)" >> "$FAILED_LOG"
    FAILED=$((FAILED+1))
  fi
  
  # Brief pause to avoid rate limiting
  sleep 1
done


# Push governance docs (not part of push_v*.sh series — runs separately)
GOVERNANCE_SCRIPT="$SCRIPTS_DIR/push_governance_docs.sh"
if [ -f "$GOVERNANCE_SCRIPT" ]; then
  GOV_NAME="push_governance_docs.sh"
  if grep -qF "$GOV_NAME" "$LOG" 2>/dev/null; then
    echo "⏭️  SKIP $GOV_NAME (already pushed)"
    SKIPPED=$((SKIPPED+1))
  else
    echo ""
    echo "🚀 Pushing $GOV_NAME ..."
    export GITHUB_PAT_SPA="$PAT"
    if bash "$GOVERNANCE_SCRIPT" 2>&1; then
      echo "$GOV_NAME — $(date -u +%Y-%m-%dT%H:%M:%SZ)" >> "$LOG"
      echo "✅ $GOV_NAME pushed"
      DONE=$((DONE+1))
    else
      echo "❌ $GOV_NAME FAILED"
      echo "$GOV_NAME — FAILED $(date -u +%Y-%m-%dT%H:%M:%SZ)" >> "$FAILED_LOG"
      FAILED=$((FAILED+1))
    fi
  fi
fi

echo ""
echo "============================================"
echo "✅ Done: $DONE pushed | ⏭️  Skipped: $SKIPPED | ❌ Failed: $FAILED"
