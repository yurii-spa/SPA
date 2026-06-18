#!/usr/bin/env bash
# Sprint v8.74 push — MP-1228 DeFiProtocolVaultPerformanceFeeGrossOfSwapFeeBaseGapAnalyzer
# Run on Mac: bash scripts/push_v874.sh
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$REPO_ROOT"

# PAT from Keychain (never hardcode)
GITHUB_PAT="$(security find-generic-password -s GITHUB_PAT_SPA -w 2>/dev/null || true)"
if [[ -z "$GITHUB_PAT" ]]; then
  echo "ERROR: GITHUB_PAT_SPA not found in Keychain. Run: bash setup_pat.sh" >&2
  exit 1
fi
export GITHUB_PAT

MSG="feat(analytics): MP-1228 DeFiProtocolVaultPerformanceFeeGrossOfSwapFeeBaseGapAnalyzer (91 tests, yield_quality Tier-B)"

python3 push_to_github.py \
  --files \
  "$REPO_ROOT/spa_core/analytics/defi_protocol_vault_performance_fee_gross_of_swap_fee_base_gap_analyzer.py" \
  "$REPO_ROOT/spa_core/tests/test_defi_protocol_vault_performance_fee_gross_of_swap_fee_base_gap_analyzer.py" \
  "$REPO_ROOT/spa_core/analytics/_module_registry.py" \
  "$REPO_ROOT/KANBAN.json" \
  "$REPO_ROOT/sprint_log.md" \
  --message "$MSG"

echo "Push v8.74 complete."
