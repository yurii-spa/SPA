#!/usr/bin/env bash
# Sprint v10.99 — MP-1483 Pre-launch validation 38/40 PASS
set -euo pipefail
cd "$(dirname "$0")/.."

python3 push_to_github.py \
  --files \
    spa_core/backtesting/pre_launch_validation.py \
    spa_core/adapters/defillama_feed.py \
    spa_core/adapters/sky_susds_feed.py \
    spa_core/data_pipeline/defillama_fetcher.py \
    data/equity_curve_daily.json \
    data/adapter_status.json \
    data/gap_monitor.json \
    data/paper_trading_status.json \
    data/backtest/paper_ready_gate.json \
    data/backtest/owner_paper_acceptance_gate.json \
    tests/test_pre_launch_v2.py \
    scripts/push_v1099.sh \
  --message "Sprint v10.99 — MP-1483 Pre-launch validation 38/40 PASS"
