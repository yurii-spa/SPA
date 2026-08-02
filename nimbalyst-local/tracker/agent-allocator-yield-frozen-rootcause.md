---
trackerStatus:
  type: agent
title: Аллокатор заморожен на неоптимальной доходности — ребаланс только по нарушению, нет триггера «заработать больше»
status: backlog
source: session-2026-07-23-owner-investigation
created: 2026-07-23
priority: high
domain: money-path (RiskPolicy НЕ трогать; pre_cutover_gate + ADR обязательны)
---

## Что случилось (диагноз, подтверждён кодом 2026-07-23)

Портфель держит **40% в morpho_steakhouse @ 3.47%** (упёрт в абсолютный потолок концентрации) +
**20.6% в кэше @ 0%**, тогда как eligible-вселенная того же/выше тира стоит пустой:
aave_v3 T1 4.78% ($12B), aave_v3_optimism T1 4.80% ($400M), sdai T2 5.50% ($1.2B),
sfrax T2 6.00% ($800M), scrvusd T2 7.00%, frax T2 7.50%. Дневной APY на развёрнутый капитал 5.90%,
бленд с кэшем ≈ 4.7%, суммарно +0.70% за 54 дня.

**Root-cause:**
1. `portfolio_rebalancer.py` → `AllocationTuner.optimize()` **умеет** оптимизировать по APY/Sharpe
   в рамках policy — но вызывается **ТОЛЬКО** когда `ALLOC-001` (`cycle_runner.py:880`) ловит
   нарушение жёсткого лимита. Коммент: «Rebalancer runs ONLY when current positions violate policy
   — not run every cycle to avoid unnecessary churn».
2. 40%@3.47% + 20% cash **не нарушают ни один потолок** ⇒ enforcer = passed ⇒ оптимизатор не
   запускается ⇒ раскладка **заморожена** на неоптимальной доходности бессрочно.
3. **Нет триггера «улучшить доходность»** — оптимизатора никто не просит зарабатывать больше внутри
   безопасного контура.
4. Yield-chase логика (s54_daily_yield_maximizer и др.) работает в SHADOW (ADR-033) — advisory,
   капитал не двигает.
5. Сопутствующее: 5/24 фида stale-fallback (сужают свежую вселенную); `policy_enforcer` возможно
   несёт устаревшие потолки vs `policy.py` (см. memory `optimized-yield-t3-breach`).

## Что нужно сделать (money-path — через pre_cutover_gate + ADR, RiskPolicy НЕ менять)

Добавить **yield-improvement триггер ребаланса** поверх нынешнего violation-only:
- каждый цикл считать оптимальную по APY раскладку тюнером (в рамках существующих потолков RiskPolicy);
- если `expected_apy(optimal) − apy(current) > порог` **за вычетом стоимости переключения** (анти-churn) —
  ребалансировать; иначе логировать «держим, дельта ниже порога» с числами;
- кэш сверх 5%-буфера **обязан быть объяснён** (какие потолки/фиды/режим биндят);
- запретить максить потолок концентрации на протоколе с доходностью ниже медианы eligible-набора;
- всё детерминированно, LLM запрещён, fail-CLOSED на stale-фидах.

## Как понять, что готово

Тест доказывает: при 40%@3.47% рядом с eligible 6% — цикл предлагает ребаланс (а не молчит); кэш>5%
всегда с записанной причиной; RiskPolicy v1.0 byte-identical; прогон через `pre_cutover_gate`; ADR принят.

## Что будет после

Реализуется в изолированном workspace, отдельным authorized-коммитом, после решения владельца.
Связано с целевой архитектурой инвест-агентов — см. `docs/ideas/2026-07-23-head-of-investment-agent-layer.md`
и карту `agent-head-of-investment-layer.md`.
