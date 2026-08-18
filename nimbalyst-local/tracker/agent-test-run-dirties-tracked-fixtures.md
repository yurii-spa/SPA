---
trackerStatus:
  type: agent-task
title: Прогон тестов пачкает git-tracked фикстуры — «чистое дерево» перестало быть сигналом
status: in-progress
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

## Цикл #275 — семейство `spa_core/analytics/*` закрыто (194 модуля)

**Замер переделан, потому что первый был неполон дважды.** (а) Импорт всех модулей в ОДНОМ
процессе терял 115 из 745: чей-то импорт по дороге подменял `inspect`, и всё, что грузилось
после, падало на ровном месте — «писателя не существует» вместо «замер сломался». Теперь по
СВЕЖЕМУ процессу на модуль (`measure_one.py`). (б) Маска `spa_core/analytics/*.py`
нерекурсивна, а CI гоняет ещё и `spa_core/analytics/gross_of/` — подпакет замерен отдельно:
**ни один** из его 19 модулей не пишет в git-tracked путь, работы там нет.

Итог замера: **194 модуля** с модульной константой, резолвящейся в git-tracked файл
(182 различных пути) — вместо «94 модуля / 59 путей» в оценке выше.

**Механизм — `live_paths.sandboxed_default(path, tree_default)`** (общая форма того, что уже
было руками написано в `borrowing_cost_optimizer.py`). Ставится В ПИСАТЕЛЕ, а не на определении
константы и не в сборке конфига: объявленное умолчание читают живые ассерты
(`assertEqual(cfg["log_path"], LOG_PATH)`, `assertEqual(a.log_path, "data/...")`), и они
остаются в силе — **отдушина под флаг НЕ понадобилась ни одному тесту** (оценка выше её
предполагала). Уводится только путь, совпавший с умолчанием дерева; чужой проходит насквозь.

Четыре свойства функции — четыре покрасневших замера, каждое закреплено тестом
(`test_sandboxed_state_path.py`, +6 тестов, включая положительный контроль прод-ветки):

| Свойство | Что было, если его нет |
|---|---|
| чужой путь — насквозь | партия #1: тесты подменяют `mod.LOG_PATH` на `tmp` и требуют записи туда — 7 красных, и они были ПРАВЫ |
| сравнение нормализованных путей | партия #3: `normpath`/`abspath`/`Path` против «как объявлено» — ВОСЕМЬ `data/*_log.json` писались в дерево при формально стоящем уводе |
| тип возврата = тип входа | партия #3: `Path`→`str` уронил 30 тестов `bridge_risk_assessor` на `'str' object has no attribute 'parent'` |
| `None` проходит насквозь | партия #4: писатель с `log_file: Path = None` — 21 тест `protocol_insider_activity_monitor` на `Path(None)` |

**Отдельно измерено: механическая правка обязана проверяться, а не предполагаться.**
`verify_injections.py` нашёл СЕМЬ писателей, где увод сел не на ту переменную (на `log_dir`
или на `tmp`-файл): увод формально стоит, а пишут по-прежнему по константе. Все семь исправлены
руками.

**Писатели пяти путей от корня `tests/` — ИЗМЕРЕНЫ** (инструментированный прогон `tests/`,
обёртки вокруг `open(w/a)` / `os.replace` / `os.rename`, на каждое попадание — nodeid и кадр стека):

| путь | тест | продовая строка |
|---|---|---|
| `data/hy_regime_log.json` | `tests/test_hy_cycle.py` (12 попаданий, `TestFailClosed` / `TestKillSwitch`) | `risk/regime_gate.py:212 log_regime_change` ← `paper_trading/hy_cycle.py:129 refresh_hy_regime` ← `:191 run_hy_cycle` |
| `data/tear_sheet_summary.json` | `tests/test_tear_sheet.py:547,564 TestRealDataIntegration` | `reporting/tear_sheet_html.py:1152 _atomic_write_json` ← `:96 generate` |
| `data/uptime_prev_state.json` | `tests/test_uptime_monitor.py::test_main_smoke_real_run` | `monitoring/uptime_monitor.py:594 _write_prev_state` ← `:720 _process_agent_alerts` ← `:845 run_all_checks` |
| `data/uptime_status.json` | тот же тест | `monitoring/uptime_monitor.py:831 run_all_checks` ← `:916 main` |
| `data/market_regime.json` | `tests/test_market_regime.py:387 TestCLI._run_cli` | **ПОДПРОЦЕСС** `python3 -m spa_core.analysis.market_regime` с `cwd=<корень>` → `analysis/market_regime.py:257 save_to_cache` |

Последняя строка — отдельный класс: писатель живёт в ДОЧЕРНЕМ процессе, поэтому обёртка
внутри pytest его не видит (её нашли сверкой `git status`, а не пробой). Увод там сработает
через `PYTEST_CURRENT_TEST`, который дочерний процесс наследует, — ради этого признак и был
оставлен вторым в `under_test()`.

