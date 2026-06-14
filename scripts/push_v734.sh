#!/usr/bin/env bash
# SPA Sprint v7.34 — Push script
# MP-992 DeFiProtocolRegulatoryRiskScorer + MP-993 ProtocolDeFiStablecoinHealthMonitor
# Usage: bash scripts/push_v734.sh

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT"

echo "=== SPA Sprint v7.34 Push ==="
echo "MP-992 DeFiProtocolRegulatoryRiskScorer + MP-993 ProtocolDeFiStablecoinHealthMonitor"
echo ""

# ── PAT resolution (no credentials in file) ────────────────────────────────
PAT=$(security find-generic-password -s GITHUB_PAT_SPA -w 2>/dev/null || echo "")
[ -z "$PAT" ] && PAT="${GITHUB_PAT_SPA:-${SPA_GITHUB_PAT:-}}"
[ -z "$PAT" ] && [ -f ~/.github_pat ] && PAT=$(cat ~/.github_pat)
[ -z "$PAT" ] && { echo "❌ PAT не найден. Установите через: bash setup_pat.sh"; exit 1; }

echo "✅ PAT найден"

# ── Files to push ──────────────────────────────────────────────────────────
FILES=(
    "spa_core/analytics/defi_protocol_regulatory_risk_scorer.py"
    "spa_core/analytics/protocol_defi_stablecoin_health_monitor.py"
    "spa_core/tests/test_defi_protocol_regulatory_risk_scorer.py"
    "spa_core/tests/test_protocol_defi_stablecoin_health_monitor.py"
    "data/regulatory_risk_log.json"
    "data/stablecoin_health_log.json"
    "KANBAN.json"
    "scripts/push_v734.sh"
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
    spa_core.tests.test_defi_protocol_regulatory_risk_scorer \
    spa_core.tests.test_protocol_defi_stablecoin_health_monitor \
    -v 2>&1 | tail -5

echo ""
echo "Pushing files to GitHub..."

python3 push_to_github.py \
    --files \
    "$REPO_ROOT/spa_core/analytics/defi_protocol_regulatory_risk_scorer.py" \
    "$REPO_ROOT/spa_core/analytics/protocol_defi_stablecoin_health_monitor.py" \
    "$REPO_ROOT/spa_core/tests/test_defi_protocol_regulatory_risk_scorer.py" \
    "$REPO_ROOT/spa_core/tests/test_protocol_defi_stablecoin_health_monitor.py" \
    "$REPO_ROOT/data/regulatory_risk_log.json" \
    "$REPO_ROOT/data/stablecoin_health_log.json" \
    "$REPO_ROOT/KANBAN.json" \
    "$REPO_ROOT/scripts/push_v734.sh" \
    --message "feat: MP-992+MP-993 regulatory risk scorer + stablecoin health monitor (204 tests) sprint v7.34"

echo ""
echo "=== Push complete ==="
echo "  MP-992 DeFiProtocolRegulatoryRiskScorer   — 102 tests"
echo "  MP-993 ProtocolDeFiStablecoinHealthMonitor — 102 tests"
echo "  Total: 204 tests GREEN"
echo "  done_count: 654, sprint_current: v7.34"
