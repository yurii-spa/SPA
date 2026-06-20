#!/bin/bash
# push_v1240.sh — S31 Bear Market Hedge + S32 Market Neutral (regime-defensive)
# Запуск: bash ~/Documents/SPA_Claude/scripts/push_v1240.sh
#
# Контекст: backtest показал S7 Pendle-YT = −14.28% APY (3.73% max DD) в bear-сценарии.
# S31 — regime-aware защитная стратегия (BEAR: 80% T1 + 15% Sky + 5% cash, zero T2/YT;
#       BULL: 50% T1 + 35% T2 + 10% Pendle PT + 5% cash; плавный 7-дневный переход).
# S32 — true market-neutral (фиксированно 50% T1 / 45% T2 / 5% cash, недельный ребаланс).
#
# PAT читается из Keychain (GITHUB_PAT_SPA) — НИКОГДА не хардкодить в файл.
set -euo pipefail
cd ~/Documents/SPA_Claude

ROOT="$HOME/Documents/SPA_Claude"

# ── push_to_github.py сам читает PAT из Keychain; явно передавать не нужно ────
python3 push_to_github.py \
  --files \
    "$ROOT/spa_core/strategies/s31_bear_market_hedge.py" \
    "$ROOT/spa_core/strategies/s32_market_neutral.py" \
    "$ROOT/spa_core/strategies/strategy_registry.py" \
    "$ROOT/tests/test_s31_s32_hedge.py" \
    "$ROOT/scripts/push_v1240.sh" \
  --message "feat(strategies): S31 Bear Market Hedge + S32 Market Neutral (regime-defensive, 47 tests)

Backtest revealed S7 Pendle-YT posts -14.28% APY (3.73% max DD) in the bear
scenario. Add two defensive strategies that protect the book when speculative
strategies fail:

S31 BearMarketHedgeStrategy (T1, regime-aware):
  - Bear detection: Aave util <50% | avg T2 APY <4% | any APY decline >1%/week
  - BEAR  book: 40% Aave + 40% Compound + 15% Sky sUSDS + 5% cash
                (zero T2, zero Pendle/YT) → target 3.5-4.5% APY, DD <0.5%
  - BULL  book: 25% Aave + 25% Compound + 17.5% Fluid + 17.5% Ethena
                + 10% Pendle PT (fixed-rate, not YT) + 5% cash → target 6-8% APY
  - Gradual 7-day / ~14.29%(=1/7)-per-day transition to avoid whipsaws

S32 MarketNeutralStrategy (T2, no market timing):
  - Fixed 50% T1 / 45% T2 / 5% cash regardless of regime, rebalanced weekly
  - T1 = equal-weight Aave+Compound+Sky; T2 = top 3 by APY, equal-weight
  - Target 5-6% APY (~5.5%) with <1% drawdown

Registered S31/S32 in strategy_registry. tests/test_s31_s32_hedge.py: 47 tests,
all passing (allocation per regime, signal detection, 7-day transition, weekly
rebalance, top-3 T2 selection). Stdlib only, advisory/read-only, LLM-free."

echo "✅ push_v1240 done"
