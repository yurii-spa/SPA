#!/bin/bash
cd ~/Documents/SPA_Claude
python3 push_to_github.py \
  --files /Users/yuriikulieshov/Documents/SPA_Claude/spa_core/governance/__init__.py \
          /Users/yuriikulieshov/Documents/SPA_Claude/spa_core/governance/kill_switch.py \
          /Users/yuriikulieshov/Documents/SPA_Claude/spa_core/paper_trading/cycle_runner.py \
          /Users/yuriikulieshov/Documents/SPA_Claude/scripts/kill_switch_drill.py \
          /Users/yuriikulieshov/Documents/SPA_Claude/spa_core/tests/test_kill_switch.py \
          /Users/yuriikulieshov/Documents/SPA_Claude/KANBAN.json \
  --message "feat(MP-108): Kill-switch engine + drill script, 32 tests ✅"
echo "Exit code: $?"
