#!/usr/bin/env bash
# scripts/run_cpa_wave_pushes.sh
# Consolidated push runner for CPA wave sprints v9.21–v9.40.
# Usage: bash scripts/run_cpa_wave_pushes.sh
#
# Reads PAT from macOS Keychain (GITHUB_PAT_SPA), then runs each push
# script in sequence. Missing scripts are skipped with a warning.
# Exits non-zero if any push script fails.

set -euo pipefail

REPO_DIR="$HOME/Documents/SPA_Claude"
cd "$REPO_DIR"

echo "=== CPA Wave Push: v9.21-v9.40 ==="
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

# ── Script list (v9.21–v9.40) ────────────────────────────────────────────────
SCRIPTS=(
  scripts/push_v921.sh
  scripts/push_v922.sh
  scripts/push_v923.sh
  scripts/push_v924.sh
  scripts/push_v925.sh
  scripts/push_v926.sh
  scripts/push_v927.sh
  scripts/push_v928.sh
  scripts/push_v929.sh
  scripts/push_v930.sh
  scripts/push_v931.sh
  scripts/push_v932.sh
  scripts/push_v933.sh
  scripts/push_v934.sh
  scripts/push_v935.sh
  scripts/push_v936.sh
  scripts/push_v937.sh
  scripts/push_v938.sh
  scripts/push_v939.sh
  scripts/push_v940.sh
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
echo "=== CPA Wave Push Complete ==="
echo "  ✅ passed : $PASS"
echo "  ⚠️  skipped: $SKIP"
echo "  ❌ failed : $FAIL"

if [ "$FAIL" -gt 0 ]; then
  echo "Some push scripts failed — check output above."
  exit 1
fi
exit 0
