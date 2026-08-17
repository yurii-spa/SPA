---
trackerStatus:
  type: agent
title: Линия время-рядов для 18 форкастеров (поток 3 own-27)
status: done
source: own-27-decision-2026-08-04
created: 2026-08-04
priority: medium
domain: analytics relocation (advisory; risk-gate НЕ трогать)
---

Построить фид живых APY-рядов из data/historical_apy* (оси дат НЕ совпадают — выравнивать по дате) и подключить 18 форкастеров/компараторов. Разблокирует также часть 140 непроводимых Tier-B и 38 dormant-by-design. Список: docs/analytics_relocation_plan_2026-08-04.md, поток 3.

## Как понять, что готово
Модули потока дают видимый выход в своём новом доме (rationale/отчёт/série-скоры), прогоны
тестов зелёные, ни один тест не ослаблен (инв.16).

## Результат (проверка 2026-08-17)
Работа была УЖЕ СДЕЛАНА (линия A1) — карточка отставала от кода. Как и в потоке 1,
«переселение» = ПОДКЛЮЧЕНИЕ модуля на месте: файлы не двигались, импорты не менялись.

* Фид рядов: `spa_core/analytics/_apy_series.py` — читает `data/historical_apy/*.json`
  (5 файлов), `data/apy_series_daily.json`, `adapter_status.json`, `apy_ranking.json`.
  Выравнивание ПО ДАТЕ (оси файлов не совпадают — это и было условием карточки),
  fail-CLOSED при недоборе истории, read-only, кеш по mtime/size.
* Подключение форкастеров: у каждого модуля потока module-level `analyze(context)`;
  агрегатор (`signal_aggregator._ModuleAdapter`) исполняет их как Tier-B entrypoint.
* **16 из 18 оживлены** и дают скор на живых рядах (367 точек по aave_v3 / morpho_blue):
  apy_forecaster, apy_momentum, defi_borrow_rate_forecaster, cross_chain_yield_comparator,
  defi_risk_adjusted_yield_comparator, protocol_defi_cross_chain_yield_normalizer,
  protocol_defi_cross_protocol_yield_arbitrage_scanner, protocol_defi_depeg_contagion_modeler,
  defi_protocol_real_yield_sustainability_rater, defi_yield_sustainability_rater,
  protocol_defi_yield_source_sustainability_ranker, chain_concentration, liquidity_scorer,
  protocol_liquidity_depth_stress_tester, risk_budget, defi_vault_strategy_risk_decomposer
  (последний по построению отвечает только на vault-виды: yearn_v3 26.25, spark_susds 22.5;
  на lending-протоколах честный None).
* **2 из 18 сознательно НЕ оживлены** — кормить нечем без фабрикации, `analyze()` всегда
  None, в Tier-B реестр не возвращены: `defi_liquid_staking_rate_comparator` (в data/ нет
  LST-фида: комиссии валидаторов, peg-дисконт, client diversity, withdrawal delay) и
  `defi_nft_collateral_valuation_model` (нет фида floor-цен/объёмов NFT). Это единственный
  остаток по карточке, и он упирается в отсутствующие фиды, а не в код.
* Плюс 5 бонусных модулей на том же фиде (apy_anomaly_detector, apy_tracker,
  yield_forecast_engine, protocol_defi_yield_seasonality_analyzer, yield_compressor_score).
* Тесты: `spa_core/tests/test_timeseries_lane_modules.py` (полярность падающего/растущего
  ряда, None при недоборе истории и неизвестном протоколе, «контекст-путь не пишет файлов»)
  + `test_apy_series.py` — зелёные, ни один не ослаблен.
* Граница соблюдена: слой advisory/сигнальный, капитал не двигает и исполнение не гейтит.
