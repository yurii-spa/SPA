#!/bin/bash
# Push MP-208 (risk axes v2) + MP-212 (historical backtest) + MP-213 (milestone check)
# Использование: double-click в Finder или bash _push_mp208_212_213.command
set -e
cd ~/Documents/SPA_Claude

FILES=""
for f in \
  spa_core/risk/risk_axes.py \
  spa_core/risk/policy.py \
  spa_core/backtest/__init__.py \
  spa_core/backtest/historical_backtest.py \
  spa_core/milestone/milestone_v2.py \
  spa_core/tests/test_risk_axes.py \
  spa_core/tests/test_historical_backtest.py \
  spa_core/tests/test_milestone_v2.py \
  docs/ADR_008_risk_axes_v2.md \
  KANBAN.json
do
  [ -f "$f" ] && FILES="$FILES $(pwd)/$f"
done

python3 push_to_github.py --files $FILES \
  --message "feat: MP-208 risk axes v2 + MP-212 historical backtest + MP-213 milestone check ✅"
