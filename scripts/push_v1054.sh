#!/usr/bin/env bash
# scripts/push_v1054.sh
# Sprint v10.54 — MP-1438: BaseAnalytics COMPLETE: 37/37 analytics modules migrated
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$REPO_ROOT"

echo "=== Sprint v10.54 — MP-1438 push ==="
echo "Root: $REPO_ROOT"
echo ""

python3 push_to_github.py \
  --files \
    "$REPO_ROOT/spa_core/analytics/rebalance_cost_estimator.py" \
    "$REPO_ROOT/spa_core/analytics/yield_compressor_score.py" \
    "$REPO_ROOT/spa_core/analytics/yield_forecast_engine.py" \
    "$REPO_ROOT/scripts/baseanalytics_migration_summary.py" \
    "$REPO_ROOT/tests/test_baseanalytics_complete.py" \
    "$REPO_ROOT/scripts/push_v1054.sh" \
    "$REPO_ROOT/KANBAN.json" \
  --message "Sprint v10.54 — MP-1438 BaseAnalytics COMPLETE: 37/37 analytics modules migrated"

echo ""
echo "✅ Sprint v10.54 pushed"