### Что ОСТАЛОСЬ (цикл #275 не закрывает карточку)

1. **Пять путей от корня `tests/` — измерены, но НЕ уведены.** Три из пяти писателей лежат в
   `spa_core/risk/` (`regime_gate.py`) и `spa_core/monitoring/` — это не аналитика, у них своя
   зона и свои правила; правка требует отдельной итерации, а не довеска к этой.
2. **Полный прогон `tests/` (13 020 тестов) не перепроверен ПОСЛЕ увода аналитики** — он шёл
   8 минут ради замера писателей и повторно не гонялся.

## Acceptance criteria

- после полного прогона `tests/` в чистом чекауте `origin/main` `git status --porcelain` пуст;
- для каждого из шести путей в теле задачи назван КОНКРЕТНЫЙ писатель (файл:строка), а не гипотеза;
- ни один существующий ассерт не ослаблен и не удалён (инв. #16);
- запись в `docs/journal/<неделя>.md`.

**Не входит:** RiskPolicy / kill-switch / живой трек `data/equity_curve_daily.json` / launchd /
`landing/**`.


---

## СВЕРКА 2026-08-17 — НЕ ЗАКРЫТА, но остаток сузился ровно до пяти путей (замер)

Первый acceptance-критерий («после полного прогона `tests/` `git status
--porcelain` пуст») проверен прогоном, а не по журналу.

### Прогон 1 — `tests/` целиком, из чистого дерева

```
$ git checkout -- data spa_core/data && git status --porcelain   # пусто
$ python3 -m pytest tests/ -q --tb=no
3 failed, 13020 passed, 38 skipped, 880 subtests passed in 471.61s
$ git status --porcelain
 M data/hy_regime_log.json
 M data/market_regime.json
 M data/tear_sheet_summary.json
 M data/uptime_prev_state.json
 M data/uptime_status.json
```

**Пять путей — РОВНО те пять от корня `tests/`, которые раздел «Что ОСТАЛОСЬ»
цикла #275 назвал измеренными, но не уведёнными.** Ни одного лишнего.
(Два падения — `test_mypy_gate`, одно — `test_agent_template_wake_storm`;
средовые, mypy в контейнере не установлен, к карточке отношения не имеют.)

### Прогон 2 — шесть путей из тела карточки и 15 путей замера #274: ЧИСТО

```
$ git checkout -- data && git status --porcelain   # пусто
$ python3 -m pytest spa_core/tests/test_cash_attribution_policy_refusals.py \
      spa_core/tests/test_borrowing_cost_optimizer.py spa_core/tests/test_api.py \
      spa_core/tests/test_alerts.py spa_core/tests/test_engine_bridge.py \
      spa_core/tests/test_airdrop_farming_value_estimator.py \
      spa_core/tests/test_test_run_leaves_tree_clean.py -q
273 passed, 2 skipped in 25.48s
$ git status --porcelain    # пусто
```

То есть все шесть путей ИЗ ТЕЛА КАРТОЧКИ (`spa_core/data/reward_harvesting_log.json`,
`spa_core/data/token_emission_log.json`, `spa_core/database/spa.db`,
`tests/fixtures/{golive_status,paper_evidence_7d,tournament_ranking_7d}.json`)
после прогона их измеренных писателей больше не мутируют — увод работает.
Второй acceptance-критерий (писатель назван файлом:строкой для каждого из шести)
выполнен таблицей замера #274.

### Почему карточка всё-таки НЕ закрывается

Критерий №1 сформулирован как «пусто», а не «почти пусто». Пять путей остаются,
и их писатели живут в `spa_core/risk/regime_gate.py`, `spa_core/monitoring/
uptime_monitor.py`, `spa_core/reporting/tear_sheet_html.py` и в ПОДПРОЦЕССЕ
`python3 -m spa_core.analysis.market_regime` — чужие зоны, отдельная итерация.

### Новая форма того же дефекта, найденная сверкой (назвал, не чинил)

Увод `live_paths.sandboxed_default` завязан на `under_test()`
(`PYTEST_CURRENT_TEST`), поэтому он **не действует, когда модуль исполняет
обычный скрипт**. Замер:

```
$ git checkout -- data && git status --porcelain   # пусто
$ python3 scripts/audit_tier_c_wiring_feasibility.py --tier A --out /tmp/…
$ git status --porcelain
 M data/exit_liquidity_log.json
 M data/liquidation_cascade_log.json
```

(при `--tier B`, где инструмент трогает 479 модулей, набор вырастает до 33
`data/*_log.json` + два `spa_core/data/*_log.json`). Это ровно класс
«сторож смотрит на признак прогона тестов, а вне него молчит», уже дважды
описанный в `agent-tests-reach-live-feed-222`, — но здесь он даёт не отказы,
а грязное дерево от обычного запуска инструмента. Карточка про тестовый прогон,
поэтому чинить не стал; для решения нужна отдельная карточка.
