#!/usr/bin/env bash
# scripts/push_v1064.sh
# Sprint v10.64 — MP-1448: BaseAnalytics Phase 4: paper_trading + family_fund
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$REPO_ROOT"

echo "=== Sprint v10.64 — MP-1448 BaseAnalytics Phase 4: paper_trading + family_fund ==="
echo "Root: $REPO_ROOT"
echo ""

python3 push_to_github.py \
  --files \
    "$REPO_ROOT/spa_core/paper_trading/golive_checker.py" \
    "$REPO_ROOT/spa_core/paper_trading/tournament_evaluator.py" \
    "$REPO_ROOT/spa_core/family_fund/lead_tracker.py" \
    "$REPO_ROOT/scripts/baseanalytics_migration_summary.py" \
    "$REPO_ROOT/scripts/push_v1064.sh" \
    "$REPO_ROOT/KANBAN.json" \
  --message "Sprint v10.64 — MP-1448 BaseAnalytics Phase 4: paper_trading + family_fund"
