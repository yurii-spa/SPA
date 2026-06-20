#!/usr/bin/env bash
# scripts/run_cpa_wave7_pushes.sh
# Pushes all CPA Wave 7 sprints to GitHub (v10.67 - v10.74)
# MP-1458: Wave 7 Consolidated Push Script
# Usage: bash ~/Documents/SPA_Claude/scripts/run_cpa_wave7_pushes.sh
#
# Reads PAT from macOS Keychain (GITHUB_PAT_SPA), then runs each push
# script in sequence. Missing scripts are skipped with a warning.

set -euo pipefail

REPO_DIR="$HOME/Documents/SPA_Claude"
cd "$REPO_DIR"

echo "=== SPA CPA Wave 7 Push (v10.67 - v10.74) ==="
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

# ── Script list (v10.67–v10.74) ───────────────────────────────────────────────
SCRIPTS=(
  scripts/push_v1067.sh
  scripts/push_v1068.sh
  scripts/push_v1069.sh
  scripts/push_v1070.sh
  scripts/push_v1071.sh
  scripts/push_v1072.sh
  scripts/push_v1073.sh
  scripts/push_v1074.sh
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
echo "=== Wave 7 complete ==="
echo "  ✅ passed : $PASS"
echo "  ⚠️  skipped: $SKIP"
echo "  ❌ failed : $FAIL"
echo "Done: $(date -u '+%Y-%m-%dT%H:%M:%SZ')"

if [ "$FAIL" -gt 0 ]; then
  echo "Some push scripts failed — check output above."
  exit 1
fi
exit 0
