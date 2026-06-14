#!/usr/bin/env bash
# Push script for sprint v7.19 (MP-962 + MP-963)
# Files: defi_oracle_manipulation_risk_scorer.py, protocol_defi_depeg_contagion_modeler.py,
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
  "spa_core/analytics/defi_oracle_manipulation_risk_scorer.py"
  "spa_core/analytics/protocol_defi_depeg_contagion_modeler.py"
  "spa_core/tests/test_defi_oracle_manipulation_risk_scorer.py"
  "spa_core/tests/test_protocol_defi_depeg_contagion_modeler.py"
  "data/oracle_manipulation_log.json"
  "data/depeg_contagion_log.json"
  "KANBAN.json"
  "scripts/push_v719.sh"
)

COMMIT_MSG="v7.19: MP-962 DeFiOracleManipulationRiskScorer (102 tests) + MP-963 ProtocolDeFiDepegContagionModeler (102 tests) — 204 tests green, done_count 624->626"

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
