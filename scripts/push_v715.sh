#!/usr/bin/env bash
# ============================================================
# push_v715.sh — Sprint v7.15 push script
# MP-954: DeFiStakingRewardsOptimizer (class-based, gas-aware)
# MP-955: ProtocolCrossChainFeeComparator (cross-chain fees)
# ============================================================
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT"

# ---- PAT resolution (never embedded) ----
PAT=$(security find-generic-password -s GITHUB_PAT_SPA -w 2>/dev/null || echo "")
[ -z "$PAT" ] && PAT="${GITHUB_PAT_SPA:-${SPA_GITHUB_PAT:-}}"
[ -z "$PAT" ] && [ -f ~/.github_pat ] && PAT=$(cat ~/.github_pat)
[ -z "$PAT" ] && { echo "❌ PAT не найден (Keychain/env/~/.github_pat)"; exit 1; }

echo "✅ PAT найден"

# ---- Files to push ----
FILES=(
  "$(pwd)/spa_core/analytics/defi_staking_rewards_optimizer.py"
  "$(pwd)/spa_core/analytics/protocol_cross_chain_fee_comparator.py"
  "$(pwd)/spa_core/tests/test_defi_staking_rewards_optimizer.py"
  "$(pwd)/spa_core/tests/test_protocol_cross_chain_fee_comparator.py"
  "$(pwd)/data/staking_rewards_log.json"
  "$(pwd)/data/cross_chain_fee_log.json"
  "$(pwd)/KANBAN.json"
  "$(pwd)/scripts/push_v715.sh"
)

COMMIT_MSG="feat: MP-954 DeFiStakingRewardsOptimizer + MP-955 ProtocolCrossChainFeeComparator (sprint v7.15, 278 tests green)"

echo ""
echo "📦 Pushing sprint v7.15 files..."
echo "   Commit: $COMMIT_MSG"
echo ""

python3 "$(pwd)/push_to_github.py" \
  --files "${FILES[@]}" \
  --message "$COMMIT_MSG"

echo ""
echo "✅ Sprint v7.15 pushed successfully"
echo "   MP-954: DeFiStakingRewardsOptimizer — 90 tests (class-based, sqrt formula, gas-aware)"
echo "   MP-955: ProtocolCrossChainFeeComparator — 95 tests (cross-chain fee comparison, L2/L1)"
echo "   Total: 278 tests green (183 staking + 95 cross-chain)"
