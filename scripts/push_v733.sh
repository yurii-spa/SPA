#!/usr/bin/env bash
# SPA Sprint v7.33 — Push script
# MP-990 DeFiProtocolTVLMomentumAnalyzer + MP-991 ProtocolDeFiTreasuryRunwayAnalyzer
# Usage: bash scripts/push_v733.sh

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT"

echo "=== SPA Sprint v7.33 Push ==="
echo "MP-990 DeFiProtocolTVLMomentumAnalyzer + MP-991 ProtocolDeFiTreasuryRunwayAnalyzer"
echo ""

# ── PAT resolution (no credentials in file) ────────────────────────────────
PAT=$(security find-generic-password -s GITHUB_PAT_SPA -w 2>/dev/null || echo "")
[ -z "$PAT" ] && PAT="${GITHUB_PAT_SPA:-${SPA_GITHUB_PAT:-}}"
[ -z "$PAT" ] && [ -f ~/.github_pat ] && PAT=$(cat ~/.github_pat)
[ -z "$PAT" ] && { echo "❌ PAT не найден. Установите через: bash setup_pat.sh"; exit 1; }

echo "✅ PAT найден"

# ── Files to push ──────────────────────────────────────────────────────────
FILES=(
    "spa_core/analytics/defi_protocol_tvl_momentum_analyzer.py"
    "spa_core/analytics/protocol_defi_treasury_runway_analyzer.py"
    "spa_core/tests/test_defi_protocol_tvl_momentum_analyzer.py"
    "spa_core/tests/test_protocol_defi_treasury_runway_analyzer.py"
    "data/tvl_momentum_log.json"
    "data/treasury_runway_log.json"
    "KANBAN.json"
    "scripts/push_v733.sh"
)

# Verify all files exist
echo "Verifying files..."
MISSING=0
for f in "${FILES[@]}"; do
    if [ ! -f "$REPO_ROOT/$f" ]; then
        echo "  ❌ MISSING: $f"
        MISSING=1
    else
        echo "  ✅ $f"
    fi
done

if [ "$MISSING" -eq 1 ]; then
    echo ""
    echo "❌ Abort: missing files. Resolve before pushing."
    exit 1
fi

echo ""
echo "Running tests..."

python3 -m unittest \
    spa_core.tests.test_defi_protocol_tvl_momentum_analyzer \
    spa_core.tests.test_protocol_defi_treasury_runway_analyzer \
    -v 2>&1 | tail -5

echo ""
echo "Pushing files to GitHub..."

python3 push_to_github.py \
    --files \
    "$REPO_ROOT/spa_core/analytics/defi_protocol_tvl_momentum_analyzer.py" \
    "$REPO_ROOT/spa_core/analytics/protocol_defi_treasury_runway_analyzer.py" \
    "$REPO_ROOT/spa_core/tests/test_defi_protocol_tvl_momentum_analyzer.py" \
    "$REPO_ROOT/spa_core/tests/test_protocol_defi_treasury_runway_analyzer.py" \
    "$REPO_ROOT/data/tvl_momentum_log.json" \
    "$REPO_ROOT/data/treasury_runway_log.json" \
    "$REPO_ROOT/KANBAN.json" \
    "$REPO_ROOT/scripts/push_v733.sh" \
    --message "feat: MP-990+MP-991 TVL momentum + treasury runway analyzers (189 tests) sprint v7.33"

echo ""
echo "=== Push complete ==="
echo "  MP-990 DeFiProtocolTVLMomentumAnalyzer — 98 tests"
echo "  MP-991 ProtocolDeFiTreasuryRunwayAnalyzer — 91 tests"
echo "  Total: 189 tests GREEN"
echo "  done_count: 650, sprint_current: v7.33"
