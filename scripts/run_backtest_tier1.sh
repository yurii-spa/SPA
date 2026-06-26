#!/bin/bash
# Daily backtest pipeline (Tier-1): real data → tournament → verdict → gate.
# Tier-1 is a PARALLEL analytical layer — never modifies RiskPolicy or the cycle.
# Best-effort fetch: on network failure the last-good real cache persists and the run continues.
set +e
cd /Users/yuriikulieshov/Documents/SPA_Claude
PY=/Users/yuriikulieshov/miniconda3/bin/python3
echo "[$(date -u '+%FT%TZ')] fetch real historical APY (DeFiLlama)..."
$PY scripts/fetch_historical_apy.py
echo "[$(date -u '+%FT%TZ')] tier1 data integrity (no-lookahead audit)..."
$PY -m spa_core.backtesting.tier1.data_integrity
echo "[$(date -u '+%FT%TZ')] mass_tournament (real data)..."
$PY -m spa_core.backtesting.mass_tournament
echo "[$(date -u '+%FT%TZ')] strategy_tournament_runner (regenerate shadow source from fresh mass results — must NOT freeze; promotion gate reads this)..."
$PY -m spa_core.backtesting.strategy_tournament_runner
echo "[$(date -u '+%FT%TZ')] tier1 evaluator (net-of-cost + OOS + capacity)..."
$PY -m spa_core.backtesting.tier1.evaluator
echo "[$(date -u '+%FT%TZ')] tier1 gate (backtest->paper eligibility + live divergence)..."
$PY -m spa_core.backtesting.tier1.gate
echo "[$(date -u '+%FT%TZ')] tier1 correlation (package diversification)..."
$PY -m spa_core.backtesting.tier1.correlation
echo "[$(date -u '+%FT%TZ')] tier1 packages (offered risk tiers)..."
$PY -m spa_core.backtesting.tier1.packages
echo "[$(date -u '+%FT%TZ')] tier1 canary stage..."
$PY -m spa_core.backtesting.tier1.canary
echo "[$(date -u '+%FT%TZ')] tier1 regime detection..."
$PY -m spa_core.backtesting.tier1.regime
echo "[$(date -u '+%FT%TZ')] tier1 monte-carlo confidence intervals..."
$PY -m spa_core.backtesting.tier1.monte_carlo
echo "[$(date -u '+%FT%TZ')] tier1 VaR/CVaR/ES..."
$PY -m spa_core.backtesting.tier1.var
echo "[$(date -u '+%FT%TZ')] tier1 walk-forward (out-of-sample equity curve + capacity at AUM)..."
$PY -m spa_core.backtesting.tier1.walk_forward_full
echo "[$(date -u '+%FT%TZ')] tier1 verifiable NAV / proof-of-reserves..."
$PY -m spa_core.backtesting.tier1.nav_proof
echo "[$(date -u '+%FT%TZ')] tier1 risk limits (institutional overlay)..."
$PY -m spa_core.backtesting.tier1.limits
echo "[$(date -u '+%FT%TZ')] tier1 return attribution..."
$PY -m spa_core.backtesting.tier1.attribution
echo "[$(date -u '+%FT%TZ')] tier1 benchmark-relative metrics..."
$PY -m spa_core.backtesting.tier1.benchmark
echo "[$(date -u '+%FT%TZ')] tier1 status rollup + problem alert..."
$PY -m spa_core.backtesting.tier1.status --alert
echo "[$(date -u '+%FT%TZ')] tier1 pipeline health/SLO..."
$PY -m spa_core.backtesting.tier1.pipeline_health
echo "[$(date -u '+%FT%TZ')] tier1 run manifest (reproducibility stamp — LAST)..."
$PY -m spa_core.backtesting.tier1.run_manifest
echo "[$(date -u '+%FT%TZ')] done."
