#!/bin/bash
# scripts/push_v1044.sh
# MP-1428 (v10.44): Paper trading Day 1 readiness checklist
# Push: paper_day1_checklist.py, day1_readiness_check.py, tests
set -e
cd ~/Documents/SPA_Claude

python3 push_to_github.py \
  --files \
    /Users/yuriikulieshov/Documents/SPA_Claude/spa_core/backtesting/paper_day1_checklist.py \
    /Users/yuriikulieshov/Documents/SPA_Claude/scripts/day1_readiness_check.py \
    /Users/yuriikulieshov/Documents/SPA_Claude/tests/test_paper_day1_checklist.py \
  --message "Sprint v10.44 — MP-1428 Paper trading Day 1 readiness checklist, 30 tests"

echo "✅ v10.44 pushed"
