# Поимённый остаток после контрольного прогона №14 (кандидат `b47b637a1`, 2026-10-18)

Прогон: https://github.com/yurii-spa/SPA/actions/runs/39108745934 — население 134 982 · passed 134 205 · **failed 58** ·
error 0 · skipped 719 · не получено 0 · ошибок сбора 0 · частей 12/12. Сравнение №13 → №14: **новых 0**, прежних 58,
исправлено 11 (`ci_control_compare_run13_run14.txt`). Основа — разбор №13 (69 падений, только чтение кода; локально
воспроизведены перепись `adapter_status` и `python_git_ref_provenance`), перепроверенный по списку №14 поимённо.
Атрибуция старых правок — через GitHub (локальный клон прод-дерева неглубокий). «Прежнее» и «чужое» НЕ означает
«безопасное»: влияние названо по каждой группе.

## Счёт по классам (приоритет сверху вниз)

| Класс | Сколько | Группы |
|---|---|---|
| A · собственная регрессия этой сессии | **0** | (в №13 было 5 — исправлено `4cdea501`; шестой кандидат оказался прежним, перенесён в F) |
| B · сохранность данных | **1** | сторож «артефакт ступени лежит под `root/data`» слеп |
| C · права владельца / граница решений | **8** | ремонт фантомов vs гейт ADR-551 (7) · тест ворот публикации заслонён (1) |
| D · реальный дефект продукта/сторожа | **5** | §49 no_regression без производителя (2) · `shell_git_cd_target` (2) · строки INDEX для ADR-777/778 (1) |
| E · таймаут > 180 с | **4** | `run_identity_key_price` (2) · `python_git_ref_provenance` (2) |
| F · устаревший храповик / потолок / ожидание теста | **26** | 19 групп ниже |
| G · только окружение (Linux vs Mac и т. п.) | **11** | 8 групп ниже |
| H · зависит от часов | **3** | 3 группы ниже |
| **Итого** | **58** | |

## Исправлено между №13 и №14 (11)

