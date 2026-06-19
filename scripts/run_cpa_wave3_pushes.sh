#!/usr/bin/env bash
# scripts/run_cpa_wave3_pushes.sh
# Pushes all CPA Wave 3 sprints to GitHub (v9.71 - v10.6)
# Usage: bash ~/Documents/SPA_Claude/scripts/run_cpa_wave3_pushes.sh
#
# Reads PAT from macOS Keychain (GITHUB_PAT_SPA), then runs each push
# script in sequence. Missing scripts are skipped with a warning.

set -euo pipefail

REPO_DIR="$HOME/Documents/SPA_Claude"
cd "$REPO_DIR"

echo "=== SPA CPA Wave 3 Push (v9.71 - v10.6) ==="
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

# ── Script list (v9.71–v10.6) ────────────────────────────────────────────────
SCRIPTS=(
  scripts/push_v971.sh
  scripts/push_v972.sh
  scripts/push_v973.sh
  scripts/push_v974.sh
  scripts/push_v975.sh
  scripts/push_v976.sh
  scripts/push_v977.sh
  scripts/push_v978.sh
  scripts/push_v979.sh
  scripts/push_v980.sh
  scripts/push_v981.sh
  scripts/push_v982.sh
  scripts/push_v983.sh
  scripts/push_v984.sh
  scripts/push_v985.sh
  scripts/push_v986.sh
  scripts/push_v987.sh
  scripts/push_v988.sh
  scripts/push_v989.sh
  scripts/push_v990.sh
  scripts/push_v991.sh
  scripts/push_v992.sh
  scripts/push_v993.sh
  scripts/push_v994.sh
  scripts/push_v995.sh
  scripts/push_v996.sh
  scripts/push_v997.sh
  scripts/push_v998.sh
  scripts/push_v999.sh
  scripts/push_v100.sh
  scripts/push_audit001.sh
  scripts/push_v1001.sh
  scripts/push_v1002.sh
  scripts/push_v1003.sh
  scripts/push_v1004.sh
  scripts/push_v1005.sh
  scripts/push_v1006.sh
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
echo "=== Wave 3 complete ==="
echo "  ✅ passed : $PASS"
echo "  ⚠️  skipped: $SKIP"
echo "  ❌ failed : $FAIL"
echo "Done: $(date -u '+%Y-%m-%dT%H:%M:%SZ')"

if [ "$FAIL" -gt 0 ]; then
  echo "Some push scripts failed — check output above."
  exit 1
fi
exit 0
