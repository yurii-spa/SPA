#!/usr/bin/env bash
# scripts/run_cpa_wave2_pushes.sh
# Pushes all CPA Wave 2 sprints to GitHub (v9.41 - v9.70)
# Usage: bash ~/Documents/SPA_Claude/scripts/run_cpa_wave2_pushes.sh
#
# Reads PAT from macOS Keychain (GITHUB_PAT_SPA), then runs each push
# script in sequence. Missing scripts are skipped with a warning.

set -euo pipefail

REPO_DIR="$HOME/Documents/SPA_Claude"
cd "$REPO_DIR"

echo "=== SPA CPA Wave 2 Push (v9.41 - v9.70) ==="
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

# ── Script list (v9.41–v9.70) ────────────────────────────────────────────────
SCRIPTS=(
  scripts/push_v941.sh
  scripts/push_v942.sh
  scripts/push_v943.sh
  scripts/push_v944.sh
  scripts/push_v945.sh
  scripts/push_v946.sh
  scripts/push_v947.sh
  scripts/push_v948.sh
  scripts/push_v949.sh
  scripts/push_v950.sh
  scripts/push_v951.sh
  scripts/push_v952.sh
  scripts/push_v953.sh
  scripts/push_v954.sh
  scripts/push_v955.sh
  scripts/push_v956.sh
  scripts/push_v957.sh
  scripts/push_v958.sh
  scripts/push_v959.sh
  scripts/push_v960.sh
  scripts/push_v961.sh
  scripts/push_v962.sh
  scripts/push_v963.sh
  scripts/push_v964.sh
  scripts/push_v965.sh
  scripts/push_v966.sh
  scripts/push_v967.sh
  scripts/push_v968.sh
  scripts/push_v969.sh
  scripts/push_v970.sh
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
echo "=== Wave 2 complete ==="
echo "  ✅ passed : $PASS"
echo "  ⚠️  skipped: $SKIP"
echo "  ❌ failed : $FAIL"
echo "Done: $(date -u '+%Y-%m-%dT%H:%M:%SZ')"

if [ "$FAIL" -gt 0 ]; then
  echo "Some push scripts failed — check output above."
  exit 1
fi
exit 0
