#!/usr/bin/env bash
# Sprint v8.75 push — MP-1229 DeFiProtocolVaultPerformanceFeeGrossOfDepositFeeBaseGapAnalyzer
# Run on Mac: bash scripts/push_v875.sh
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$REPO_ROOT"

# PAT fallback chain (never hardcode a token anywhere):
#   1) macOS Keychain (service GITHUB_PAT_SPA)
#   2) env GITHUB_PAT_SPA
#   3) env SPA_GITHUB_PAT
#   4) file ~/.github_pat
GITHUB_PAT="$(security find-generic-password -s GITHUB_PAT_SPA -w 2>/dev/null || true)"
if [[ -z "${GITHUB_PAT:-}" ]]; then GITHUB_PAT="${GITHUB_PAT_SPA:-}"; fi
if [[ -z "${GITHUB_PAT:-}" ]]; then GITHUB_PAT="${SPA_GITHUB_PAT:-}"; fi
if [[ -z "${GITHUB_PAT:-}" && -f "$HOME/.github_pat" ]]; then
  GITHUB_PAT="$(tr -d '[:space:]' < "$HOME/.github_pat")"
fi
if [[ -z "${GITHUB_PAT:-}" ]]; then
  echo "ERROR: GitHub PAT not found (Keychain GITHUB_PAT_SPA / env GITHUB_PAT_SPA / env SPA_GITHUB_PAT / ~/.github_pat)." >&2
  exit 1
fi
export GITHUB_PAT

MSG="feat(analytics): MP-1229 DeFiProtocolVaultPerformanceFeeGrossOfDepositFeeBaseGapAnalyzer (96 tests, yield_quality Tier-B)"

python3 push_to_github.py \
  --files \
  "$REPO_ROOT/spa_core/analytics/defi_protocol_vault_performance_fee_gross_of_deposit_fee_base_gap_analyzer.py" \
  "$REPO_ROOT/spa_core/tests/test_defi_protocol_vault_performance_fee_gross_of_deposit_fee_base_gap_analyzer.py" \
  "$REPO_ROOT/spa_core/analytics/_module_registry.py" \
  "$REPO_ROOT/KANBAN.json" \
  "$REPO_ROOT/sprint_log.md" \
  --message "$MSG"

echo "Push v8.75 complete."
