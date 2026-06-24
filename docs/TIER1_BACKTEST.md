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

## P1 ✅ сделано — реальные данные + правильная метрика для yield

- **`scripts/fetch_historical_apy.py`** тянет РЕАЛЬНУЮ дневную историю APY из DeFiLlama
  (`/chart/{pool}`, gzip, percent→decimal) → `data/bee/defillama_apy_history.json`. Сейчас
  **9 протоколов** реальной истории (aave_v3 до 1235д, compound_v3 1354д, yearn/euler/fluid/
  ethena/aave-base). `professional_backtest._protocol_apy_series` подхватывает их по имени
  протокола (real data предпочтительнее proxy). Фетч встроен в дневной pipeline (best-effort).
- **Ключевой вывод P1:** даже на РЕАЛЬНЫХ данных дневная vol доходности стейблов ≈ 0.1% →
  Sharpe механически 23–84. Это **не баг данных, а природа класса активов**: yield почти
  детерминирован (получаешь доход, он не скачет как цена). **Вывод Tier-1: для yield-стратегий
  Sharpe — неправильная метрика.**
- **Evaluator теперь распознаёт режим:** `LOW_VOL_YIELD` (реальные данные, Sharpe вырожден по
  природе) → ранжирует по **net-of-cost APY + risk-бэнды пакетов**, Sharpe/DSR информационно.
  `DEGENERATE_MOCK` (вырождено И данные не реальные) → UNPROVEN. `NORMAL` → DSR-ранжирование.
  Tail/principal risk (депег/эксплойт) управляется отдельно детерминированным RiskPolicy.
- Текущий вердикт: 53 стратегии валидированы в **Conservative** (~4.3% net). Balanced/
  Aggressive пусто — нужны протоколы с более высокой доходностью (будущая диверсификация).

## P2 ✅ сделано — полное покрытие данных + out-of-sample гейт

- **Реальные данные расширены до 13 протоколов** (добавлены morpho_steakhouse 755д, morpho_blue,
  maple 332д; уточнены DeFiLlama-слаги: morpho symbol=`STEAKUSDC`, maple symbol=`USDC`+meta
  `syrup`). **spark_susds / sky_susds НЕ фетчатся** — RULES.md фиксирует Sky/sUSDS = 0% до
  on-chain GSM Pause Delay ≥ 48h; остаются на консервативном proxy (не противоречим доку).
- **`spa_core/backtesting/tier1/oos.py` — out-of-sample проверка для YIELD.** Вместо Sharpe-OOS
  (вырожден) считает blended net-APY стратегии на in-sample (первые 70%) vs out-of-sample
  (последние 30%) по реальным рядам, выравнивая по общей оси дат (forward-fill — ряды стартуют
  в разные дни). `oos_holds` = OOS-доходность ≥ 80% от in-sample (edge не деградировал).
- **Эффект:** OOS-гейт ужесточил валидацию **53 → 2 стратегии**. 51 стратегия выглядела хорошо
  на полной истории, но её доходность упала в held-out периоде (исторически yields были ~5%,
  сейчас ~3.7%) → не валидируются. Пакеты теперь считают только OOS-прошедшие стратегии.

## P3 ✅ сделано — петля замкнута (backtest→paper→live + capacity + divergence)

- **Capacity (TVL-глубина)** в evaluator: позиция не должна превышать 2% TVL пула. Считает
  `capacity_aum_usd` (макс. размер фонда до нарушения) — критично для масштабирования на внешний
  AUM ($100M-цель). `capacity_ok` обязателен для `validated`.
- **`spa_core/backtesting/tier1/gate.py`** — авторитетный gate допуска. Стратегия `eligible_for_paper`
  только если `validated` (real-data + net-of-cost APY>0 + пакет + OOS-hold + capacity). Пишет
  `data/tier1_gate.json` с причинами блокировки по каждой. Текущий вердикт: **2 eligible
  (s27_stablecoin_carry, s62_yield_ladder_v2), 62 blocked** (в основном `yield_decayed_out_of_sample`).
- **Live-vs-backtest divergence**: сравнивает живой paper-APY с Tier-1-ожидаемым net-APY валидированных
  стратегий. Сейчас `ok` (live 3.6% ≥ expected 3.17% — живой трекинг бэктеста). При обвале → сигнал
  демоушна/ревью.
- **Турнир консультирует gate**: `tournament_engine.check_promotions` аннотирует каждый промоушн
  `tier1_eligible` через `gate.is_eligible()` (advisory, fail-open — не блокирует, промоушны и так
  advisory; параллельная модель, поведение турнира не меняется).
- Pipeline: fetch → tournament → verdict → **gate**. 17 тестов.

## Состояние: Tier-1 P0–P3 завершены ✅

P0 статистика (DSR/PSR/minTRL) · P1 реальные данные + режимы · P2 13 протоколов + OOS ·
P3 gate + capacity + divergence. Дальнейшее (опционально): корреляции пакетов (диверсификация),
расширение capacity-проверки на target-AUM сценарии, hard-enforcement gate (сейчас advisory).
- **P2:** прогон через `scenario_runner.py` (depeg / liquidity-crunch / bear) — worst-case DD.
- **P2:** capacity/liquidity constraints (TVL-глубина) + корреляции портфеля (диверсификация
  пакетов реальная, не мнимая).
- **P3:** enforced gate backtest→paper→live (вход в paper только при DSR-pass + net-APY-порог +
  OOS≥N дней); live-vs-backtest divergence (`bee/backtest_live_fit.py`) → авто-демоушн при деградации.

## Принцип честности
Слой спроектирован «честным по построению»: при коротком треке или mock-данных он **сообщает,
что доверять нельзя**, а не выдаёт красивый рейтинг. Это и есть Tier-1 стандарт.
