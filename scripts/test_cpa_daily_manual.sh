#!/bin/bash
# Manual test run of CPA daily cycle
cd ~/Documents/SPA_Claude
/Users/yuriikulieshov/miniconda3/bin/python3 -m spa_core.backtesting.cpa_daily_cycle \
  --run \
  --no-telegram \
  --date $(date +%Y-%m-%d)
