---
trackerStatus:
  type: agent
title: Переселить 9 трекеров в слой отчётности (поток 2 own-27)
status: done
source: own-27-decision-2026-08-04
created: 2026-08-04
priority: medium
domain: analytics relocation (advisory; risk-gate НЕ трогать)
---

9 трекеров/отчётников из бывшего Tier-B подключить секциями в пост-цикловый analytics_runner (MP-104) и/или дневной дайджест. Список: docs/analytics_relocation_plan_2026-08-04.md, поток 2.

## Как понять, что готово
Модули потока дают видимый выход в своём новом доме (rationale/отчёт/série-скоры), прогоны
тестов зелёные, ни один тест не ослаблен (инв.16).

## Результат (проверка 2026-08-17)
Работа была УЖЕ СДЕЛАНА (задача A4) — карточка отставала от кода. Как и в потоке 1,
«переселение» = ПОДКЛЮЧЕНИЕ модуля на месте, а не перенос файла: ни один модуль не сдвинут,
ни один импорт не изменён, shim не понадобился.

* Подключение: `spa_core/analytics/report_sections.py` — все 9 модулей плана в
  `_SECTION_BUILDERS` (`portfolio_stats`, `portfolio_volatility_tracker`,
  `yield_attribution_tracker`, `defi_protocol_market_share_tracker`,
  `adapter_health_scorecard`, `lp_position_tracker`, `staking_reward_tracker`,
  `chain_fee_tracker`, `governance_token_value_tracker`).
* Потребитель: `spa_core/analytics/analytics_runner.py` (MP-104) — блок `sections` в
  `data/analytics_summary.json`, второй пояс try/except поверх per-секционного fail-safe.
* Живой выход на копии data/ (45 баров трека): OK — portfolio_stats,
  portfolio_volatility_tracker, yield_attribution_tracker,
  defi_protocol_market_share_tracker, adapter_health_scorecard; честный SKIPPED с причиной —
  lp_position_tracker, staking_reward_tracker (нет файлов позиций), chain_fee_tracker
  (нет per-chain gas-фида и цены ETH), governance_token_value_tracker (нет фида токеномики).
  Ни одного ERROR, `errors: []`.
* Тесты: `spa_core/tests/test_report_sections.py` + `test_analytics_runner*.py` — зелёные,
  ни один не ослаблен.
* Граница соблюдена: секции только отчётные, капитал не двигают и ничего не гейтят.
