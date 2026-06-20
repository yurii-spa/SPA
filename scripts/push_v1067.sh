#!/usr/bin/env bash
# Sprint v10.67 — MP-1451: Tests for top 5 untested atomic modules + migration
# Modules: track_store, backup, alert_manager, multi_strategy_runner, pnl_attribution
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"

python3 "$REPO_ROOT/push_to_github.py" \
  --files \
    "$REPO_ROOT/tests/test_track_store.py" \
    "$REPO_ROOT/tests/test_backup.py" \
    "$REPO_ROOT/tests/test_alert_manager.py" \
    "$REPO_ROOT/tests/test_multi_strategy_runner.py" \
    "$REPO_ROOT/tests/test_pnl_attribution.py" \
    "$REPO_ROOT/spa_core/alerts/alert_manager.py" \
    "$REPO_ROOT/spa_core/paper_trading/multi_strategy_runner.py" \
    "$REPO_ROOT/spa_core/persistence/backup.py" \
    "$REPO_ROOT/scripts/push_v1067.sh" \
    "$REPO_ROOT/KANBAN.json" \
  --message "Sprint v10.67 — MP-1451 Tests + atomic migration for 5 untested modules (90 tests GREEN)"
