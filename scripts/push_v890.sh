#!/usr/bin/env bash
# scripts/push_v890.sh
# Sprint v8.90 — MP-1245 DeFiProtocolVaultPerformanceFeeGrossOfAvsOperatorFeeBaseGapAnalyzer
# Run on Mac: bash scripts/push_v890.sh
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

# ── files changed in v8.90 ───────────────────────────────────────────────────
FILES=(
  "spa_core/analytics/defi_protocol_vault_performance_fee_gross_of_avs_operator_fee_base_gap_analyzer.py"
  "spa_core/tests/test_defi_protocol_vault_performance_fee_gross_of_avs_operator_fee_base_gap_analyzer.py"
  "spa_core/analytics/_module_registry.py"
  "KANBAN.json"
  "sprint_log.md"
  "scripts/push_v890.sh"
)

# Convert to absolute paths
ABS_FILES=()
for f in "${FILES[@]}"; do
  ABS_FILES+=("${REPO_ROOT}/${f}")
done

MSG="v8.90 MP-1245 DeFiProtocolVaultPerformanceFeeGrossOfAvsOperatorFeeBaseGapAnalyzer (98 tests, yield_quality Tier-B) — perf-fee gross-of-avs-operator-fee base gap (the restaking AVS operator's commission skimmed from AVS reward flow on EigenLayer/Symbiotic/Karak before the restaker-vault sees it, with perf fee struck on GROSS reward; distinct from validator_commission L1 consensus node-operator commission, slashing_loss the penalty event, boost_fee, harvest_bounty/oracle_update_fee keeper/oracle layers, management_fee/deposit_fee/withdrawal_fee/referral_fee/reserve_contribution/insurance_premium vault fee layers, and the cost/priority_fee/blob_fee/l1_data_fee/bundler_fee/crosschain_message_fee/mev_tax/intent_solver_fee/swap_fee/exit_slippage/rebalancing_cost gas-execution-messaging layers, plus liquidation_penalty/bad_debt_socialization/borrow_cost/funding_cost/flash_loan_fee/bridge_fee); Tier-B yield_quality registry [skip ci]"

echo "Pushing ${#ABS_FILES[@]} files..."
python3 "${REPO_ROOT}/push_to_github.py" \
  --files "${ABS_FILES[@]}" \
  --message "${MSG}"

echo "Push v8.90 complete."
