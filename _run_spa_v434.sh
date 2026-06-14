#!/bin/bash
# SPA-V434: запустить тесты + push
set -euo pipefail

SPA_DIR="/Users/yuriikulieshov/Documents/SPA_Claude"
cd "$SPA_DIR"

echo "=== pytest spa_core/tests/test_dashboard_snapshot.py ==="
python3 -m pytest spa_core/tests/test_dashboard_snapshot.py -v
echo ""

echo "=== push to GitHub ==="
python3 push_to_github.py \
  --files \
    "$SPA_DIR/spa_core/paper_trading/cycle_runner.py" \
    "$SPA_DIR/spa_core/tests/test_dashboard_snapshot.py" \
    "$SPA_DIR/auto_push.py" \
    "$SPA_DIR/data/dashboard_metrics_history.json" \
  --message "feat(SPA-V434): daily dashboard snapshot in cycle_runner, 14 tests"

echo "=== done ==="
