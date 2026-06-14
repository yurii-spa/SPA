#!/usr/bin/env bash
# Push script for sprint v7.18 (MP-960 + MP-961)
# Files: defi_liquidity_mining_roi_calculator.py, protocol_emission_schedule_impact_analyzer.py,
#        tests, log stubs, KANBAN.json

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$REPO_ROOT"

# ---------------------------------------------------------------------------
# PAT resolution (never hardcoded)
# ---------------------------------------------------------------------------
PAT=$(security find-generic-password -s GITHUB_PAT_SPA -w 2>/dev/null || echo "")
[ -z "$PAT" ] && PAT="${GITHUB_PAT_SPA:-${SPA_GITHUB_PAT:-}}"
[ -z "$PAT" ] && [ -f ~/.github_pat ] && PAT=$(cat ~/.github_pat)
[ -z "$PAT" ] && { echo "❌ PAT не найден"; exit 1; }

echo "✅ PAT resolved"

# ---------------------------------------------------------------------------
# Files to push
# ---------------------------------------------------------------------------
FILES=(
  "spa_core/analytics/defi_liquidity_mining_roi_calculator.py"
  "spa_core/analytics/protocol_emission_schedule_impact_analyzer.py"
  "spa_core/tests/test_defi_liquidity_mining_roi_calculator.py"
  "spa_core/tests/test_protocol_emission_schedule_impact_analyzer.py"
  "data/liquidity_mining_roi_log.json"
  "data/emission_schedule_log.json"
  "KANBAN.json"
  "scripts/push_v718.sh"
)

COMMIT_MSG="v7.18: MP-960 DeFiLiquidityMiningROICalculator (88 tests) + MP-961 ProtocolEmissionScheduleImpactAnalyzer (87 tests) — 175 tests green, done_count 618->620"

# ---------------------------------------------------------------------------
# Push via push_to_github.py
# ---------------------------------------------------------------------------
ABS_FILES=()
for f in "${FILES[@]}"; do
  ABS_FILES+=("$REPO_ROOT/$f")
done

echo "🚀 Pushing ${#ABS_FILES[@]} files..."
python3 "$REPO_ROOT/push_to_github.py" \
  --files "${ABS_FILES[@]}" \
  --message "$COMMIT_MSG"

echo "✅ Push complete: $COMMIT_MSG"
