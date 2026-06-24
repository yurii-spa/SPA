#!/bin/bash
# Daily backtest pipeline: run the mass tournament, then the Tier-1 verdict over it.
# Tier-1 is a PARALLEL analytical layer (deflated Sharpe / net-of-cost / packages) —
# it never modifies RiskPolicy or the canonical cycle.
set +e
cd /Users/yuriikulieshov/Documents/SPA_Claude
PY=/Users/yuriikulieshov/miniconda3/bin/python3
echo "[$(date -u '+%FT%TZ')] mass_tournament..."
$PY -m spa_core.backtesting.mass_tournament
echo "[$(date -u '+%FT%TZ')] tier1 evaluator..."
$PY -m spa_core.backtesting.tier1.evaluator
echo "[$(date -u '+%FT%TZ')] done."
