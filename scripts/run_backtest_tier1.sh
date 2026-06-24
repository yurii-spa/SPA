#!/bin/bash
# Daily backtest pipeline (P1): refresh REAL historical APY → mass tournament → Tier-1 verdict.
# Tier-1 is a PARALLEL analytical layer — never modifies RiskPolicy or the canonical cycle.
# Best-effort fetch: if network fails the last-good real cache persists and the run continues.
set +e
cd /Users/yuriikulieshov/Documents/SPA_Claude
PY=/Users/yuriikulieshov/miniconda3/bin/python3
echo "[$(date -u '+%FT%TZ')] fetch real historical APY (DeFiLlama)..."
$PY scripts/fetch_historical_apy.py
echo "[$(date -u '+%FT%TZ')] mass_tournament (real data)..."
$PY -m spa_core.backtesting.mass_tournament
echo "[$(date -u '+%FT%TZ')] tier1 evaluator..."
$PY -m spa_core.backtesting.tier1.evaluator
echo "[$(date -u '+%FT%TZ')] done."
