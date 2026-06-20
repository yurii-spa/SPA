#!/usr/bin/env bash
# scripts/push_v1062.sh
# Sprint v10.62 — MP-1446: Atomic Batch 5 (15 files) + coverage report + KANBAN
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$REPO_ROOT"

echo "=== Sprint v10.62 — MP-1446 Atomic Batch 5 push ==="
echo "Root: $REPO_ROOT"
echo ""

python3 push_to_github.py \
  --files \
    "$REPO_ROOT/spa_core/paper_trading/cycle_runner.py" \
    "$REPO_ROOT/spa_core/paper_trading/golive_checker.py" \
    "$REPO_ROOT/spa_core/paper_trading/gap_monitor.py" \
    "$REPO_ROOT/spa_core/paper_trading/drawdown_analytics.py" \
    "$REPO_ROOT/spa_core/paper_trading/yield_attribution.py" \
    "$REPO_ROOT/spa_core/paper_trading/concentration_analytics.py" \
    "$REPO_ROOT/spa_core/paper_trading/risk_contribution.py" \
    "$REPO_ROOT/spa_core/paper_trading/progress_tracker.py" \
    "$REPO_ROOT/spa_core/paper_trading/alpha_decay.py" \
    "$REPO_ROOT/spa_core/paper_trading/tail_risk.py" \
    "$REPO_ROOT/spa_core/shadow/shadow_tracker.py" \
    "$REPO_ROOT/spa_core/milestone/milestone_tracker.py" \
    "$REPO_ROOT/spa_core/audit/audit_trail.py" \
    "$REPO_ROOT/spa_core/audit/data_integrity.py" \
    "$REPO_ROOT/spa_core/adapters/sky_susds_feed.py" \
    "$REPO_ROOT/spa_core/tests/test_drawdown_analytics.py" \
    "$REPO_ROOT/spa_core/tests/test_alpha_decay.py" \
    "$REPO_ROOT/scripts/atomic_coverage_report.sh" \
    "$REPO_ROOT/scripts/push_v1062.sh" \
    "$REPO_ROOT/KANBAN.json" \
  --message "Sprint v10.62 — MP-1446 Atomic batch 5, 15 files + coverage report + KANBAN"

echo ""
echo "✅ Sprint v10.62 pushed"
