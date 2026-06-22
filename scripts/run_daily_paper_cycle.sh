#!/bin/bash
# scripts/run_daily_paper_cycle.sh
# MP-1427 (v10.43): Daily paper trading cycle runner
# Wraps CPACycleWithEvidence — called by launchd at 08:00 UTC daily.
# Logs to logs/daily_cycle_YYYYMMDD.log
#
# BUG FIX (PATH 2026-06-20 v12.03):
#   Hardcode PYTHON path — launchd не наследует shell PATH.
#   Используем miniconda python (паритет с com.spa.cyclerunner).

set -e

# miniconda python — AGENT-001 fix (2026-06-22): launchd не наследует PATH
PYTHON=/Users/yuriikulieshov/miniconda3/bin/python3

cd ~/Documents/SPA_Claude

LOG_DIR=~/Documents/SPA_Claude/logs
mkdir -p "$LOG_DIR"
LOG_FILE="$LOG_DIR/daily_cycle_$(date +%Y%m%d).log"

echo "[$(date -u +%Y-%m-%dT%H:%M:%SZ)] Starting daily paper cycle" >> "$LOG_FILE"

"$PYTHON" -c "
import sys
sys.path.insert(0, '.')
from spa_core.backtesting.cpa_cycle_with_evidence import CPACycleWithEvidence
cycle = CPACycleWithEvidence(base_dir='.')
result = cycle.run()
print(result)
" >> "$LOG_FILE" 2>&1

EXIT_CODE=$?

echo "[$(date -u +%Y-%m-%dT%H:%M:%SZ)] Cycle completed (exit $EXIT_CODE)" >> "$LOG_FILE"
exit $EXIT_CODE
