#!/bin/bash
# Daily backtest pipeline (Tier-1): real data → tournament → verdict → gate.
# Tier-1 is a PARALLEL analytical layer — never modifies RiskPolicy or the cycle.
# Best-effort fetch: on network failure the last-good real cache persists and the run continues.
set +e
cd /Users/yuriikulieshov/Documents/SPA_Claude
PY=/Users/yuriikulieshov/miniconda3/bin/python3
echo "[$(date -u '+%FT%TZ')] fetch real historical APY (DeFiLlama)..."
$PY scripts/fetch_historical_apy.py
echo "[$(date -u '+%FT%TZ')] mass_tournament (real data)..."
$PY -m spa_core.backtesting.mass_tournament
echo "[$(date -u '+%FT%TZ')] tier1 evaluator (net-of-cost + OOS + capacity)..."
$PY -m spa_core.backtesting.tier1.evaluator
echo "[$(date -u '+%FT%TZ')] tier1 gate (backtest->paper eligibility + live divergence)..."
$PY -m spa_core.backtesting.tier1.gate
echo "[$(date -u '+%FT%TZ')] tier1 correlation (package diversification)..."
$PY -m spa_core.backtesting.tier1.correlation
echo "[$(date -u '+%FT%TZ')] tier1 packages (offered risk tiers)..."
$PY -m spa_core.backtesting.tier1.packages
echo "[$(date -u '+%FT%TZ')] done."
