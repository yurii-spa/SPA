#!/usr/bin/env bash
# scripts/push_v892.sh
# Sprint v8.92 — MP-1248 DeFiProtocolVaultPerformanceFeeGrossOfVoteIncentiveFeeBaseGapAnalyzer
# Run on Mac: bash scripts/push_v892.sh
# PAT is resolved at runtime from a fallback chain — NEVER hardcoded.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"

# ── resolve PAT: Keychain → env GITHUB_PAT_SPA → env SPA_GITHUB_PAT → ~/.github_pat ──
GITHUB_PAT=""
GITHUB_PAT="$(security find-generic-password -s GITHUB_PAT_SPA -w 2>/dev/null || true)"
if [ -z "$GITHUB_PAT" ]; then GITHUB_PAT="${GITHUB_PAT_SPA:-}"; fi
if [ -z "$GITHUB_PAT" ]; then GITHUB_PAT="${SPA_GITHUB_PAT:-}"; fi
if [ -z "$GITHUB_PAT" ] && [ -f "$HOME/.github_pat" ]; then
  GITHUB_PAT="$(tr -d '\r\n' < "$HOME/.github_pat" || true)"
fi
if [ -z "$GITHUB_PAT" ]; then
  echo "ERROR: GitHub PAT not found." >&2
  echo "       Tried: Keychain(GITHUB_PAT_SPA) -> \$GITHUB_PAT_SPA -> \$SPA_GITHUB_PAT -> ~/.github_pat" >&2
  echo "       See docs/TOKEN_ROTATION_RUNBOOK.md" >&2
  exit 1
fi
export GITHUB_PAT

# ── files changed in v8.92 ───────────────────────────────────────────────────
FILES=(
  "spa_core/analytics/defi_protocol_vault_performance_fee_gross_of_vote_incentive_fee_base_gap_analyzer.py"
  "spa_core/tests/test_defi_protocol_vault_performance_fee_gross_of_vote_incentive_fee_base_gap_analyzer.py"
  "spa_core/analytics/_module_registry.py"
  "KANBAN.json"
  "sprint_log.md"
  "scripts/push_v892.sh"
)

ABS_FILES=()
for f in "${FILES[@]}"; do ABS_FILES+=("${REPO_ROOT}/${f}"); done

MSG="v8.92 MP-1248 DeFiProtocolVaultPerformanceFeeGrossOfVoteIncentiveFeeBaseGapAnalyzer (98 tests, yield_quality Tier-B) — perf-fee gross-of-vote-incentive-fee base gap (the take-rate a vote-incentive/bribe MARKETPLACE — Votium/Hidden Hand/Paladin Quest/Warden — skims off the gauge-vote-bribe income a veToken/gauge-voting vault earns, deducted from gross bribe stream before the perf fee is struck on GROSS yield; distinct from referral_fee/boost_fee third-party take-rates, the existing vetoken_bribe_efficiency/bribe_market modules measuring bribe ROI/market dynamics, validator_commission/management_fee/harvest_bounty, trade-execution drag swap_fee/exit_slippage/rebalancing_cost/mev_tax, the gas/AA/messaging/oracle layers, and the other gross_of_* layers) [skip ci]"

echo "Pushing ${#ABS_FILES[@]} files..."
python3 "${REPO_ROOT}/push_to_github.py" \
  --files "${ABS_FILES[@]}" \
  --message "${MSG}"

echo "Push v8.92 complete."
