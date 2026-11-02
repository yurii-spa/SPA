---
trackerStatus:
  type: inbox
title: "Остаток класса «тест пишет в git-tracked data/»: население 68, закрыто 50, писатель каждого остатка НАЗВАН замером"
status: new
source: nimbalyst
created: 2026-11-02
finding_adr: ADR-900
twin_key: "sha256:372631d70c0361d27c57abf318319212ba7d07214a80b2ecb77376a110729acf"
intake_kind: task
---

## Что измерено

Население класса «тест пишет в git-tracked `data/`» ИЗМЕРЕНО по логам джоб
контрольного прогона **41435243848** (`8f34a8894`, 12 шардов из 12, 68 нарушений,
свод не назвал ни одного — ADR-899): **68 тест-модулей · 71 файл `data/`**.
Заказ G895 п. 1 называл **семь** — это был срез ОДНОГО шарда (11), а не класс.

Цикл #1013 (ADR-900) закрыл **50 из 68**. Остаток — **18 тест-модулей**,
и писатель у каждого НАЗВАН замером (зонд по `os.replace`/`io.open`/`os.rename` на
живом прогоне), а не grep'ом по имени файла: у `adapter_status.json` grep давал
**108** кандидатов, у `golive_status.json` — 59.

### Остаток, который агент вправе закрыть сам (16 файлов)

| тест-модуль | файл `data/` | писатель (ИЗМЕРЕН) |
|---|---|---|
| `test_alerts.py` | `data/alert_log.json` | `spa_core/alerts/alert_dispatcher.py` |
| `test_borrowing_cost_optimizer.py` | `data/borrowing_cost_log.json` | `spa_core/analytics/borrowing_cost_optimizer.py` |
| `test_defi_funding_rate_arbitrage_detector.py` | `data/funding_rate_arb_log.json` | `spa_core/analytics/defi_funding_rate_arbitrage_detector.py` |
| `test_defi_lending_rate_spread_analyzer.py` | `data/lending_rate_spread_log.json` | `spa_core/analytics/defi_lending_rate_spread_analyzer.py`, `spa_core/analytics/defi_protocol_lending_rate_spread_analyzer.py` |
| `test_defi_perpetual_funding_rate_analyzer.py` | `data/perp_funding_rate_log.json` | `spa_core/analytics/defi_perpetual_funding_rate_analyzer.py` |
| `test_defi_protocol_cross_asset_correlation_risk_analyzer.py` | `data/cross_asset_correlation_log.json` | `spa_core/analytics/defi_protocol_cross_asset_correlation_risk_analyzer.py` |
| `test_defi_protocol_lending_rate_spread_analyzer.py` | `data/lending_rate_spread_log.json` | `spa_core/analytics/defi_lending_rate_spread_analyzer.py`, `spa_core/analytics/defi_protocol_lending_rate_spread_analyzer.py` |
| `test_protocol_airdrop_eligibility_optimizer.py` | `data/airdrop_eligibility_log.json` | `spa_core/analytics/protocol_airdrop_eligibility_optimizer.py` |
| `test_protocol_cross_chain_yield_arbitrage_detector.py` | `data/cross_chain_arbitrage_log.json` | `spa_core/analytics/protocol_cross_chain_yield_arbitrage_detector.py` |
| `test_protocol_defi_yield_smoothing_analyzer.py` | `data/yield_smoothing_log.json` | `spa_core/analytics/protocol_defi_yield_smoothing_analyzer.py` |
| `test_protocol_economic_attack_simulator.py` | `data/attack_simulation_log.json` | `spa_core/analytics/protocol_economic_attack_simulator.py` |
| `test_protocol_fee_revenue_sustainability_analyzer.py` | `data/fee_revenue_sustainability_log.json` | `spa_core/analytics/protocol_fee_revenue_sustainability_analyzer.py` |
| `test_protocol_insider_activity_monitor.py` | `data/insider_activity_log.json` | `spa_core/analytics/protocol_insider_activity_monitor.py` |
| `test_restaking_risk_analyzer.py` | `data/restaking_risk_log.json` | `spa_core/analytics/restaking_risk_analyzer.py` |
| `test_token_price_volatility_tracker.py` | `data/token_volatility_log.json` | `spa_core/analytics/token_price_volatility_tracker.py` |
| `test_yield_source_concentration_risk.py` | `data/yield_concentration_log.json` | `spa_core/analytics/yield_source_concentration_risk.py` |

