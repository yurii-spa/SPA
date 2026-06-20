#!/usr/bin/env bash
# ============================================================
# Wave 10 Push Orchestrator — v11.43 → v11.54 (MP-1538)
# Runs all Sprint v11.x push scripts in sequence.
# Safe to re-run — each sub-script is idempotent.
# ============================================================
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SCRIPTS_DIR="$REPO_ROOT/scripts"
cd "$REPO_ROOT"

echo "============================================================"
echo "  SPA Wave 10 Push Orchestrator — v11.43 → v11.54"
echo "  $(date '+%Y-%m-%d %H:%M:%S')"
echo "============================================================"

WAVE10_SCRIPTS=(
  "push_v1143.sh"   # MP-1523 REST API observability
  "push_v1144.sh"   # MP-1524 Admin tools
  "push_v1145.sh"   # MP-1525 Documentation sprint
  "push_v1151.sh"   # MP-1535 Pre-deploy validation (28 tests)
  "push_v1152.sh"   # MP-1536 GitHub Actions workflows (19 tests)
  "push_v1153.sh"   # MP-1537 Cloudflare Pages config
  "push_v1154.sh"   # MP-1538 Milestone + KANBAN update
)

PASSED=0
FAILED=0
SKIPPED=0

for script in "${WAVE10_SCRIPTS[@]}"; do
  path="$SCRIPTS_DIR/$script"
  if [[ ! -f "$path" ]]; then
    echo "  ⏭️  SKIP $script (not found)"
    ((SKIPPED++)) || true
    continue
  fi
  echo ""
  echo "--- Running $script ---"
  if bash "$path"; then
    echo "  ✅ $script OK"
    ((PASSED++)) || true
  else
    echo "  ❌ $script FAILED (exit $?)"
    ((FAILED++)) || true
  fi
done

echo ""
echo "============================================================"
echo "  Wave 10 complete: ${PASSED} passed / ${FAILED} failed / ${SKIPPED} skipped"
echo "============================================================"

if [[ $FAILED -gt 0 ]]; then
  echo "❌ Some pushes failed. Check output above."
  exit 1
fi
echo "✅ All Wave 10 pushes complete."
