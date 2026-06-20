#!/bin/bash
# scripts/push_v1243.sh
# Sprint v12.43 — Arbitrum-focused strategies S34–S37
#   S34 Arbitrum Yield (T2, sequencer-down rotation to mainnet)
#   S35 GMX Stablecoin Carry (T2, GLP gate > 8% stable APY)
#   S36 Cross-Chain Optimizer (T2, weekly best-chain tilt + 30% mainnet anchor)
#   S37 Radiant Concentrated (T2, 50% Radiant + 45% mainnet T1 sleeve)
# Tests: tests/test_s34_s37_arbitrum.py (42 tests)
# Registered in spa_core/strategies/strategy_registry.py
#
# SECURITY: never push scripts/cf_install_token.command (CF tunnel token).
set -e
cd ~/Documents/SPA_Claude

python3 push_to_github.py \
  --files \
    /Users/yuriikulieshov/Documents/SPA_Claude/spa_core/strategies/s34_arbitrum_yield.py \
    /Users/yuriikulieshov/Documents/SPA_Claude/spa_core/strategies/s35_gmx_carry.py \
    /Users/yuriikulieshov/Documents/SPA_Claude/spa_core/strategies/s36_cross_chain_optimizer.py \
    /Users/yuriikulieshov/Documents/SPA_Claude/spa_core/strategies/s37_radiant_concentrated.py \
    /Users/yuriikulieshov/Documents/SPA_Claude/spa_core/strategies/strategy_registry.py \
    /Users/yuriikulieshov/Documents/SPA_Claude/tests/test_s34_s37_arbitrum.py \
    /Users/yuriikulieshov/Documents/SPA_Claude/scripts/push_v1243.sh \
  --message "Sprint v12.43 — Arbitrum strategies S34–S37 (sequencer rotation, GMX GLP gate, cross-chain tilt, Radiant concentrated), 42 tests"

echo "✅ v12.43 pushed"