Почему их не закрыли три прохода цикла #1013: умолчание пути у них объявлено НЕ в
форме `os.path.join(os.path.dirname(__file__), "..", "..", "data", <имя>)` —
встречаются `_REPO_ROOT`-производные (`os.path.join(_REPO_ROOT, "data", …)`,
`_REPO_ROOT / "data" / …`) и формы, где умолчания на уровне модуля нет вовсе.
Преобразователь их НЕ ТРОНУЛ и НАЗВАЛ — это третий исход, не молчание.

### Остаток, который агент сам закрывать НЕ ВПРАВЕ (5 файлов)

| тест-модуль | файл `data/` | писатель (ИЗМЕРЕН) |
|---|---|---|
| `test_cycle_write_interlock.py` | `data/adapter_status.json` | `spa_core/monitoring/adapter_status_generator.py`, `spa_core/paper_trading/cycle_reporting.py`, `spa_core/paper_trading/cycle_runner.py` |
| `test_cycle_write_interlock.py` | `data/apy_milestone_log.json` | `spa_core/analytics/apy_milestone_tracker.py`, `spa_core/paper_trading/cycle_reporting.py` |
| `test_cycle_write_interlock.py` | `data/gap_monitor.json` | `spa_core/paper_trading/gap_monitor.py` |
| `test_cycle_write_interlock.py` | `data/risk_alerts.json` | `spa_core/paper_trading/gap_monitor.py` |
| `test_redteam_infra.py` | `data/golive_status.json` | `spa_core/paper_trading/cycle_gap_monitor.py`, `spa_core/paper_trading/cycle_runner.py`, `spa_core/paper_trading/golive_checker.py`, `spa_core/redteam/runner.py` |

Это денежный путь и живой go-live трек: `paper_trading/cycle_runner.py`,
`golive_checker.py`, `cycle_reporting.py`, `cycle_gap_monitor.py`. Автономный мандат
их НЕ покрывает (`CLAUDE.md`, «ЗАПРЕЩЕНО автономно»), поэтому правка идёт отдельным
решением, а не прицепом к гигиене тестов. Отдельно замечено: `gap_monitor.py` и
`adapter_status_generator.py` дверь `SPA_DATA_DIR` УЖЕ имеют (ADR-849 §2) и всё равно
попали в замер — значит у них есть ВТОРОЙ путь записи, и он не измерен.

## Почему это не косметика

Сессионный сторож `spa_core/tests/tracked_write_guard.py` поднимает `exitstatus`
сессии, поэтому пока жив хоть один писатель, шард, который его несёт, кончается
кодом 1 ПО ПОСТРОЕНИЮ. «Набор зелёный» нечем предъявить. База
`tracked_write_baseline.json` ПУСТА — дописывать в неё ЗАПРЕЩЕНО (инв. #16).

## Как понять, что готово

Проба `tracked_data_untouched_by_declared_runs` зелена при ПОЛНОЙ поверхности:
объявить в `card_acceptance.TRACKED_WRITE_RUNS` все **68** модулей и получить
«не тронул ни одного файла». Сегодня объявлено 50 и проба зелена на них —
её вердикт НАЗЫВАЕТ свою область сам, чтобы «зелено на срезе» не читалось как
«класс закрыт».

## Что будет после

Контрольный прогон перестанет кончаться кодом 1 по построению, и вердикт набора
станет предъявим — условие, названное заказом G895 п. 1 условием существования.
