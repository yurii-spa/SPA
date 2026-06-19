#!/usr/bin/env bash
# scripts/run_cpa_wave4_pushes.sh
# Pushes all CPA Wave 4 sprints to GitHub (v10.7 - v10.28)
# Usage: bash ~/Documents/SPA_Claude/scripts/run_cpa_wave4_pushes.sh
#
# Reads PAT from macOS Keychain (GITHUB_PAT_SPA), then runs each push
# script in sequence. Missing scripts are skipped with a warning.

set -euo pipefail

REPO_DIR="$HOME/Documents/SPA_Claude"
cd "$REPO_DIR"

echo "=== SPA CPA Wave 4 Push (v10.7 - v10.28) ==="
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

# ── Script list (v10.7–v10.28) ───────────────────────────────────────────────
SCRIPTS=(
  scripts/push_v1007.sh
  scripts/push_v1008.sh
  scripts/push_v1009.sh
  scripts/push_v1010.sh
  scripts/push_v1011.sh
  scripts/push_v1012.sh
  scripts/push_v1013.sh
  scripts/push_v1014.sh
  scripts/push_v1015.sh
  scripts/push_v1016.sh
  scripts/push_v1017.sh
  scripts/push_v1018.sh
  scripts/push_v1019.sh
  scripts/push_v1020.sh
  scripts/push_v1021.sh
  scripts/push_v1022.sh
  scripts/push_v1023.sh
  scripts/push_v1024.sh
  scripts/push_v1025.sh
  scripts/push_v1026.sh
  scripts/push_v1027.sh
  scripts/push_v1028.sh
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
echo "=== Wave 4 complete ==="
echo "  ✅ passed : $PASS"
echo "  ⚠️  skipped: $SKIP"
echo "  ❌ failed : $FAIL"
echo "Done: $(date -u '+%Y-%m-%dT%H:%M:%SZ')"

if [ "$FAIL" -gt 0 ]; then
  echo "Some push scripts failed — check output above."
  exit 1
fi
exit 0
