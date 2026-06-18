#!/usr/bin/env bash
# scripts/push_v887.sh
# Sprint v8.87 — MP-1241 DeFiProtocolVaultPerformanceFeeGrossOfLiquidationPenaltyBaseGapAnalyzer
# Run on Mac: bash scripts/push_v887.sh
# PAT is resolved at runtime from a fallback chain — NEVER hardcoded.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"

# ── resolve PAT: Keychain → env GITHUB_PAT_SPA → env SPA_GITHUB_PAT → ~/.github_pat ──
GITHUB_PAT=""
# 1) macOS Keychain
GITHUB_PAT="$(security find-generic-password -s GITHUB_PAT_SPA -w 2>/dev/null || true)"
# 2) env GITHUB_PAT_SPA
if [ -z "$GITHUB_PAT" ]; then
  GITHUB_PAT="${GITHUB_PAT_SPA:-}"
fi
# 3) env SPA_GITHUB_PAT
if [ -z "$GITHUB_PAT" ]; then
  GITHUB_PAT="${SPA_GITHUB_PAT:-}"
fi
# 4) file ~/.github_pat
if [ -z "$GITHUB_PAT" ] && [ -f "$HOME/.github_pat" ]; then
  GITHUB_PAT="$(tr -d '\r\n' < "$HOME/.github_pat" || true)"
fi

if [ -z "$GITHUB_PAT" ]; then
  echo "ERROR: GitHub PAT not found." >&2
  echo "       Tried: Keychain(GITHUB_PAT_SPA) → \$GITHUB_PAT_SPA → \$SPA_GITHUB_PAT → ~/.github_pat" >&2
  echo "       See docs/TOKEN_ROTATION_RUNBOOK.md" >&2
  exit 1
fi
export GITHUB_PAT

# ── files changed in v8.87 ───────────────────────────────────────────────────
FILES=(
  "spa_core/analytics/defi_protocol_vault_performance_fee_gross_of_liquidation_penalty_base_gap_analyzer.py"
  "spa_core/tests/test_defi_protocol_vault_performance_fee_gross_of_liquidation_penalty_base_gap_analyzer.py"
  "spa_core/analytics/_module_registry.py"
  "KANBAN.json"
  "sprint_log.md"
  "scripts/push_v887.sh"
)

# Convert to absolute paths
ABS_FILES=()
for f in "${FILES[@]}"; do
  ABS_FILES+=("${REPO_ROOT}/${f}")
done

MSG="v8.87 MP-1241 DeFiProtocolVaultPerformanceFeeGrossOfLiquidationPenaltyBaseGapAnalyzer (98 tests, yield_quality Tier-B) — perf-fee gross-of-liquidation-penalty base gap (the liquidator bonus + protocol liquidation fee bled from a leveraged/looping vault's seized collateral when its position is partially liquidated; distinct from bad_debt_socialization residual uncovered debt on a FAILED liquidation, ongoing borrow_cost interest on the borrowed leg, validator slashing_loss, the vault's own trade-execution drag exit_slippage/swap_fee/rebalancing_cost/mev_tax, and the gas-market/AA/messaging/oracle/keeper layers cost/priority_fee/blob_fee/l1_data_fee/bundler_fee/crosschain_message_fee/oracle_update_fee/harvest_bounty, plus funding_cost/bridge_fee/flash_loan_fee/management_fee/deposit_fee/withdrawal_fee/intent_solver_fee); B=496 total=688 done_count=934 [skip ci]"

echo "Pushing ${#ABS_FILES[@]} files..."
python3 "${REPO_ROOT}/push_to_github.py" \
  --files "${ABS_FILES[@]}" \
  --message "${MSG}"

echo "Push v8.87 complete."
