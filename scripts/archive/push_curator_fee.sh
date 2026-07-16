#!/usr/bin/env bash
# scripts/push_curator_fee.sh
# Additive module: MP-1246 DeFiProtocolVaultPerformanceFeeGrossOfCuratorFeeBaseGapAnalyzer
#
# NOTE: This run (spa-dev-continue) detected a CONCURRENT instance of the same
# scheduled task actively advancing sprints v8.88–v8.91 (React SPA, insurance_fund_premium,
# avs_operator_fee) and writing KANBAN.json / sprint_log.md live. To avoid clobbering that
# authoritative bookkeeping, this run did NOT touch KANBAN.json or sprint_log.md. It only
# added the non-overlapping `curator_fee` analyzer + test + one registry line.
# Therefore this script stages ONLY those additive files (no KANBAN.json / sprint_log.md).
#
# Run on Mac: bash scripts/push_curator_fee.sh
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

# ── additive curator_fee files only (NO KANBAN.json / sprint_log.md) ─────────────
FILES=(
  "spa_core/analytics/defi_protocol_vault_performance_fee_gross_of_curator_fee_base_gap_analyzer.py"
  "spa_core/tests/test_defi_protocol_vault_performance_fee_gross_of_curator_fee_base_gap_analyzer.py"
  "spa_core/analytics/_module_registry.py"
  "scripts/push_curator_fee.sh"
)

# Convert to absolute paths
ABS_FILES=()
for f in "${FILES[@]}"; do
  ABS_FILES+=("${REPO_ROOT}/${f}")
done

MSG="MP-1246 DeFiProtocolVaultPerformanceFeeGrossOfCuratorFeeBaseGapAnalyzer (98 tests, yield_quality Tier-B weight=0.5) — perf-fee gross-of-CURATOR-FEE base gap: the external risk-curator's cut of vault yield (MetaMorpho/Morpho Blue, Euler v2 EulerEarn, Yearn v3 curated vaults; Gauntlet/Steakhouse/Re7) skimmed before the depositor sees net → fee-on-curator-fee base inflation. Distinct from gross_of_management_fee (operator AUM fee), gross_of_validator_commission (PoS commission), gross_of_referral_fee, gross_of_reserve_contribution and gross_of_harvest_bounty. Additive module only (no KANBAN/sprint_log — see header note re: concurrent run). [skip ci]"

echo "Pushing ${#ABS_FILES[@]} files (curator_fee additive)..."
python3 "${REPO_ROOT}/push_to_github.py" \
  --files "${ABS_FILES[@]}" \
  --message "${MSG}"

echo "Push curator_fee complete."
