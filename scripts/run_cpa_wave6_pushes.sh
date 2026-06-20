#!/usr/bin/env bash
# scripts/run_cpa_wave6_pushes.sh
# Pushes all CPA Wave 6 sprints to GitHub (v10.51 - v10.66)
# MP-1450: Wave 6 Consolidated Push Script
# Usage: bash ~/Documents/SPA_Claude/scripts/run_cpa_wave6_pushes.sh
#
# Reads PAT from macOS Keychain (GITHUB_PAT_SPA), then runs each push
# script in sequence. Missing scripts are skipped with a warning.

set -euo pipefail

REPO_DIR="$HOME/Documents/SPA_Claude"
cd "$REPO_DIR"

echo "=== SPA CPA Wave 6 Push (v10.51 - v10.66) ==="
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

# ── Script list (v10.51–v10.66) ───────────────────────────────────────────────
SCRIPTS=(
  scripts/push_v1051.sh
  scripts/push_v1052.sh
  scripts/push_v1053.sh
  scripts/push_v1054.sh
  scripts/push_v1055.sh
  scripts/push_v1056.sh
  scripts/push_v1057.sh
  scripts/push_v1058.sh
  scripts/push_v1059.sh
  scripts/push_v1060.sh
  scripts/push_v1061.sh
  scripts/push_v1062.sh
  scripts/push_v1063.sh
  scripts/push_v1064.sh
  scripts/push_v1065.sh
  scripts/push_v1066.sh
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
echo "=== Wave 6 complete ==="
echo "  ✅ passed : $PASS"
echo "  ⚠️  skipped: $SKIP"
echo "  ❌ failed : $FAIL"
echo "Done: $(date -u '+%Y-%m-%dT%H:%M:%SZ')"

if [ "$FAIL" -gt 0 ]; then
  echo "Some push scripts failed — check output above."
  exit 1
fi
exit 0
