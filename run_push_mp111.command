#!/bin/bash
cd /Users/yuriikulieshov/Documents/SPA_Claude
python3 push_to_github.py \
  --files \
    /Users/yuriikulieshov/Documents/SPA_Claude/spa_core/milestone/__init__.py \
    /Users/yuriikulieshov/Documents/SPA_Claude/spa_core/milestone/milestone_tracker.py \
    /Users/yuriikulieshov/Documents/SPA_Claude/spa_core/paper_trading/cycle_runner.py \
    /Users/yuriikulieshov/Documents/SPA_Claude/spa_core/tests/test_milestone.py \
    /Users/yuriikulieshov/Documents/SPA_Claude/KANBAN.json \
  --message "feat(MP-111): 30-day milestone tracker + honest metrics ✅"
echo "Press Enter to close..."
read
