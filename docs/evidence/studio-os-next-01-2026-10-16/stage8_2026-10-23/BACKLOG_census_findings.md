# Backlog находок изолированного census реестра проб — этап 8 STUDIO-OS-NEXT-01 (2026-10-23)

> Файл ветки `integ/studio-os-next-01-stab`. Рабочий трекер НЕ тронут (ограничение ARB). Задачи
> ниже — не исправлены прицепом (инв. #16): каждая — отдельная работа со своей пробой приёмки.
> ROADMAP: п. 17 STUDIO-OS-NEXT-01 (ADR-763), пакет «стабилизация набора и измеримость §49».

## Источник и предмет

| поле | значение |
|---|---|
| прибор | `spa_core/monitoring/live_registry_scene_census.py` (три сессии pytest: record / empty / grown) |
| прогон | [39913695961](https://github.com/yurii-spa/SPA/actions/runs/39913695961), SHA `3f2482d22`, код прибора 1 |
| повтор | [39919735880](https://github.com/yurii-spa/SPA/actions/runs/39919735880), SHA `ffafdf1a5` (docs-only поверх) — 2 761/2 761 строк и 22/22 находки совпали поимённо (`STAGE8_EVIDENCE.md` §2) |
| артефакт | `../live_registry_census_2026-10-23_run39913695961/live_registry_scene_census.json` |
| счёт | записано 2 761 · дошли до реестра 835 · `vacuous_over_members` **22** · `unmeasured` **78** · ошибок сборки под пустым реестром **2 файла** |

Утверждения о результате относятся к SHA своего прогона; разбор ниже — о `3f2482d22`.

## Сводка разбора — дефекты отдельно от ограничений измерения

| группа | строк | род | вывод |
|---|---|---|---|
| V1 | 4 | **подтверждённый дефект теста** | утверждение над членами реестра проходит на пустом реестре (цикл без итераций / только отрицательное утверждение) |
| V2 | 18 | **ложная находка прибора** (ограничение измерения) | тело теста реестр не перечисляет — по исходнику; механизм приписывания чтений кадру теста НЕ измерен |
| U1 | 70 | ограничение измерения | параметризация по реестру схлопывается под пустым реестром в `[NOTSET]`; страж полноты `test_the_parametrized_population_is_the_whole_registry` при этом КРАСНЕЕТ (`breaks_on_substitution`) — не дефект |
| U2 | 1 | ограничение измерения (артефакт прибора) | синтетический член режима grown `lrs_synthetic_probe_g95_p2` отсутствует в базовой записи по построению |
| U3a | 2 | **подтверждённая зависимость теста от окружения** + конфигурация прибора | базовый прогон красен, потому что `--basetemp` census лежит ВНУТРИ git-checkout (`lrs-work/`); дифференциальный замер: снаружи git — passed, внутри — failed |
| U3b | 5 | ограничение измерения, причина НЕ установлена | `test_green_by_construction_census.py` красен на базе в сессии census, зелен в ci-control и в обоих вариантах basetemp локально |
| C | 2 файла | ограничение измерения | реестр читается на ИМПОРТЕ (`PROBE = PROBES["…"]`) ⇒ под пустым реестром ошибка сборки всего файла: громкий отказ, а не тихая зелень; вердикт по тестам файла в режиме empty не получен |
| G16 | 2 модуля | потерянное покрытие (учтено явно) | строки переписи G16 `green_by_construction_census` (`census_budget_refused`) и `heir_all_rows_price` (`census_reentry_refused`) — `unmeasured` с причиной |

78 = U1 70 (69 параметров + `[NOTSET]`) + U2 1 + U3a 2 + U3b 5. Не все 78 — ошибки кода: подтверждена
зависимость от окружения у двух тестов (U3a); остальные 76 — пределы измерения.

## Задачи

Формат: ID · приоритет · владелец · доказательство · критерий приёмки (машинный, ДО работы) · ROADMAP.
Владелец по ADR-285 — агент-исполнитель (ни один пункт не касается денег, публичных чисел или
необратимых действий); приёмка — ARB.

### B-1 · P2 · V1: четыре утверждения над пустым реестром

| тест | форма дефекта |
|---|---|
| `spa_core/tests/test_acceptance_probe_writer.py::ProbeRegistryHasExactlyOneCopy::test_validator_accepts_exactly_the_registered_names` | `for name in sorted(ca.PROBES)` — на пустом реестре ноль итераций |
| `…::test_unregistered_name_is_refused_and_names_the_alternatives` | `for name in ca.PROBES: assertIn(name, reason)` — то же |
| `spa_core/tests/test_cio_acceptance_rollup.py::test_a_probe_losing_its_registration_loses_its_declaration` | только `"Architecture" not in …` — истинно и при пустом ответе функции; положительной стороны нет |
| `…::test_declaration_values_that_are_not_names_are_ignored` | только отрицательные `not in` — то же |

- **Доказательство:** строки `vacuous_over_members` артефакта; исходник (`test_acceptance_probe_writer.py:74–84`,
  `test_cio_acceptance_rollup.py:479–494`). Смягчение: глобальный страж полноты реестра (≥ 60) краснеет при
  пустом реестре — набор в целом пустоту ловит, каждый из четырёх тестов в отдельности — нет.
- **Приёмка:** census на SHA с правкой — у всех четырёх nodeid вердикт ≠ `vacuous_over_members`
  (ожидаемо `breaks_on_substitution`), утверждения не ослаблены (добавлена предпосылка «реестр непуст» /
  положительная сторона «до обрезки критерий объявлен»).
- **ROADMAP:** п. 17.

### B-2 · P3 · V2: 18 ложных находок — чтения приписаны кадру теста, которого тест не делает

- **Строки:** `test_card_acceptance.py` — `TestAudit` ×10, `TestFrontmatter` ×2, `TestProbeDispatch` ×5,
  `TestWiredIntoTheOfficeStep` ×1; у всех чтения ровно `iter@test, len@test`.
- **Доказательство:** например `TestFrontmatter::test_no_frontmatter_is_empty_not_a_crash` — тело зовёт только
  `ca.parse_frontmatter`, реестр не трогает (`test_card_acceptance.py:34–35`). Совпадающий набор `iter, len` у
  модульной строки `_REGISTERED_PROBES = sorted(ca.PROBES)` (`:189`) — **гипотеза** источника, НЕ измерена.
- **Род:** дефект прибора (кадр приписан неверно), а не тестов; тесты не трогать.
- **Приёмка:** census на SHA с правкой прибора — 0 строк `vacuous_over_members` у `TestFrontmatter` и
  `TestWiredIntoTheOfficeStep`, и прибор называет кадр-источник чтения (тест положительного контроля в
  `test_live_registry_scene_census*.py`: чтение на импорте модуля не приписывается тесту).
- **ROADMAP:** п. 17 (измеримость).

### B-3 · P3 · U1: параметризация по реестру в режиме empty — `[NOTSET]` вместо «исчез»

- **Строки:** 69 × `test_card_acceptance.py::test_every_registered_probe_returns_a_known_verdict[<проба>]`
  (`теста нет в записи прогона с пустым реестром`) + 1 × `[NOTSET]` (только в empty, `skipped`).
- **Доказательство:** pytest при пустом наборе параметров ставит `[NOTSET]` со `skip`; прибор сопоставляет
  по nodeid и не связывает 69 с `[NOTSET]`. Страж полноты (`test_the_parametrized_population_is_the_whole_registry`,
  `len ≥ 60`) в том же прогоне — `breaks_on_substitution`: пустота поймана.
- **Род:** ограничение измерения, не дефект кода.
- **Приёмка:** прибор классифицирует эту группу отдельным исходом (например `collapsed_parametrization`,
  со ссылкой на сработавший страж), `unmeasured` у этих 70 строк = 0; тест прибора на сцене с
  параметризацией по реестру.
- **ROADMAP:** п. 17.

### B-4 · P3 · U2: синтетический член режима grown попадает в `unmeasured`

- **Строка:** `test_every_registered_probe_returns_a_known_verdict[lrs_synthetic_probe_g95_p2]` — только grown.
- **Род:** артефакт прибора (член, добавленный самим прибором, в базовой записи отсутствует по построению).
- **Приёмка:** строка синтетического члена получает свой исход (не `unmeasured`), тест прибора.
- **ROADMAP:** п. 17.

### B-5 · P1 · U3a: basetemp census внутри git-checkout ломает предпосылку двух тестов

- **Строки:** `test_named_cards_closed_at_origin_probe.py::test_no_repository_is_unmeasured`,
  `test_cio_decision_owner_census.py::test_probe_is_green_once_the_line_is_gone`.
- **Доказательство (дифференциально, 23.10):** те же тесты с `--basetemp` вне git-дерева — passed; с
  `--basetemp` внутри `git init`-каталога — failed (`assert 'not_satisfied' == 'unmeasured'`; «`origin/main`
  НЕ УСТАНОВЛЕН: ссылка не разрешается в этом репозитории») — `STAGE8_EVIDENCE.md` §6. Census кладёт
  basetemp в `lrs-work/` внутри checkout (`live_registry_scene_census.py:460` + `--workdir lrs-work`).
- **Род:** две части. (а) конфигурация прибора — basetemp наследует git-предка; (б) тесты неявно
  предполагают, что над `tmp_path` нет репозитория (дверь «GIT-ОКРУЖЕНИЕ», `deployment.md`).
- **Приёмка:** (а) workflow census получает `--workdir "$RUNNER_TEMP/lrs-work"`; census на SHA с правкой —
  эти 2 строки не `unmeasured`; (б) отдельной задачей — сцены тестов объявляют `GIT_CEILING_DIRECTORIES`
  (дифференциальный замер «внутри git» зелен).
- **ROADMAP:** п. 17.

### B-6 · P2 · U3b: пять тестов `green_by_construction_census` красны только в сессии census

- **Строки:** `test_a_linked_stand_never_writes_through_the_link_into_the_source[dir_link|file_link]`,
  `test_a_test_that_VANISHES_under_force_is_named_so_and_not_counted_as_a_kill`,
  `test_child_under_a_G16_PYTHONPATH_imports_the_instrumented_COPY`,
  `test_whole_contour_separates_the_three_outcomes`.
- **Доказательство:** в ci-control 39913698521 — passed; локально и с basetemp внутри git, и снаружи —
  passed (два из них проверены). Причина в сессии census (плагин `lrs_plugin`? `PYTHONPATH`?) **НЕ установлена**.
- **Род:** ограничение измерения до диагноза; дефектом кода НЕ объявлять.
- **Приёмка:** названа причина воспроизведением (тест/стенд, где красный повторяется по требованию), затем
  либо правка прибора, либо карточка на тест; census — эти 5 строк не `unmeasured` или `unmeasured` с причиной.
- **ROADMAP:** п. 17.

### B-7 · P3 · C: два файла читают реестр на импорте

- **Файлы:** `spa_core/tests/test_named_cards_closed_at_origin_probe.py:31` (`PROBE = PROBES["named_cards_closed_at_origin"]`),
  `spa_core/tests/test_owner_view.py:22` (`PROBE = ca.PROBES["director_os_owner_view_section"]`).
- **Род:** ограничение измерения (под пустым реестром — ошибка сборки, громко; потеряна поштучная разметка
  режима empty). Не дефект «тихой зелени».
- **Приёмка:** чтение реестра перенесено в фикстуру/тело; census на SHA с правкой — у файлов нет ошибки
  сборки в режиме empty, у их тестов есть вердикт empty.
- **ROADMAP:** п. 17.

### B-8 · P2 · G16: потерянное покрытие переписи G16 — учитывается явно

| модуль | причина | счёт |
|---|---|---|
| `green_by_construction_census` | `census_budget_refused` (рекурсии нет: 4 зова → 96 дочерних сессий, 643 с) | 1 строка `unmeasured` |
| `heir_all_rows_price` | `census_reentry_refused` (настоящий повторный вход: 717 вложенных проверок, 235 с) | 1 строка `unmeasured` |

- **Доказательство:** журнал W43, «этап 7», пункт G16; `unmeasured_causes` отчёта G16.
- **Приёмка:** обе строки остаются видимыми с причиной в каждом отчёте G16, пока не измерены (проверка:
  `unmeasured_causes` содержит обе причины); измерение — отдельным тактом с бюджетом, не снятием отказа.
- **ROADMAP:** п. 17.

### B-9 · P1 · новый красный полного CI `3c40ed137`: `test_investor_report.py::test_audit_trail_from_temp_db`

- **Источник:** не census, а полный CI 39935715615 (шард 2); против базы `62fe88b48` — единственный новый.
- **Доказательство:** `build_audit_trail` вернул `[]` (`DecisionLogger.get_recent` при исключении пишет в лог и
  возвращает `[]`; захваченного лога в записи CI нет). Этап 8 не трогал ни тест, ни `spa_core/reporting|agents|database`,
  ни conftest. План шардов перестроен (новые тест-файлы): тест переехал из шарда 9 (прогоны 39913698521 и ранее —
  passed) в шард 2 со сменой всех предшественников. На Mac тот же порядок шарда 2 (128 файлов) — passed; пара
  `test_decision_logger` → `test_investor_report` — passed. Кандидат-механизм (по исходнику, НЕ подтверждён):
  `test_decision_logger.py` импортирует `decision_logger` под подменой `database` (`sys.modules.setdefault`), и
  модуль может остаться связанным с поддельным `get_connection`, если настоящий `database` в процессе ещё не загружен.
- **Род:** причина НЕ установлена; дефектом кода этапа не объявлять, тест не трогать молча.
- **Приёмка:** причина названа воспроизведением на Linux (шард 2 того же плана, `-p no:randomly`, с выводом
  исключения `get_recent`); затем правка изоляции виновника (не ослабление теста) и полный CI — тест passed в
  любом шарде.
- **ROADMAP:** п. 17.

### Итог по B-9 и новая B-10 (после разбора ARB, 2026-10-23)

- **B-9 — ПРИЧИНА ДОКАЗАНА, ИСПРАВЛЕНО** (`cce8366ee`), закрыт в CI 40026699075. `test_decision_logger.py`
  оставлял `decision_logger.get_connection` = MagicMock; на Mac не виден из-за проб `conftest` (нет `web3`/`aiohttp`).
- **B-10 — НАЙДЕН И ИСПРАВЛЕН** тем же родом дефекта: путь, связанный на импорте, зависит от того, какой тест
  импортировал модуль первым. `test_live_paths` переведён на чистый подпроцесс с заданным `SPA_DATA_DIR`.
- **Класс «копия артефакта в evidence с именем живого артефакта»** (как `stream.jsonl` этапа 5): мои `exit.json`
  и `run.json` сделали `prior_run_operand_census` «не измеренным»; переименованы в `*.excerpt.json`.
  Правило для evidence: копии артефактов CI/census — только с суффиксом `.excerpt`.

### B-11 · P2 · стенные часы в сборке Mission Control (найдено полным CI 40084749657, 2026-10-24)

- **Тест:** `spa_core/tests/test_mission_rebuild_from_canon.py::test_rebuild_from_canon_gives_byte_identical_mission_json`.
- **Причина (доказана):** `spa_core/research_factory/read.py:223` — при ленте без строк прогона
  `generated_at = … or iso(datetime.now(timezone.utc))`; `mission_control._research_universe_section` зовёт
  `rf_read.latest(data)` без момента вызывающего. Две сборки с ОДНИМИ инъецированными часами расходятся, если между
  ними сменилась секунда. Воспроизведение: пауза 1,1 с между сборками ⇒ failed, без неё ⇒ passed.
- **Род:** нестабильный тест из-за утечки часов в предмет (класс «время — вход», `deployment.md`); не связан с MODELS-01.
- **Приёмка:** `latest()` принимает момент вызывающего (или отказ «нет прогона» без подстановки часов), Mission
  Control передаёт `now`; тест с паузой 1,1 с между сборками — зелен; полный CI — тест passed.
- **ROADMAP:** п. 17. Владелец — агент; приёмка — ARB. Пакетом MODELS-01 инкремент 3 НЕ исправлялось.

### B-11 — ИСПРАВЛЕНО (`b67b8c6b7`, `48c632f70`, 2026-10-24)

Пустая лента без момента; Mission Control передаёт `now`; регрессия с управляемыми часами.

### B-12 · P3 · Telegram-экран Sherlock при пустой ленте (найдено при B-11, НЕ исправлялось)

- После B-11 кокпит при пустой ленте показывает NOT_MEASURED, а `telegram/views/capital._render_sherlock` по-прежнему
  печатает счётчики (документ несёт блок `sherlock` с нулями, `generated_at=None` ⇒ строка свежести «не измерено»).
  Это расхождение «кокпит ↔ бот» на пустой ленте; на ленте с прогоном оба совпадают (`test_mission_telegram_capital_same_truth`).
- **Приёмка:** бот при `generated_at is None` печатает «не измерено», тест «та же правда» на пустой ленте.
- **ROADMAP:** п. 17. Вне границы пакета B-11 (ARB: только `research_factory.read` и передача времени из Mission Control).

## Не вошло в задачи (и почему)

- 760 `breaks_on_substitution` и 53 `claim_independent_of_members` — ожидаемые исходы, находками не являются.
- `not_reached` 1 848 — тесты не читают реестр; прибор о них ничего не утверждает.
