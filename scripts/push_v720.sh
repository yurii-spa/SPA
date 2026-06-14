#!/usr/bin/env bash
# Push script for sprint v7.20 (MP-964 + MP-965)
# Files: defi_lending_market_utilization_analyzer.py, protocol_yield_curve_arbitrage_detector.py,
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
  "spa_core/analytics/defi_lending_market_utilization_analyzer.py"
  "spa_core/analytics/protocol_yield_curve_arbitrage_detector.py"
  "spa_core/tests/test_defi_lending_market_utilization_analyzer.py"
  "spa_core/tests/test_protocol_yield_curve_arbitrage_detector.py"
  "data/lending_utilization_log.json"
  "data/yield_curve_arb_log.json"
  "KANBAN.json"
  "scripts/push_v720.sh"
)

COMMIT_MSG="v7.20: MP-964 DeFiLendingMarketUtilizationAnalyzer (111 tests) + MP-965 ProtocolYieldCurveArbitrageDetector (91 tests) — 202 tests green, done_count 624->626"

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
