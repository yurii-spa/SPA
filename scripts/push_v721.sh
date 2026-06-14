#!/usr/bin/env bash
# push_v721.sh — Push MP-966 + MP-967 artifacts to GitHub (sprint v7.21)
# Usage: bash scripts/push_v721.sh
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$REPO_ROOT"

# ── PAT resolution (never hardcoded) ─────────────────────────────────────────
PAT=$(security find-generic-password -s GITHUB_PAT_SPA -w 2>/dev/null || echo "")
[ -z "$PAT" ] && PAT="${GITHUB_PAT_SPA:-${SPA_GITHUB_PAT:-}}"
[ -z "$PAT" ] && [ -f ~/.github_pat ] && PAT=$(cat ~/.github_pat)
[ -z "$PAT" ] && { echo "❌ PAT не найден (keychain/env/~/.github_pat)"; exit 1; }

echo "✅ PAT resolved"
echo "📁 Repo: $REPO_ROOT"

# ── Files to push ─────────────────────────────────────────────────────────────
FILES=(
  "spa_core/analytics/defi_yield_bearing_collateral_analyzer.py"
  "spa_core/analytics/protocol_governance_voter_apathy_analyzer.py"
  "spa_core/tests/test_defi_yield_bearing_collateral_analyzer.py"
  "spa_core/tests/test_protocol_governance_voter_apathy_analyzer.py"
  "data/yield_bearing_collateral_log.json"
  "data/governance_apathy_log.json"
  "KANBAN.json"
  "scripts/push_v721.sh"
)

COMMIT_MSG="feat: MP-966 DeFiYieldBearingCollateralAnalyzer (99 tests) + MP-967 ProtocolGovernanceVoterApathyAnalyzer (96 tests) — 195 tests green, done_count 626->628, sprint v7.21"

# ── Push via push_to_github.py ────────────────────────────────────────────────
ABS_FILES=()
for f in "${FILES[@]}"; do
  ABS_FILES+=("$REPO_ROOT/$f")
done

echo "🚀 Pushing ${#ABS_FILES[@]} files..."
python3 "$REPO_ROOT/push_to_github.py" \
  --files "${ABS_FILES[@]}" \
  --message "$COMMIT_MSG"

echo "✅ Push complete: $COMMIT_MSG"
