#!/bin/bash
# scripts/push_v1043.sh
# MP-1427 (v10.43): launchd daily cycle setup
# Push: run_daily_paper_cycle.sh, com.spa.daily_cycle.plist, install_daily_cycle.sh, tests
set -e
cd ~/Documents/SPA_Claude

python3 push_to_github.py \
  --files \
    /Users/yuriikulieshov/Documents/SPA_Claude/scripts/run_daily_paper_cycle.sh \
    /Users/yuriikulieshov/Documents/SPA_Claude/scripts/com.spa.daily_cycle.plist \
    /Users/yuriikulieshov/Documents/SPA_Claude/scripts/install_daily_cycle.sh \
    /Users/yuriikulieshov/Documents/SPA_Claude/tests/test_daily_cycle_infra.py \
  --message "Sprint v10.43 — MP-1427 launchd daily cycle setup, 25 tests"

echo "✅ v10.43 pushed"
