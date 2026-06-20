#!/usr/bin/env bash
# scripts/run_cpa_wave8_pushes.sh
# Pushes all CPA Wave 8 sprints to GitHub (v10.75 - v10.86)
# MP-1470: Wave 8 Consolidated Push Script
# Usage: bash ~/Documents/SPA_Claude/scripts/run_cpa_wave8_pushes.sh
#
# Reads PAT from macOS Keychain (GITHUB_PAT_SPA), then runs each push
# script in sequence. Missing scripts are skipped with a warning.
# Log: /tmp/wave8_push.log

set -euo pipefail

REPO_DIR="$HOME/Documents/SPA_Claude"
cd "$REPO_DIR"

LOG_FILE="/tmp/wave8_push.log"
exec > >(tee -a "$LOG_FILE") 2>&1

echo "=== SPA CPA Wave 8 Push (v10.75 - v10.86) ==="
echo "Working dir: $REPO_DIR"
echo "Date: $(date -u '+%Y-%m-%dT%H:%M:%SZ')"
echo ""

# ── PAT from Keychain ─────────────────────────────────────────────────────────
PAT=$(security find-generic-password -s GITHUB_PAT_SPA -w 2>/dev/null || true)
if [ -z "$PAT" ]; then
  echo "ERROR: PAT not found in Keychain (key: GITHUB_PAT_SPA)"
  echo "  Run: bash setup_pat.sh  (or see docs/TOKEN_ROTATION_RUNBOOK.md)"
  exit 1
fi
export GITHUB_PAT="$PAT"
echo "✅ PAT loaded from Keychain"

# ── Script list (v10.75–v10.86) ───────────────────────────────────────────────
SCRIPTS=(
  scripts/push_v1075.sh
  scripts/push_v1076.sh
  scripts/push_v1077.sh
  scripts/push_v1078.sh
  scripts/push_v1079.sh
  scripts/push_v1080.sh
  scripts/push_v1081.sh
  scripts/push_v1082.sh
  scripts/push_v1083.sh
  scripts/push_v1084.sh
  scripts/push_v1085.sh
  scripts/push_v1086.sh
)

PASS=0
SKIP=0
FAIL=0

for SCRIPT in "${SCRIPTS[@]}"; do
  if [ ! -f "$SCRIPT" ]; then
    echo "⚠️  $SCRIPT — not found, skipping"
    SKIP=$((SKIP + 1))
    continue
  fi

  echo ""
  echo "--- Running $SCRIPT ---"
  if bash "$SCRIPT"; then
    echo "✅ $SCRIPT done"
    PASS=$((PASS + 1))
  else
    echo "❌ $SCRIPT FAILED"
    FAIL=$((FAIL + 1))
    # Continue with remaining scripts rather than aborting the whole wave
  fi
  sleep 1   # rate-limit: avoid GitHub API burst limit
done

echo ""
echo "=== Wave 8 complete ==="
echo "  ✅ passed : $PASS"
echo "  ⚠️  skipped: $SKIP"
echo "  ❌ failed : $FAIL"
echo "Done: $(date -u '+%Y-%m-%dT%H:%M:%SZ')"
echo "Log: $LOG_FILE"

if [ "$FAIL" -gt 0 ]; then
  echo "Some push scripts failed — check output above."
  exit 1
fi
exit 0
