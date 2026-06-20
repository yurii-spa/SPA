#!/usr/bin/env bash
# scripts/push_v1063.sh
# Sprint v10.63 — MP-1447: BaseAnalytics Phase 4: backtesting/ layer
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$REPO_ROOT"

echo "=== Sprint v10.63 — MP-1447 BaseAnalytics Phase 4: backtesting/ layer ==="
echo "Root: $REPO_ROOT"
echo ""

python3 push_to_github.py \
  --files \
    "$REPO_ROOT/spa_core/backtesting/pit_vs_naive_comparison.py" \
    "$REPO_ROOT/spa_core/backtesting/paper_day_counter.py" \
    "$REPO_ROOT/spa_core/backtesting/source_promotion_engine.py" \
    "$REPO_ROOT/scripts/push_v1063.sh" \
    "$REPO_ROOT/KANBAN.json" \
  --message "Sprint v10.63 — MP-1447 BaseAnalytics Phase 4: backtesting/ layer"
