#!/usr/bin/env bash
# scripts/run_cpa_wave5_pushes.sh
# Pushes all CPA Wave 5 sprints to GitHub (v10.29 - v10.50)
# MP-1435: Wave 5 Consolidated Push Script
# Usage: bash ~/Documents/SPA_Claude/scripts/run_cpa_wave5_pushes.sh
#
# Reads PAT from macOS Keychain (GITHUB_PAT_SPA), then runs each push
# script in sequence. Missing scripts are skipped with a warning.

set -euo pipefail

REPO_DIR="$HOME/Documents/SPA_Claude"
cd "$REPO_DIR"

echo "=== SPA CPA Wave 5 Push (v10.29 - v10.50) ==="
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

# ── Script list (v10.29–v10.50) ───────────────────────────────────────────────
# Note: push_v1043_v1044.sh is a combined script covering both v10.43 and v10.44.
#       Individual push_v1043.sh and push_v1044.sh are EXCLUDED to avoid
#       double-push. If only individual scripts exist, remove push_v1043_v1044.sh
#       from this list.
SCRIPTS=(
  scripts/push_v1029.sh
  scripts/push_v1030.sh
  scripts/push_v1031.sh
  scripts/push_v1032.sh
  scripts/push_v1033.sh
  scripts/push_v1034.sh
  scripts/push_v1035.sh
  scripts/push_v1036.sh
  scripts/push_v1037.sh
  scripts/push_v1038.sh
  scripts/push_v1039.sh
  scripts/push_v1040.sh
  scripts/push_v1041.sh
  scripts/push_v1042.sh
  scripts/push_v1043_v1044.sh
  scripts/push_v1045.sh
  scripts/push_v1046.sh
  scripts/push_v1047.sh
  scripts/push_v1048.sh
  scripts/push_v1049.sh
  scripts/push_v1050.sh
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
echo "=== Wave 5 complete ==="
echo "  ✅ passed : $PASS"
echo "  ⚠️  skipped: $SKIP"
echo "  ❌ failed : $FAIL"
echo "Done: $(date -u '+%Y-%m-%dT%H:%M:%SZ')"

if [ "$FAIL" -gt 0 ]; then
  echo "Some push scripts failed — check output above."
  exit 1
fi
exit 0