| Тесты | Чем |
|---|---|
| `test_adapter_status_writer_census` ×2, `test_shadow_tvl_provenance::TestAcceptanceProbe` ×3 | `4cdea501` — собственная регрессия `ef317cbd`: сцена пробы пишет только внутри себя |
| `test_autonomy_mandate::TestWiredIntoTheMandatoryStep` ×2 | `4cdea501` — тест читает только первый блок (изменение теста с обоснованием, инв. #16) |
| `tests/cartographer/test_owner_briefing.py::…never_stores_a_remote_url…` | `b47b637a` — список шарда через `@файл` (дефект моего инструмента ADR-768) |
| `tests/test_dead_code_resolved.py::test_16_unused_imports_decreased` | `923c9ea9` (ADR-778 `ledger_parse_census`), до того `3833b5de` (мой `61a9e04b`) |
| `test_tracker_board_matches_cards` | `b1dce3b4` — доска пересобрана вместе с новыми карточками |
| `test_python_git_ref_provenance::…new_unresolved_identity…` | без правки: у границы 180 с, в этот раз уложился — класс E остаётся |

## Таблица остатка

| Кл. | Тесты (файл × число) | Причина | Влияние на работающую систему | Ответственный | Как проверить исправление | Задача |
|---|---|---|---|---|---|---|
| B | `test_census_stage_root_contract` ×1 | тест выводит имя модуля из имени переменной; `findings_bridge.py:2866` импортирует `acceptance_tree_capability as _atc` ⇒ `ModuleNotFoundError` | класс «перепись пишет артефакт мимо `root/data`» НЕ сторожится с циклов #758/#760; ошибочной записи не наблюдалось | циклы #758/#760 | тест зелёный, и мутация «ступень пишет в корень» его краснит | `inbox-storozh-artefakt-stupeni-lezhit-v-data-k` |
| C | `test_repair_phantom_intake_cards` ×7 | скрипт (цикл, 12.08 `eda520328`) зовёт `set_status("done")` на `owner-decision-*`; гейт ADR-551 (инв. #14) верно отказывает | **риск в работе**: `--apply` до отказа переоткрывает исходники и неатомарно дописывает фантом ⇒ фантом в очереди владельца, трекер рассогласован; прод-монитор называет скрипт лекарством | цикл (скрипт) + ADR-551 (гейт) | 7 тестов зелёные + запуск `--apply` при отказе гейта не меняет ни одного файла (sha до/после) | `inbox-remont-kartochek-fantomov-primenyaetsya` |
| C | `test_publication_truth::BothPushersRunThePublicationGate` ×1 | пушер в сцене останавливается на гейте окна мутаций (ADR-772, `be9dd4ff8`, код 10) раньше ворот публикации | прод-пуш по-прежнему отказывает; тест ворот публичных чисел (предмет №2) ворота не видит | ADR-772 (цикл) | тест зелёный и доказывает, что отказ — от ворот публикации | `inbox-test-vorot-publikatsii-ne-dohodit-do-vor` |
| D | `test_office_declaration_doors` ×1, `test_office_subject_drift_producer_tick` ×1 | ADR-770 (цикл #885, `4633177e3`) объявил `data/no_regression_census.json` с `producer: null`; освежается только руками | критерий §49 «нет регрессий» снова станет НЕ ИЗМЕРЕНО ~через 8 сут после записи 17.10 (предел 192 ч) | цикл #885 | у артефакта есть производитель в расписании; оба теста зелёные | `inbox-artefakt-no-regression-nikto-ne-perepisyv` |
| D | `test_shell_git_cd_target_census::RatchetOnTheRealTree` ×2 | `scripts/pre_commit_check.sh:20` — `$(git rev-parse --show-toplevel)`, прибор такую форму не разрешает ⇒ rc 2 | только сторож; красный и на Маке | не определено | оба теста зелёные без расширения базы | `inbox-hrapovik-shell-git-cd-krasen-na-chistom` |
| D | `test_memory_in_git` ×1 | строки INDEX.md для ADR-777/778 без имени файла (циклы #893 `793b7cc06`, #894 `8109b6693`) | читатель реестра по ссылке решения не находит | циклы #893/#894 | тест зелёный | `inbox-reestr-reshenii-stroki-adr-777-i-adr-778` (новая) |
| E | `test_run_identity_key_price::BatteryHoleTests` ×2 | полный обход 174 читателей × 3 стенда + `git`-подпроцессы `asset_registry_gap_price`; ~180,5 с в CI | только время CI; прибор советательный | прибор G16 (циклы) | оба теста < 180 с в CI без поднятия лимита | `inbox-taimauty-v-ci-perepis-g16-i-instrument-g` (новая) |
| E | `test_python_git_ref_provenance::RegistryReactsToTheCensus` ×2 | инструмент 101 с на Маке ⇒ ~230 с в CI (`find_readers`/`ast.walk`); третий тест группы то укладывается, то нет | только время CI | цикл (инструмент) | все тесты группы < 180 с в CI | `inbox-taimauty-v-ci-perepis-g16-i-instrument-g` (новая) |
| F | `test_python_git_ref_provenance` ×2 (`test_real_tree_matches_the_frozen_baseline`, `test_an_intact_baseline_passes`) | предмет вырос на 25 против `scripts/python_git_ref_provenance_baseline.json` (устарела с 04.10; происхождение по пунктам не определено) | сторож git-ссылок слепнет на новые случаи | не определено | база сверена поимённо (не дописана ради зелёного) | `inbox-predpisannyi-progon-krasnyi-na-chistom-m` |
| F | `test_tail_value_divergence` ×3, `test_invisible_consumer_scale::WiringTest` ×1 | три привязки `_REACH_OUTCOMES` в переписи (одна в строковом литерале); тест сравнивает с не тем словарём; поиск подстроки `reach_outcome` ловит законный ключ `reach_outcomes`; проводка шага ищется формой AST, которой больше нет | только тест; красны с №6 и раньше (до переименования `65a3ef25e`) | не определено (до сессии) | 4 теста зелёные, без сужения проверок | `inbox-ostatok-f-ustarevshie-hrapoviki-i-ozhida` (новая) |
| F | `test_document_field_reader` ×4 | соседняя совокупность зашита литералом `_neighbour(16, 10)`=26, живой обход находит 41 | только тест | `da36104cf` (не сессия) | 4 теста зелёные | то же |
| F | `test_unwired_guard_modules_ratchet` ×2, `test_unwired_scripts_ratchet` ×1, `test_unwired_registry_evidence` ×1, `test_edge_boundary_dataflow_census` ×1 | сторожа без читателя (`ledger_parse_census` ADR-778, `step_time_drift`), 4 записи `KNOWN_UNWIRED` уже подключены; 3 новых сироты; вычет «ручной R&D» 69/135 (> 50 %); население edge 39 ≠ 35 | эрозия сторожей: написанное не исполняется | циклы (ADR-778 и др.), Novel-Edge | тесты зелёные подключением/объявлением, без роста вычета | то же |
| F | `test_postgres_migration` ×1, `tests/test_spaerror_complete.py` ×1, `tests/test_no_utcnow.py` ×1 | 10 сырых `sqlite3.connect`; 15 голых `RuntimeError` (11 в `card_acceptance.py`, циклы #861–#863); `utcnow()` в docstring | только храповики | циклы | тесты зелёные | то же |
| F | `test_fixture_schema_gap_ratchet` ×1, `test_state_journal_coverage_audit` ×1, `test_decision_journal_coverage` ×1, `test_subject_population_census` ×1, `test_office_absent_block_producer_aware` ×2, `test_site_snapshot_view_shape` ×1, `scripts/tests/test_fill_agent_passports.py` ×1 | 123 ≠ 121 сайтов двери; строка STATE 08.10 без покрытия журнала; `keep_dominance_census` не в совокупности читателей; новая форма в `test_mission_ui_design_v3.py`; список исключений офиса разошёлся; 61 поле снимка сайта без вида (Wave 2 `0dc759eb2`); `architecture/manifest.json` с отступом 2 вместо 1 (`87abe591c`) | тесты/документы; поля снимка сайта никто не читает через вид | циклы; `2df987cec` (выпуск Director OS) — проверить | тесты зелёные | то же |
| G | `scripts/tests/test_check_concurrent_pytest.py` ×3, `test_shell_git_cd_repo_identity` ×2, `test_recover_trusted_runtime` ×1, `test_announce_clock_door_census` ×1, `test_edge_downside_parity` ×1, `test_truncated_input_census` ×1 | lsof на Linux; зашитые пути Мака; нет `dscl`/`launchctl`; `strftime %Q` glibc vs macOS; `stdev` Python 3.11 vs 3.13; длина TMPDIR | нет (CI-хост отличается от прода) | окружение | тесты объявляют своё окружение и зелёные на ubuntu | `inbox-ostatok-g-testy-zavisyat-ot-hosta-ci-11` (новая) |
| G | `test_act_day_recovery::…keeps_its_cents` ×1 | порядок обхода `set(frm)\|set(to)` решает округление (1 цент) | советательная цифра может разойтись на цент между хостами — хрупкость кода | не определено | порядок детерминирован; тест зелёный на обоих хостах | то же |
| G | `test_research_evidence_tracks` ×1 | `SEED_PATH` указывает в скретчпад ДРУГОЙ сессии Claude (`cc0d3914b`, ADR-564, 05.10) | сломается на любом хосте после чистки `/tmp` | `cc0d3914b` | затравка в репозитории/фикстуре | то же |
| H | `test_slo_keepability` ×1, `test_timeseries_lane_modules[apy_tracker]` ×1, `test_no_import_time_clock_in_tests` ×1 | `main()` без `now` (бомба календаря); `apy_tracker.get_trend` — стенные часы; часы на импорте в 3 тест-файлах | тесты; `apy_tracker` — советательный | циклы | время — вход; тесты зелёные при любой дате | `inbox-ostatok-h-testy-zavisyat-ot-segodnyashne` (новая) |
