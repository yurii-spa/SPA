#!/bin/bash
# scripts/push_v1247.sh
# Sprint v12.47 — Morpho max-allocation strategies S38–S39 (MP-1247)
#   S38 Morpho Max (T2, policy-COMPLIANT): Morpho Blue at 20% T2 cap +
#       Euler 20% + Aave 35% + Compound 20% + 5% cash → ~3.95% blended APY.
#   S39 Morpho Max+ (T2, RESEARCH-only): Morpho Blue at 25% (ABOVE current
#       20% T2 per-protocol cap) → ~4.1% blended APY; NON-compliant under
#       RiskPolicy v1.0, advisory pending a cap-raise ADR.
# Rationale: Morpho Blue USDC is the highest-APY venue (365-day mean ≈ 6.87%)
#   but the live book holds it at only ~1.9% — these strategies capture the spread.
# Tests: tests/test_s38_s39_morpho.py (21 tests, all pass)
# Registered in spa_core/strategies/strategy_registry.py
#
# SECURITY: never push scripts/cf_install_token.command (CF tunnel token).
set -e
cd ~/Documents/SPA_Claude

python3 push_to_github.py \
  --files \
    /Users/yuriikulieshov/Documents/SPA_Claude/spa_core/strategies/s38_morpho_max.py \
    /Users/yuriikulieshov/Documents/SPA_Claude/spa_core/strategies/s39_morpho_max_plus.py \
    /Users/yuriikulieshov/Documents/SPA_Claude/spa_core/strategies/strategy_registry.py \
    /Users/yuriikulieshov/Documents/SPA_Claude/tests/test_s38_s39_morpho.py \
    /Users/yuriikulieshov/Documents/SPA_Claude/scripts/push_v1247.sh \
  --message "Sprint v12.47 — Morpho max-allocation S38 (compliant ~3.95%) + S39 (research, cap-raise ~4.1%), 21 tests"

echo "✅ v12.47 pushed"
