---
trackerStatus:
  type: agent-task
title: Прогон тестов пачкает git-tracked фикстуры — «чистое дерево» перестало быть сигналом
status: backlog
priority: medium
source: session-2026-08-04-cycle114
created: 2026-08-04
domain: тесты (tests/fixtures/**, spa_core/data/**, spa_core/database/spa.db) + гигиена приёмки; НЕ risk, НЕ сайт, НЕ деплой
---

## Как найдено

Побочная находка цикла #114 (задача — фиксированные порты в `tests/test_fund_api.py`, к фикстурам
отношения не имеет). После прогона среза `tests/` в рабочем дереве `git status` показал
изменёнными файлы, которых цикл не касался.

## Что измерено

Прогон `tests/` (12964–12966 тестов) в ДВУХ деревьях — своём и КОНТРОЛЬНОМ на чистом
`origin/main e2c80a555`. После прогона `git status --porcelain` в **обоих**:

```
 M spa_core/data/reward_harvesting_log.json
 M spa_core/data/token_emission_log.json
 M spa_core/database/spa.db
 M tests/fixtures/golive_status.json
 M tests/fixtures/paper_evidence_7d.json
 M tests/fixtures/tournament_ranking_7d.json
```

Контроль мутировал **тот же набор** ⇒ это поведение самого набора тестов, а не чьей-то правки.
Все шесть файлов **git-tracked**.

## Почему это стоит починить

1. **«Чистое дерево» больше ничего не значит.** После любого прогона `git status` заведомо
   грязный, поэтому им нельзя проверить «я не задел лишнего» — а это ровно та проверка, которой
   цикл отделяет свои правки от чужих перед пушем.
2. **Одна невнимательность = мусор на origin.** Циклы пушат явным списком файлов, и пока список
   пишется руками, защита держится только на внимательности — той самой, что уже отказала 30.07
   (столкновение двух сессий на одной карточке, карточка `agent-card-claim-collision-guard`).
   Опубликованная `spa.db` или переписанная фикстура тихо сдвинет ожидания других тестов.
3. **Ломает `git stash`.** Известный хвост: `stash pop` конфликтует на этой же churn-мутации,
   и правки остаются в стэше (`git-stash-data-churn-conflict`).
4. Мутация фикстур в принципе делает набор **зависимым от порядка**: тест, читающий фикстуру
   после того, как её переписал другой тест, проверяет уже не то, что записано в репозитории.

## Что предлагается сделать

Найти писателей (для каждого из шести путей — какой тест/модуль пишет) и увести запись в
`tmp_path`/временную копию, как это уже сделано в других местах набора. Отдельно решить, должны ли
`spa_core/database/spa.db` и `spa_core/data/*_log.json` вообще быть git-tracked артефактами.

**Осторожно:** сначала ИЗМЕРИТЬ писателя, а не гадать по имени файла — в этом репозитории уже был
класс дефектов «тест пишет в живое состояние» (`tests-write-live-alert-state`), где список
писателей по построению неполон, потому что часть путей резолвится статически при импорте.

## ИЗМЕРЕННЫЕ ПИСАТЕЛИ (2026-08-17, цикл #274) — файл:строка, не гипотеза

Замер: инструментированный прогон `pytest spa_core/tests/` с обёртками вокруг
`builtins.open(w/a)` · `os.replace`/`rename` · `shutil.copy*` · `sqlite3.connect`; список
трекаемых путей — из `git ls-files`; на каждое попадание записан nodeid теста И кадр стека.

| трекаемый путь | тест-писатель | продовая строка, которая резолвит путь |
|---|---|---|
| `data/adapter_status.json` | `test_cash_attribution_policy_refusals.py:438` | `monitoring/adapter_status_generator.py:939 write` ← `:964 run_and_write` ← `cycle_runner.py:974 run_cycle` |
| `data/gap_monitor.json` | тот же | `paper_trading/gap_monitor.py:332 _write` |
| `data/risk_alerts.json` | тот же | `paper_trading/gap_monitor.py:384 _atomic_write_json` ← `:401 _save_alerts_doc` |
| `data/apy_milestone_log.json` | тот же | `analytics/apy_milestone_tracker.py:284 _save` ← `cycle_reporting.py:530` |
| `data/exit_liquidity_log.json` | тот же | `analytics/protocol_exit_liquidity_analyzer.py:50 _atomic_log` |
| `data/yield_farming_roi_log.json` | тот же | `analytics/yield_farming_roi_calculator.py:211 _append_log` ← `signal_aggregator.py:346` |
| `data/yield_volatility_surface_log.json` | тот же | `analytics/yield_volatility_surface_analyzer.py:159 _log_result` ← `signal_aggregator.py:346` |
| `spa_core/data/reward_harvesting_log.json` | тот же | `analytics/defi_reward_harvesting_optimizer.py:49 _save_log` |
| `spa_core/data/token_emission_log.json` | тот же | `analytics/protocol_token_emission_analyzer.py:58 _save_log` |
| `data/borrowing_cost_log.json` | `test_borrowing_cost_optimizer.py`, **69 тестов** | `analytics/borrowing_cost_optimizer.py:214 _append_log` |
| `data/airdrop_farming_log.json` | `test_airdrop_farming_value_estimator.py:438 test_none_config` | `analytics/airdrop_farming_value_estimator.py:52 _atomic_log` |
| `data/alert_log.json` | `test_alerts.py::TestRunAlertsCli` (2 теста) | `alerts/alert_dispatcher.py:519 _append_ring_buffer` |
| `spa_core/database/spa.db` | `test_api.py`, **5 тестов** | `database/connection.py:66` ← `database/init_db.py:253 init_database` ← `api/_shared.py:197` |
| `data/live_execution_log.json` | `test_engine_bridge.py` | `execution/engine_bridge.py:195 __init__` |
| `data/chains_status.json` | всплыл на ~20 % повторного прогона | `data_pipeline/defillama_fetcher.py:642` И `export_data.py:95 write_json` (чокпоинт всей выгрузки, каталог из модульного `OUTPUT_DIR`) |

**Главная находка: ни один писатель не является «тестом, забывшим подменить путь».**
`test_run_cycle_wires_the_refusal_into_the_owner_facing_artifact` передаёт
`data_dir=str(tmp_path)` и `allow_live_write=False`, его докстринг дословно обещает «the live
track is never read or written» — и ОДИН этот тест пачкает ДЕВЯТЬ путей: `run_cycle` не
протаскивает `data_dir` в веер, а веер резолвит пути из собственного `__file__`.

**Границы замера, честно:** первый прогон был прерван на 9 %, и `data/live_execution_log.json`
(14-й путь) он НЕ увидел — его нашёл уже сторож. Поэтому канареечный срез сторожа обязан расти
вместе с находками.

## ОСТАТОК после цикла #274 (карточку НЕ закрывать)

Закрыто: механизм увода (`live_paths.sandboxed_state_path` / `sandboxed_state_dir`,
`tracked_db_guard`), сторож с положительным контролем, и **15 путей** — все шесть из тела карточки
плюс девять, найденных замером.

Открыто и ИЗМЕРЕНО (не гипотеза):

1. **59 путей `data/<анализатор>_log.json`** — однородное семейство: 94 модуля
   `spa_core/analytics/*.py` с копипастой
   `_LOG_PATH = os.path.join(os.path.dirname(__file__), "..", "..", "data", "<name>_log.json")`.
   Всплывают за 20 %-й отметкой полного прогона. Починка — увод в РЕЗОЛВЕРЕ модуля (не в
   `atomic_save`: увод только записи рассинхронизирует её с чтением, а увод чтения обнулил бы
   законные `live_data`-чтения). Это отдельная итерация: механическая правка 94 файлов —
   big-bang, запрещённый `CLAUDE.md`. Блэст-радиус измерен: `assertTrue(mod.DATA_FILE.exists())`
   (≈16 тестов) переживает увод, а `assertIn("data", DEFAULT_LOG_FILE)` в
   `test_protocol_defi_position_sizing_optimizer.py:933` и
   `test_defi_protocol_insurance_coverage_analyzer.py:1226` потребует правки под флаг.
2. **5 путей от корня `tests/`**: `data/{hy_regime_log,market_regime,tear_sheet_summary,
   uptime_prev_state,uptime_status}.json`. Писатели не мерены.

## Acceptance criteria

- после полного прогона `tests/` в чистом чекауте `origin/main` `git status --porcelain` пуст;
- для каждого из шести путей в теле задачи назван КОНКРЕТНЫЙ писатель (файл:строка), а не гипотеза;
- ни один существующий ассерт не ослаблен и не удалён (инв. #16);
- запись в `docs/journal/<неделя>.md`.

**Не входит:** RiskPolicy / kill-switch / живой трек `data/equity_curve_daily.json` / launchd /
`landing/**`.
