#!/usr/bin/env bash
# MP-1433 (v10.49) — SPAError Batch 2: analytics + telegram_protocols_reporter
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$REPO_ROOT"

python3 push_to_github.py \
  --files \
    "$REPO_ROOT/spa_core/analytics/protocol_liquidity_depth_analyzer.py" \
    "$REPO_ROOT/spa_core/analytics/rebalance_cost_estimator.py" \
    "$REPO_ROOT/spa_core/analytics/yield_compressor_score.py" \
    "$REPO_ROOT/spa_core/analytics/yield_timing_optimizer.py" \
    "$REPO_ROOT/spa_core/analytics/protocol_tvl_filter.py" \
    "$REPO_ROOT/spa_core/analytics/protocol_adoption_scorer.py" \
    "$REPO_ROOT/spa_core/telegram_protocols_reporter.py" \
    "$REPO_ROOT/spa_core/tests/test_protocol_liquidity_depth_analyzer.py" \
    "$REPO_ROOT/spa_core/tests/test_rebalance_cost_estimator.py" \
    "$REPO_ROOT/spa_core/tests/test_yield_compressor_score.py" \
    "$REPO_ROOT/spa_core/tests/test_yield_timing_optimizer.py" \
    "$REPO_ROOT/spa_core/tests/test_protocol_tvl_filter.py" \
    "$REPO_ROOT/spa_core/tests/test_protocol_adoption_scorer.py" \
  --message "Sprint v10.49 — MP-1433 SPAError batch 2 backtesting+paper_trading, 10 files"

echo "Push v10.49 complete."
