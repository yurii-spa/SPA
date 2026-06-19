#!/usr/bin/env bash
# scripts/push_v890.sh
# Sprint v8.90 — MP-1244 DeFiProtocolVaultPerformanceFeeGrossOfInsuranceFundPremiumBaseGapAnalyzer
# Run on Mac: bash scripts/push_v890.sh
# PAT is resolved at runtime from a fallback chain — NEVER hardcoded.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"

# ── resolve PAT: Keychain → env GITHUB_PAT_SPA → env SPA_GITHUB_PAT → ~/.github_pat ──
GITHUB_PAT=""
GITHUB_PAT="$(security find-generic-password -s GITHUB_PAT_SPA -w 2>/dev/null || true)"
if [ -z "$GITHUB_PAT" ]; then GITHUB_PAT="${GITHUB_PAT_SPA:-}"; fi
if [ -z "$GITHUB_PAT" ]; then GITHUB_PAT="${SPA_GITHUB_PAT:-}"; fi
if [ -z "$GITHUB_PAT" ] && [ -f "$HOME/.github_pat" ]; then GITHUB_PAT="$(tr -d "\r\n" < "$HOME/.github_pat" || true)"; fi
if [ -z "$GITHUB_PAT" ]; then
  echo "ERROR: GitHub PAT not found." >&2
  echo "       Tried: Keychain(GITHUB_PAT_SPA) → \$GITHUB_PAT_SPA → \$SPA_GITHUB_PAT → ~/.github_pat" >&2
  exit 1
fi
export GITHUB_PAT

FILES=(
  "spa_core/analytics/defi_protocol_vault_performance_fee_gross_of_insurance_fund_premium_base_gap_analyzer.py"
  "spa_core/tests/test_defi_protocol_vault_performance_fee_gross_of_insurance_fund_premium_base_gap_analyzer.py"
  "spa_core/analytics/_module_registry.py"
  "KANBAN.json"
  "sprint_log.md"
  "scripts/push_v890.sh"
)

ABS_FILES=()
for f in "${FILES[@]}"; do ABS_FILES+=("${REPO_ROOT}/${f}"); done

MSG="v8.90 MP-1244 DeFiProtocolVaultPerformanceFeeGrossOfInsuranceFundPremiumBaseGapAnalyzer (98 tests, yield_quality Tier-B) — perf-fee gross-of-insurance-fund-premium base gap (continuous cover premium paid OUT to a safety module / external cover provider — Nexus Mutual / Sherlock / staked-token Safety Module — for slashing/hack protection, skimmed from gross yield before the perf fee is struck; distinct from reserve_contribution retained protocol revenue, bad_debt_socialization realized residual loss, liquidation_penalty liquidator bonus, and slashing_loss the event itself); B=497 total=689 done_count=937 [skip ci]"

echo "Pushing ${#ABS_FILES[@]} files..."
python3 "${REPO_ROOT}/push_to_github.py" \
  --files "${ABS_FILES[@]}" \
  --message "${MSG}"

echo "Push complete."
