#!/bin/bash
# MP-606: DailyOperationsReport — push script v530
# Usage: bash scripts/push_v530.sh
# PAT читается из macOS Keychain (GITHUB_PAT_SPA) или env.

set -euo pipefail

REPO="yurii-spa/SPA"
COMMIT_MSG="feat(SPA-V530): DailyOperationsReport (MP-606) — unified risk/yield/chains/strategies/peg report, Telegram ≤4000 chars, action items, 90 tests green"
FILES=(
    "spa_core/analytics/daily_operations_report.py"
    "spa_core/tests/test_daily_operations_report.py"
    "data/daily_ops_report.json"
    "KANBAN.json"
    "SPA_sprint_log.md"
    "scripts/push_v530.sh"
)

# --- PAT resolution ---
PAT=""
PAT=$(security find-generic-password -s GITHUB_PAT_SPA -w 2>/dev/null || true)
[ -z "$PAT" ] && PAT="${GITHUB_PAT_SPA:-}"
[ -z "$PAT" ] && PAT="${SPA_GITHUB_PAT:-}"
[ -z "$PAT" ] && [ -f ~/.github_pat ] && PAT=$(cat ~/.github_pat)
if [ -z "$PAT" ]; then
    echo "❌ PAT not found. Set GITHUB_PAT_SPA in Keychain or env."
    exit 1
fi

python3 push_to_github.py \
    --files "${FILES[@]}" \
    --message "$COMMIT_MSG"
