#!/usr/bin/env bash
# scripts/push_v889_ewp.sh
# Sprint v8.92-ewp (reconciled) — MP-1247 DeFiProtocolVaultPerformanceFeeGrossOfEarlyWithdrawalPenaltyBaseGapAnalyzer
# NB: original plan was v8.89/MP-1243, but parallel scheduled runs already claimed
#     v8.89 (curator_fee), v8.90 (insurance_fund_premium/avs), v8.91 (protocol_revenue_share).
#     This module (early_withdrawal_penalty) is a genuine NON-duplicate layer; filed as MP-1247.
# Run on Mac: bash scripts/push_v889_ewp.sh
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

# ── files changed in this sprint ─────────────────────────────────────────────
FILES=(
  "spa_core/analytics/defi_protocol_vault_performance_fee_gross_of_early_withdrawal_penalty_base_gap_analyzer.py"
  "spa_core/tests/test_defi_protocol_vault_performance_fee_gross_of_early_withdrawal_penalty_base_gap_analyzer.py"
  "spa_core/analytics/_module_registry.py"
  "KANBAN.json"
  "sprint_log.md"
  "scripts/push_v889_ewp.sh"
)

# Convert to absolute paths
ABS_FILES=()
for f in "${FILES[@]}"; do
  ABS_FILES+=("${REPO_ROOT}/${f}")
done

MSG="MP-1247 DeFiProtocolVaultPerformanceFeeGrossOfEarlyWithdrawalPenaltyBaseGapAnalyzer (98 tests, yield_quality Tier-B) — perf-fee gross-of-early-withdrawal-penalty base gap (penalty seized when the vault BREAKS a time-lock/vesting position EARLY to honour a redemption before maturity: veCRV/vote-escrow early-exit forfeiture, Pendle PT/YT early redeem, locked-staking/cooldown forfeiture, bonding/warmup burn — bled from gross yield before the depositor sees it, with the perf fee struck on GROSS yield -> fee-on-early-withdrawal-penalty/fee-base inflation; distinct from FLAT withdrawal_fee, liquidator-seizure liquidation_penalty, continuous funding_cost/borrow_cost, execution-drag exit_slippage/swap_fee/rebalancing_cost, and from lockup_opportunity_cost/redemption_cooldown_exposure which price the WAIT not a seized penalty). Reconciled MP-1247/v8.92-ewp (original v8.89/MP-1243 taken by parallel runs); registry +1 Tier-B [skip ci]"

echo "Pushing ${#ABS_FILES[@]} files..."
python3 "${REPO_ROOT}/push_to_github.py" \
  --files "${ABS_FILES[@]}" \
  --message "${MSG}"

echo "Push v8.92-ewp (MP-1247) complete."
