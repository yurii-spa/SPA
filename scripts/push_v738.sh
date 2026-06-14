#!/usr/bin/env bash
# push_v738.sh — Sprint v7.38: MP-1000 + MP-1001
# Pushes all sprint deliverables to GitHub via push_to_github.py
# NEVER embed PAT here — always read from keychain/env

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$REPO_ROOT"

# ── PAT resolution (keychain → env → file) ─────────────────────────────────
PAT=$(security find-generic-password -s GITHUB_PAT_SPA -w 2>/dev/null || echo "")
[ -z "$PAT" ] && PAT="${GITHUB_PAT_SPA:-${SPA_GITHUB_PAT:-}}"
[ -z "$PAT" ] && [ -f ~/.github_pat ] && PAT=$(cat ~/.github_pat)
[ -z "$PAT" ] && { echo "❌ PAT не найден"; exit 1; }

export GITHUB_PAT_SPA="$PAT"

echo "🚀 Sprint v7.38 — MP-1000 + MP-1001 push"
echo "   Repo: $REPO_ROOT"

# ── Files to push ────────────────────────────────────────────────────────────
FILES=(
    "$REPO_ROOT/spa_core/analytics/defi_protocol_fee_tier_optimizer.py"
    "$REPO_ROOT/spa_core/analytics/protocol_defi_token_buyback_impact_analyzer.py"
    "$REPO_ROOT/spa_core/tests/test_defi_protocol_fee_tier_optimizer.py"
    "$REPO_ROOT/spa_core/tests/test_protocol_defi_token_buyback_impact_analyzer.py"
    "$REPO_ROOT/data/fee_tier_optimization_log.json"
    "$REPO_ROOT/data/token_buyback_log.json"
    "$REPO_ROOT/KANBAN.json"
    "$REPO_ROOT/scripts/push_v738.sh"
)

# ── Verify all files exist ───────────────────────────────────────────────────
MISSING=0
for f in "${FILES[@]}"; do
    if [ ! -f "$f" ]; then
        echo "❌ Missing: $f"
        MISSING=$((MISSING+1))
    fi
done
[ "$MISSING" -gt 0 ] && { echo "Aborting — $MISSING file(s) missing."; exit 1; }

echo "✅ All ${#FILES[@]} files verified"

# ── Push ─────────────────────────────────────────────────────────────────────
python3 "$REPO_ROOT/push_to_github.py" \
    --files "${FILES[@]}" \
    --message "feat: Sprint v7.38 — MP-1000 DeFiProtocolFeeTierOptimizer (124 tests) + MP-1001 ProtocolDeFiTokenBuybackImpactAnalyzer (120 tests) — 244 tests GREEN, done_count 656->658"

echo "✅ Push complete — Sprint v7.38 delivered"
