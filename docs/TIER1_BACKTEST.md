# Tier-1 бэктест и валидация (параллельная модель)

> Заложено 2026-06-24. **Параллельный слой** — НЕ меняет RiskPolicy v1.0, дневной цикл
> или любой канонический модуль (по требованию: «не противоречить документации → делать
> параллельной моделью»). Чистый stdlib, детерминированно, LLM запрещён. Цель — поднять
> валидацию стратегий до практик квант-фондов Tier-1 и подвести фундамент под risk-tiered
> «пакеты» (Conservative / Balanced / Aggressive, как на лендинге).

## Зачем (главная проблема, которую слой вскрыл)

Турнир ранжирует ~64 стратегии по Sharpe и продвигает лучшие. Tier-1 риск-комитет это
не примет по двум причинам, и обе подтверждены на наших данных:

1. **Selection bias.** Из 64 испытаний «лучшее» завышено просто удачей. Ожидаемый
   макс-Sharpe из 64 испытаний без всякого edge уже высок — победителя надо сравнивать
   с этим бенчмарком (Deflated Sharpe Ratio), а не с нулём.
2. **Данные mock.** Дневной бэктест гоняется на `MOCK_APY` (константы) → vol ≈ 0.06%,
   Sharpe 24–76 (в реале хорошо = 1–3). Метрики математически вырождены. Tier-1-слой это
   **детектирует и отказывается сертифицировать** (`data_quality: DEGENERATE`).

## Что построено (P0 — фундамент)

| Модуль | Что делает |
|---|---|
| `spa_core/backtesting/tier1/deflated_sharpe.py` | PSR, **Deflated Sharpe Ratio**, expected-max-Sharpe под нулём, min-track-record-length. Коррекция на multiple-testing (Bailey & López de Prado), всё на `statistics.NormalDist`. |
| `spa_core/backtesting/tier1/cost_model.py` | **Net-of-cost** APY: газ + slippage + bridge как годовой drag. Агрессивные (частый ребаланс) теряют edge на costs. |
| `spa_core/backtesting/tier1/evaluator.py` | Вердикт над `mass_tournament_results.json`: DSR/PSR/minTRL + net-of-cost на стратегию, **детектор вырожденных данных**, назначение в **пакеты**. Пишет `data/tier1_verdict.json`. |
| `scripts/run_backtest_tier1.sh` + `com.spa.mass_tournament` | Дневной pipeline: mass_tournament → tier1 evaluator (06:30, перед турниром). |
| `spa_core/tests/test_tier1_backtest.py` | 9 тестов (математика + детектор вырожденности). |

**Текущий честный вердикт:** `data_quality: DEGENERATE` (median Sharpe 49.5 / vol 0.06%),
0 DSR-passers, все грейды `UNPROVEN`. То есть: **рейтингу турнира пока доверять нельзя** —
нужна реальная история.

## Risk-tiered пакеты (твоё видение)

`evaluator.PACKAGES` — продуктовые тиры, в которые попадает стратегия по NET APY и worst-DD:

| Пакет | NET APY | Лимит просадки |
|---|---|---|
| **Conservative** | 2–6% | ≤ 3% |
| **Balanced** | 6–12% | ≤ 10% |
| **Aggressive** | 12%+ | ≤ 25% |

DSR гейтит доверие: пакет предлагается клиенту, только когда его стратегии **прошли DSR**
на реальных данных. Сейчас кандидаты есть, но все `UNPROVEN` (mock).

## Дорожная карта до полного Tier-1

- **P0 ✅ сделано:** DSR/PSR/minTRL, net-of-cost, детектор вырожденности, пакеты, pipeline.
- **P1 (следующее):** убить `MOCK_APY` → бэктест на **реальной point-in-time истории**
  (`data/historical_apy/` расширить с 3–5 до всех ~27 протоколов через DeFiLlama; без
  lookahead/survivorship). Без этого DSR останется UNPROVEN.
- **P1:** подключить существующий `walk_forward_validator.py` → out-of-sample проверка.
- **P2:** прогон через `scenario_runner.py` (depeg / liquidity-crunch / bear) — worst-case DD.
- **P2:** capacity/liquidity constraints (TVL-глубина) + корреляции портфеля (диверсификация
  пакетов реальная, не мнимая).
- **P3:** enforced gate backtest→paper→live (вход в paper только при DSR-pass + net-APY-порог +
  OOS≥N дней); live-vs-backtest divergence (`bee/backtest_live_fit.py`) → авто-демоушн при деградации.

## Принцип честности
Слой спроектирован «честным по построению»: при коротком треке или mock-данных он **сообщает,
что доверять нельзя**, а не выдаёт красивый рейтинг. Это и есть Tier-1 стандарт.
