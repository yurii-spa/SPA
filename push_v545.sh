#!/bin/bash
# Push script for SPA-V545 (MP-621: FullPortfolioMasterReport)
# Run from project root: bash scripts/push_v545.sh

set -euo pipefail

REPO="yurii-spa/SPA"
COMMIT_MSG="feat(SPA-V545): FullPortfolioMasterReport (MP-621) — unified master snapshot aggregating 12 analytics modules, EXCELLENT/GOOD/FAIR/ALERT health, action items, Telegram ≤2000 chars, 124 tests green"
FILES=(
  "spa_core/analytics/full_portfolio_report.py"
  "spa_core/tests/test_full_portfolio_report.py"
  "data/master_report.json"
  "KANBAN.json"
  "SPA_sprint_log.md"
  "scripts/push_v545.sh"
)

# Resolve PAT: Keychain → env vars → ~/.github_pat
PAT=$(security find-generic-password -s GITHUB_PAT_SPA -w 2>/dev/null || echo "")
[ -z "$PAT" ] && PAT="${GITHUB_PAT_SPA:-${SPA_GITHUB_PAT:-}}"
[ -z "$PAT" ] && [ -f ~/.github_pat ] && PAT=$(cat ~/.github_pat)
[ -z "$PAT" ] && { echo "❌ PAT не найден (Keychain / GITHUB_PAT_SPA / ~/.github_pat)"; exit 1; }

echo "🚀 Pushing SPA-V545 → $REPO"
python3 push_to_github.py --files "${FILES[@]}" --message "$COMMIT_MSG"
echo "✅ Done"
