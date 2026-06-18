#!/usr/bin/env bash
# scripts/push_v876.sh
# Sprint v8.76 — MP-1230 DeFiProtocolVaultPerformanceFeeGrossOfManagementFeeBaseGapAnalyzer
# Run on Mac: bash scripts/push_v876.sh
# PAT is read from macOS Keychain — never hardcoded.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"

# ── read PAT from Keychain ────────────────────────────────────────────────────
GITHUB_PAT="$(security find-generic-password -s GITHUB_PAT_SPA -w 2>/dev/null || true)"
if [ -z "$GITHUB_PAT" ]; then
  echo "ERROR: GITHUB_PAT_SPA not found in Keychain." >&2
  echo "       Run: bash setup_pat.sh   (see docs/TOKEN_ROTATION_RUNBOOK.md)" >&2
  exit 1
fi
export GITHUB_PAT

# ── files changed in v8.76 ───────────────────────────────────────────────────
FILES=(
  "spa_core/analytics/defi_protocol_vault_performance_fee_gross_of_management_fee_base_gap_analyzer.py"
  "spa_core/tests/test_defi_protocol_vault_performance_fee_gross_of_management_fee_base_gap_analyzer.py"
  "spa_core/analytics/_module_registry.py"
  "KANBAN.json"
  "sprint_log.md"
  "scripts/push_v876.sh"
)

# Convert to absolute paths
ABS_FILES=()
for f in "${FILES[@]}"; do
  ABS_FILES+=("${REPO_ROOT}/${f}")
done

MSG="v8.76 MP-1230 DeFiProtocolVaultPerformanceFeeGrossOfManagementFeeBaseGapAnalyzer (97 tests, yield_quality Tier-B) — perf-fee gross-of AUM management fee base gap; B=485 total=677 done_count=923"

echo "Pushing ${#ABS_FILES[@]} files..."
python3 "${REPO_ROOT}/push_to_github.py" \
  --files "${ABS_FILES[@]}" \
  --message "${MSG}"

echo "Push v8.76 complete."
