#!/bin/bash
# MP-135 push — double-click to run
cd "$(dirname "$0")"
python3 push_to_github.py \
  --files \
    spa_core/paper_trading/strategy_consolidator.py \
    spa_core/tests/test_strategy_consolidator.py \
    KANBAN.json \
  --message "feat(SPA-V435): MP-135 Strategy S0-S5 Consolidator & Ranker — 59 tests"
echo
echo "--- Done. Press any key to close ---"
read -n 1
