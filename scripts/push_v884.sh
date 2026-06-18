#!/usr/bin/env bash
# scripts/push_v884.sh
# Sprint v8.84 — MP-1238 DeFiProtocolVaultPerformanceFeeGrossOfCrosschainMessageFeeBaseGapAnalyzer
# Run on Mac: bash scripts/push_v884.sh
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

# ── files changed in v8.84 ───────────────────────────────────────────────────
FILES=(
  "spa_core/analytics/defi_protocol_vault_performance_fee_gross_of_crosschain_message_fee_base_gap_analyzer.py"
  "spa_core/tests/test_defi_protocol_vault_performance_fee_gross_of_crosschain_message_fee_base_gap_analyzer.py"
  "spa_core/analytics/_module_registry.py"
  "KANBAN.json"
  "sprint_log.md"
  "scripts/push_v884.sh"
)

# Convert to absolute paths
ABS_FILES=()
for f in "${FILES[@]}"; do
  ABS_FILES+=("${REPO_ROOT}/${f}")
done

MSG="v8.84 MP-1238 DeFiProtocolVaultPerformanceFeeGrossOfCrosschainMessageFeeBaseGapAnalyzer (98 tests, yield_quality Tier-B) — perf-fee gross-of-crosschain-message-fee base gap (per-message cross-chain messaging-protocol fee: LayerZero endpoint+executor / Chainlink CCIP / Hyperlane interchain-gas payment to verify and deliver the vault's harvest/rebalance instruction across chains, distinct from bridge_fee asset-transfer, execution base-fee cost, EIP-1559 priority-fee proposer tip, EIP-4844 blob-fee DA posting, oracle update fee, ERC-4337 bundler fee, and keeper harvest bounty); B=493 total=685 done_count=931 [skip ci]"

echo "Pushing ${#ABS_FILES[@]} files..."
python3 "${REPO_ROOT}/push_to_github.py" \
  --files "${ABS_FILES[@]}" \
  --message "${MSG}"

echo "Push v8.84 complete."
