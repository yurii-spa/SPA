# CI control run #6: разбор 123 непрошедших тестов

**Прогон:** 39035352936 · SHA `ec9071d6f` · Python 3.11.17 / pytest 9.1.1 / ubuntu-24 · `SPA_ENV=ci PYTHONHASHSEED=0`.
**Итог:** 134 006 passed · 719 skipped · **101 failed + 22 error = 123** · 12/12 шардов завершены, вердикт RED, `not_obtained=0` (вердикт полный).
**Код для чтения:** worktree `/tmp/spa_wt_fail` (origin/main `96a355a0c`, потомок `ec9071d6f`). Дата разбора: 2026-10-17.
**Локальная проверка (macOS, Python 3.13.11, `run_tests.sh`):** прогнаны 22 быстрых файла. Тяжёлые census-тесты и файлы >180 с не запускались.

Классы: **(a)** реальный дефект кода или фикстуры · **(b)** тест зависит от хоста/живого дерева (macOS-утилиты, пути, часы, версия Python) и на CI-раннере держаться не может · **(c)** дрейф храповика/базы (предмет перерос записанный потолок) · **(d)** производительность (>180 с на тест) · **(e)** нестабилен или зависит от порядка · **(f)** неизвестно.

> Оговорка о `git log`: почти все файлы попали на `main` массовым повторным добавлением `da36104cf` (2026-10-04). Если вводящий коммит назван `da36104cf`, это значит «есть на main с 04.10». Настоящая точка введения в истории `main` не видна.

## 1. Группы первопричин

| Гр. | Название | Кол-во | Пример nodeid | Причина и доказательство | Класс | macOS |
|---|---|---|---|---|---|---|
| G01 | measure()/перепись всего корпуса внутри теста | 29 | `test_table_form_census.py::Wiring::*` (9 error в setUpClass), `test_rule_second_copy_census.py::LiveControlOnTheRealTree::*` | **ДОКАЗАНО.** `Failed: Timeout (>180.0s)`. Три «pytest internal error (exit 3)» (`test_list_identity_census` ×2, `test_run_identity_key_price::…lowered_again…`) — те же таймауты: от start до crash в `stream.jsonl` прошло 182,5 с, 181,5 с и 183,6 с. Время на файл (`file_wall_s`): ledger_day_unit 840 с, list_identity 640 с, run_identity_key_price 450 с, autonomy_mandate 360 с, rule_second_copy_census_wiring 361 с, finding_address_price 339 с. Модуль `rule_second_copy_census.py` — 25 741 строка | d | не запускались |
| G02 | Пограничный таймаут `run_identity_key_price::…excludes_itself…` | 1 | `test_run_identity_key_price.py::BatteryHoleTests::test_the_instrument_excludes_itself_by_naming_the_reason` | **ДОКАЗАНО.** Таймаут на `g16.measure()` → `classify_reader` (`run_identity_key_price.py:2004`). Красный в #3 и #6, зелёный в #5: тест проходит рядом с порогом 180 с | e (по сути d) | — |
| G03 | BSD-флаг `ps -E` на Linux | 19 | `test_safe_terminate_ownership.py::*` (13), `test_claude_run_timeout_ownership.py::*` (6) | **ДОКАЗАНО.** На раннере `ps вернул 1: error: unsupported SysV option`. Источник — `scripts/claude_run_with_timeout.py:160` `_ps(["-A","-Ewww",…])`: `-E` (окружение) есть только в BSD-`ps`, в procps такого флага нет. `scripts/shadow/safe_terminate.py` строит перепись через ту же дверь `CRT._ps`. Прибор честно отдаёт третий исход: 125, `OWNERSHIP_UNKNOWN`, `REFUSED`. `KeyError: 'identity'` возникает потому, что при UNKNOWN ключа `identity` нет | b | safe_terminate **зелёный** → только CI |
| G04 | Разбор `lsof -F` на Linux | 3 | `scripts/tests/test_check_concurrent_pytest.py::TestOpenFilesParsesRealLsof::*` | `lsof` на раннере есть: setUp его проверяет и не падает. Разбор `scripts/check_concurrent_pytest.py:219` (`lsof -a -p PID -d 0-255 -Ftnia`) на Linux не видит обычных файлов: «только ?». **ГИПОТЕЗА:** у Linux-lsof другой набор или порядок полей `-F` (тип/режим) | b | **зелёный** → только CI |
| G05a | `strftime("%Q")` | 1 | `test_announce_clock_door_census.py::TestSynthForm::test_an_unknown_directive_yields…` | **ДОКАЗАНО.** glibc возвращает `'%Q'`, macOS — `'Q'`. Докстрока теста прямо говорит «Замер на этой машине» (`29e6d3fc7`, 10.10) | b | **зелёный** |
| G05b | `statistics.stdev` константного ряда | 1 | `test_edge_downside_parity.py::test_downside_denominator_is_exactly_zero…` | **ДОКАЗАНО.** На 3.11 `stdev([0.0002]*10) = 2.857e-20`, а не 0; на 3.13 получается ровно 0. Тест закрепил свойство конкретной версии Python | b | **зелёный** (3.13) |
| G05c | `recover_trusted_runtime.sh` — macOS-утилиты | 1 | `test_recover_trusted_runtime.py::TestDryRunZeroMutation::…` | rc 127 (команда не найдена). В скрипте `dscl` (стр. 103) и `launchctl print` (стр. 112, 118), их нет на Linux. **ГИПОТЕЗА**, какая именно из команд вернула 127 | b | **зелёный** |
| G05d | Длина путей сцены зависит от TMPDIR | 1 | `test_truncated_input_census.py::TheJanitorSeesEveryWorktree::…` | **ДОКАЗАНО механизмом.** Сцена (`test_truncated_input_census.py:722-745`) рассчитывает, что `git worktree list` перерастёт 2000 символов за счёт префикса TMPDIR. Префикс macOS `/var/folders/…/T/` длинный, Linux `/tmp` — 4 символа. Итог 1955 < 2000 | b | не запускался |
| G05e | Приколоченные цели `cd` отсутствуют на хосте | 2 | `test_shell_git_cd_repo_identity.py::GuardOnTheGuard::*` | **ДОКАЗАНО.** «НЕ ИЗМЕРЕНО: 23 приколоченных целей нет на этом хосте (`scripts/agent_novel_edge_rnd.sh:55`, `git_autopush.sh:110`…)» → rc 2 вместо 3 / 0. Цели — пути прод-Мака | b | не запускался |
| G05f | Путь в scratch ЧУЖОЙ сессии Claude | 1 | `test_research_evidence_tracks.py::test_facts_jsonl_no_fact_lacks_a_citation…` | **ДОКАЗАНО.** `SEED_PATH = /private/tmp/claude-501/…/77953ab2-…/scratchpad/ev/phase0_citations.md` (стр. 32), введён `cc0d3914b` (05.10, ADR-564). Упадёт везде, как только /tmp очистят | b | не запускался |
| G06 | Календарные бомбы (стенные часы) | 2 | `test_timeseries_lane_modules.py::test_falling_apy_riskier_than_rising[apy_tracker]`, `test_slo_keepability.py::ExitCodesSeparateThreeOutcomes::test_everything_keepable_exits_zero` | **ДОКАЗАНО.** (1) `apy_tracker.get_trend` берёт `datetime.now()` (`apy_tracker.py:83`, окно 90 дн.), последняя точка фикстуры — 2026-07-10, значит красный с ≈08.10. (2) `slo_keepability.main()` не принимает `now`: инъекция есть у `measure()`, но не у CLI. Якорь теста — 2026-10-03, окно 7 дн. → красный с ≈10.10 | b (часы) / a (полуинъекция) | **красный везде** |
| G07 | Затенение глобального `_REACH_OUTCOMES` в `rule_second_copy_census.py` | 14 | `test_tail_value_divergence.py::AggregateTest::*` (KeyError `verdict`/`blind`/`kinds_differ`…), `WholeContourTest::*`, `ReportTest::*` | **ДОКАЗАНО.** Имя определено дважды на уровне модуля: стр. 8417 `(REACH_LIVE, REACH_ISOLATED, …)` и стр. 14111 `(REACH_REACHABLE, REACH_UNREACHABLE, REACH_UNRESOLVED)`. Функция на стр. 8780 (`if reach not in _REACH_OUTCOMES`) видит ПОСЛЕДНЕЕ определение, поэтому объявленный класс `isolated_from_the_live_document_by_the_harness` получает отказ «класс вне объявленных» → `UNMEASURED`, ключей агрегата нет. Оба определения есть с `da36104cf` (04.10). Карточка `inbox-21-test-…` подтверждает: красный на чистом origin | a | **красный везде** |
| G08 | AST-тест ждёт `return {…}` у `measure()` | 2 | `test_invisible_consumer_scale.py::WiringTest::…` (StopIteration), `test_tail_value_divergence.py::WiringTest::test_measure_binds_the_step…` | **ДОКАЗАНО.** Тесты ищут в `measure()` `Return` со значением `ast.Dict`. С `68e9c68fe` (05.10, G99.2) `measure()` собирает `doc` и делает `return doc` (проверено AST по истории: при `da36104cf` было True, при `68e9c68fe` стало False) | a (тест судит структуру) | **красный везде** |
| G09 | Подстрока `reach_outcome` внутри ключа `reach_outcomes` | 1 | `test_tail_value_divergence.py::AbsentReachIsNotAnOutcome::test_the_second_name_for_reach_is_gone_from_the_code` | **ДОКАЗАНО.** `assertNotIn("reach_outcome", code)` (стр. 818) срабатывает на законный ключ `"reach_outcomes"` (стр. 14474, 25012). Ложноположительный текстовый поиск. **Это не git-history/shallow, как помечал грубый кластер** | a | **красный везде** |
| G10 | Живое население прибито литералом `_neighbour(16, 10)` | 4 | `test_document_field_reader.py::test_live_measurement_*` | **ДОКАЗАНО.** Тест сверяет живой обход дерева (сейчас 41 счётчик) с захардкоженным соседом 16+10=26 (стр. 499, 508, 536, 542, 549). Прибор честно отвечает `UNMEASURED_DOC_POPULATION`. Остальные три теста — следствие (KeyError, None в отчёте). Литерал с `da36104cf` | c (тест читает живое дерево) | не запускался (149 с) |
| G11 | `repair_phantom_intake_cards` против гейта ADR-551 | 7 | `test_repair_phantom_intake_cards.py::*` | **ДОКАЗАНО.** `scripts/repair_phantom_intake_cards.py:140` зовёт `set_status(phantom, "done")` для карточки `owner-decision-*`. `owner_queue.queue` отказывает: `LifecycleRefused — an owner decision is closed only on the owner's recorded answer (inv. #14, ADR-551)`. Скрипт отстал от гейта очереди | a | **красный везде** |
| G12 | Храповики качества кода, красные на main | 3 | `tests/test_no_utcnow.py`, `tests/test_spaerror_complete.py::test_20…`, `test_postgres_migration.py::…zero_raw_connects` | **ДОКАЗАНО.** (1) Докстрока `spa_core/monitoring/identity_field_kind.py:75` упоминает ``datetime.utcnow()``, а сторож ищет текстом (с `da36104cf`). (2) 15 голых `RuntimeError`: 11 в `card_acceptance.py:6334–6946` (циклы #861–#863, `225e93411`/`c37b2bd38`/`93ec0cb20`, 13–14.10), плюс `record_survival_census.py:316` (`c5ab6dc32`, 09.10), `failure_matrix.py:349` (`ad283847b`, 04.10), `release_activation.py:67,70`. (3) 10 сырых `sqlite3.connect`: `trading_research/*` (`9b09e7d0b` 07.10, `688f2c4b9` 06.10), `dr/full_archive_verify.py` (`53c5a59e7` 07.10), `studio_os/*` | c (a по сути: новый код нарушает действующее правило) | не запускались |
| G13a | adapter_status writer census: `caller_supplied` 27 > потолка 26 | 5 | `test_adapter_status_writer_census.py::*` ×2, `test_shadow_tvl_provenance.py::TestAcceptanceProbe::*` ×3 | **ДОКАЗАНО** по выводу: «НЕ ИЗМЕРЕНО (цель приходит от вызывающего) 27 > потолок 26». Проба `shadow_tvl` использует ту же перепись. Какая площадка новая — **ГИПОТЕЗА** (не выделена) | c | не запускались (106/246 с) |
| G13b | python_git_ref_provenance: предмет вырос на 25 | 4 | `test_python_git_ref_provenance.py::TestRatchet::test_real_tree_matches_the_frozen_baseline` | **ДОКАЗАНО.** «ХРАПОВИК: предмет ВЫРОС на 25 — `check_change_evidence.py::run::show:origin/main`, `cio_acceptance_rollup.py::…`, `memory_backup.py::bundle_repo…`». Остальные три теста (rc 3) — то же живое дерево. Файл идёт 2017 с | c | не запускался |
| G13c | fixture_schema_gap: площадок двери 123 против 121 | 1 | `test_fixture_schema_gap_ratchet.py::test_the_door_sites_still_add_up…` | ДОКАЗАНО по выводу; какие 2 площадки — не выделено | c | — |
| G13d | edge_boundary_dataflow: население 39 против 35 | 1 | `test_edge_boundary_dataflow_census.py::…population_100_published` | `assertEqual(census["population"], 35)` (стр. 253) на живом дереве. Новые `scripts/edge_*` (например `fb0fc00e3`, novel-edge #138, 16.10) | c | — |
| G13e | decision_journal_coverage: читатель `keep_dominance_census` | 1 | `test_decision_journal_coverage.py::ReaderPopulationRatchet::…` | ДОКАЗАНО по выводу. Карточка называет причину: `keep_dominance_census` читает журнал | c | — |
| G13f | subject_population: точная дорога шире полнотной | 1 | `test_subject_population_census.py::…subset_of_the_recall_road` | `spa_core/tests/test_mission_ui_design_v3.py:21`, введён `2df987cec` (Director OS release, 15.10) | c | — |
| G13g | unwired_guard_modules | 2 | `test_unwired_guard_modules_ratchet.py::*` | Новый неподключённый `spa_core/monitoring/step_time_drift.py`. Плюс 4 модуля из `KNOWN_UNWIRED` подключены, но не вычеркнуты (`adaptive_monitor`, `cpa_governance_watcher`, `data_freshness_monitor`, `unified_gas_monitor`) | c | — |
| G13h | unwired_registry_evidence: вычет 69 из 135 | 1 | `test_unwired_registry_evidence.py::…carve_out_did_not_swallow_the_watch` | Вычет «ручной R&D» перевалил половину. Растёт с каждым edge-скриптом | c | — |
| G13i | unwired_scripts: 3 новых сироты | 1 | `test_unwired_scripts_ratchet.py::TestRatchet::test_no_NEW_unwired_script_appears` | `edge_rkaw_running_calmar_weighting` (`fb0fc00e3`, 16.10), `refresh_no_regression_census` (`4633177e3`, 17.10), `worker_axis_census` (`b726e7b86`, 14.10) | c | — |
| G13j | state_journal_coverage: в живом STATE.md 3 MISSING | 1 | `test_state_journal_coverage_audit.py::test_live_state_no_longer_carries_uncovered_chronicle` | Тест читает живой `docs/STATE.md` (строка 77 «Последние решения», 08.10, ADR-642…646) | c (живой документ) | — |
| G13k | office_absent_block: новая площадка `_summarize_json` | 2 | `test_office_absent_block_producer_aware.py::CensusRatchet::*` | `scripts/consume_office_reports.py`: печать «латентность : в отчёте нет —» (стр. ≈4832) — лишняя освобождённая площадка, разошлась с allowlist | c | — |
| G13l | site_snapshot_view_shape: 61 поле снимка без переходника | 1 | `test_site_snapshot_view_shape.py::…covered_or_declared` | **ДОКАЗАНО.** Поля `book_exposure`, `anchor_equity`, … появились в `landing/src/data/track_snapshot.json` коммитом `0dc759eb2` (Wave 2 release, 15.10). В `3b417db92` (15.10 08:01) их ещё нет. Переходник и `NOT_IN_VIEW` не обновлены | c | не запускался |
| G14 | shell_git_cd_target: «не измерено» на `$(git rev-parse …)` | 2 | `scripts/tests/test_shell_git_cd_target_census.py::RatchetOnTheRealTree::*` | **ДОКАЗАНО.** `scripts/pre_commit_check.sh:18-19` (`REPO_DIR="$(git rev-parse --show-toplevel)"; cd "$REPO_DIR"`): подстановка вне белого списка → прибор отдаёт rc 2 («не измерено»), тест ждёт 0/3 | a (тест не принимает третий исход) | **красный везде** |
| G15a | Артефакт `data/no_regression_census.json` без производителя в конституции | 2 | `test_office_declaration_doors.py::…`, `test_office_subject_drift_producer_tick.py::…` | **ДОКАЗАНО.** «у data/no_regression_census.json в конституции не объявлен производитель». Артефакт и его скрипт введены `4633177e3` (ADR-770, 17.10 03:35) | a | — |
| G15b | Джоба CI-Lite без `fetch-depth` | 1 | `test_declared_git_environment.py::…declares_full_history` | **ДОКАЗАНО.** `ci-lite.yml:syntax-and-import` с `7228b19de` (06.10) ставит pytest (`pip install pytest`). Детектор, намеренно грубый, считает джобу pytest-джобой, а `fetch-depth` не объявлена. **Не git-history/shallow сам по себе** | a (декларация окружения) | — |
| G15c | Приёмник-псевдоним `_atc` в findings_bridge | 1 | `test_census_stage_root_contract.py::…under_root_data` | **ДОКАЗАНО.** `_CALL_INDEPENDENT = r"\b(\w+)\.run\(root=args\.root\)"` выводит имя модуля из приёмника. `findings_bridge.py:2866` — `import acceptance_tree_capability as _atc` → `import spa_core.monitoring._atc` → ModuleNotFoundError. Комментарий на стр. 2919 сам называет это «предсуществующий красный с #758/#760» | a | **красный везде** |
| G16 | Округление полуцента зависит от порядка обхода `set` | 1 | `test_act_day_recovery.py::…fractional_turnover_keeps_its_cents` | **ДОКАЗАНО.** `_move_deltas` перебирает `set(frm) \| set(to)` (`act_day_recovery.py:196`), затем `sum(abs(v))/2` (стр. 367) и `round(…, 2)` (стр. 397). В одном порядке сумма даёт 20000.004999… → 20000.0, в другом 20000.005 → 20000.01 (проверено в REPL). Порядок `set` разный на 3.11 и 3.13 | a (недетерминизм) | **зелёный** → только CI |
| G17 | `architecture/manifest.json` записан не каноническим сериализатором | 1 | `scripts/tests/test_fill_agent_passports.py::…byte_identical…` | **ДОКАЗАНО.** Отступ 2 вместо канонического 1 впервые появился в `87abe591c` (ADR-643, 08.10). Все 19 последующих коммитов манифеста сохраняют отступ 2 | a | **красный везде** |
| G18 | Новый гейт «окно мутаций» срабатывает раньше гейта публикации | 1 | `test_publication_truth.py::BothPushersRunThePublicationGate::…` | Пушер возвращает rc **10** (отказ `--allow-open-mutation-window`, `push_to_github.py:3095-3111`), а тест ждёт 3. Гейт введён `be9dd4ff8` (ADR-772, 17.10 10:22). **ГИПОТЕЗА:** в стенде теста нет `scripts/delta_mutation_run.py`, вердикт окна «не измерено» → отказ | a (фикстура отстала) | не запускался |
| G19 | `test_no_import_time_clock_in_tests` на `test_cockpit_dispatch.py` | 1 | `spa_core/tests/test_no_import_time_clock_in_tests.py::…` | Исключено из предложений: чинит вызывающая сессия | (a) | — |

**Сводка по классам:** a — 34 (G07 14, G11 7, G08 2, G14 2, G15 4, G09, G16, G17, G18, G19) · b — 31 (G03 19, G04 3, G05 7, G06 2) · c — 28 (G13 21, G10 4, G12 3) · d — 29 (G01) · e — 1 (G02) · f — 0. Всего 123.

**Везде или только CI** (по локальным прогонам): только CI — G03 (safe_terminate), G04, G05a, G05b, G05c, G16. Красные и на macOS — G06, G07, G08, G09, G11, G14, G15c, G17. Остальные локально не запускались.

## 2. Карточки трекера

| Группа | Карточка (статус) |
|---|---|
| G01/G02 | `inbox-ci-py3-11-test-zovet-measure-tselikom-31` (new) · `inbox-ci-na-main-krasnyi-12-progonov-podryad-m` (in-progress) · `agent-perepis-ne-pomeschaetsya-v-storozha-zavisanii` (backlog) · `inbox-proverka-mandata-avtonomii-padaet-po-180` (new, autonomy_mandate) |
| G03 | `inbox-na-linux-prinadlezhnost-protsessa-vsegda` (new) — «19 красных тестов», совпадает точно |
| G04 | `inbox-ci-na-main-verdikt-vpervye-izmeren-tests` (in-progress, lsof) |
| G05a/b/c/d/e/f | G05b, G05e (`test_shell_git_cd_repo_identity`), G05d — в общем `inbox-devyat-krasnyh-v-ci-s-raznymi-prichinami` (new). **Нет карточки:** G05a (strftime), G05c (recover_trusted_runtime), G05f (чужой scratch) |
| G06 | timeseries — `inbox-origin-main-krasen-esche-vosemyu-testami` (new). slo — `inbox-dva-testa-padayut-na-chistoi-glavnoi-vet` (new) |
| G07/G08/G09/G10 | `inbox-21-test-treh-batarei-ryada-krasneet-na-c` (new): tail_value, document_field_reader, invisible_consumer. Затенение `_REACH_OUTCOMES` как причина там, вероятно, не названо |
| G11 | `inbox-origin-main-krasen-esche-vosemyu-testami` (new) |
| G12 | utcnow — `inbox-storozh-zapreta-utcnow-sudit-tekstom-on` (new). Bare exceptions — `inbox-ci-krasnyi-iz-za-dvuh-strok-runtimeerror` (new; там 2 строки, сейчас 15). **sqlite3 — карточки нет** |
| G13 | b, h, e — `inbox-origin-main-krasen-esche-vosemyu-testami` · d, j — `inbox-predpisannyi-progon-krasnyi-na-chistom-m` (new) · d, k — `inbox-devyat-krasnyh-…` · e — `inbox-hrapovik-naseleniya-chitatelei-zhurnala` (new) · f — `inbox-dva-krasnyh-na-main-naselenie-perepisei-razoshlos` (new) · g — `inbox-dva-pribora-napisany-i-ne-pozvany-hrapov` (new), `inbox-dva-storozha-nikto-ne-zovet-a-vychet-sto` (new) · h, i — `inbox-krasnyi-na-chistom-main-vychet-ruchnoi-r` (new), `inbox-storozh-r-d-isklyucheniya-upersya-v-poro` (new). **Без карточки:** a (adapter_status `caller_supplied`), c (fixture_schema), l (site_snapshot_view) |
| G14 | `inbox-hrapovik-shell-git-cd-krasen-na-chistom` (new) |
| G15 | a — `inbox-artefakt-no-regression-nikto-ne-perepisyv` (new, рядом по предмету; производитель в конституции там не назван). b — `inbox-ci-lite-gonyaet-pytest-bez-istorii-repoz` (new), `inbox-chetyre-testa-krasneyut-na-chistom-origi` (new). c — `inbox-storozh-artefakt-stupeni-lezhit-v-data-k` (new) |
| G16 | `inbox-devyat-krasnyh-…` (new) упоминает файл. Причина (порядок `set`) не названа |
| G17, G18 | **Карточек нет** (`agent-pasporta-zapolneny-chastichno-…` о другом; `inbox-shag-0a-…` о шаге 0a, не о тесте) |

## 3. Минимальный следующий шаг и сколько он снимет

Ни один шаг не поднимает таймаут и не дописывает базу (инв. #16). Где нужна правка самого теста, она идёт с обоснованием и записью в журнал.

| Группа | Шаг (не выполнен) | Снимет |
|---|---|---|
| G01 | Не пересчитывать перепись корпуса в каждом тесте. (1) Один замер на сессию (session-fixture или кэш артефакта по sha дерева); (2) живой контроль «на настоящем дереве» вынести в отдельную объявленную тяжёлую джобу без лимита 180 с на тест. Заодно профилировать `rule_second_copy_census.measure` (25 741 строка, вероятно повторные `ast.parse` всего дерева) | до 29 (+1 G02) |
| G02 | Само уйдёт с G01 (тот же `measure`); иначе — пометить и разобрать как пограничную производительность | 1 |
| G03 | Сделать дверь `_ps` переносимой: на Linux окружение брать из `/proc/<pid>/environ` (или `ps e`), отпечаток команды — из `/proc/<pid>/cmdline`. Тестам, чей предмет — живой `ps` macOS, объявить хостовое требование явно (третий исход с причиной, а не скип) | 19 |
| G04 | Снять реальный вывод `lsof -Ftnia` на ubuntu-24 (одна строка в CI-логе) и поправить разбор под Linux-форму | 3 |
| G05a/b | Тест закрепляет поведение платформы: утверждать «строка, которую дверь отвергает», а не точное значение `'Q'`; для stdev — сравнивать с допуском или проверять свойство «константный ряд → нулевой знаменатель» через свою функцию прибора, а не через `statistics.stdev` | 2 |
| G05c | Объявить тест macOS-only через декларацию окружения (третий исход), либо инъектировать `dscl`/`launchctl` | 1 |
| G05d | Длину сцены строить из собственного префикса (длинный подкаталог), а не из TMPDIR | 1 |
| G05e | Цели `cd` в тесте — фикстура в tmp, а не пути прод-Мака; или явная декларация хоста | 2 |
| G05f | Перенести seed-файл в репозиторий (`research/…`) или в фикстуру | 1 |
| G06 | Пробросить `now` до проводки: `get_trend(now=)` в `apy_tracker.analyze` и `--now` у `slo_keepability.main`, тест передаёт якорь | 2 |
| G07 | Переименовать второе `_REACH_OUTCOMES` (стр. 14111) в уникальное имя. Плюс храповик «ни одно имя не определяется на уровне модуля дважды» для этого файла | 14 |
| G08 | Привести тесты к форме «ключ попадает в возвращаемый документ» (искать присваивание `doc[...]`/литерал `doc = {...}` или проверять поведением), с записью в журнал | 2 |
| G09 | Сравнивать по границе слова или токену AST, а не подстрокой. Это исправление ложного срабатывания, с обоснованием и записью в журнал | 1 |
| G10 | Брать население соседа из настоящего соседского прибора на том же дереве (как требует сам прибор), а не из литерала 16/10 | 4 |
| G11 | Привести `repair_phantom_intake_cards` к ADR-551: фантомную owner-decision не закрывать через `done`, а провести допустимым переходом (или фикстуры на inbox-карточках, если owner-фантомы больше не рождаются) | 7 |
| G12 | Исправить код: переписать докстроку без литерала `datetime.utcnow()`; 15 `RuntimeError` → подклассы `SPAError`; 10 `sqlite3.connect` → общий db-хелпер | 3 |
| G13 | По одному на строку: назвать новую площадку и либо исправить её (a, c, k), либо подключить сироту (g, i: `step_time_drift`, 3 скрипта), либо вычеркнуть подключённых из `KNOWN_UNWIRED` (g — сужение, разрешено). Пересчитать опубликованное население честным замером с ADR (d, f), закрыть 3 MISSING в STATE.md (j), добавить 61 поле в переходник или объявить в `NOT_IN_VIEW` с причиной (l). Для h — пересмотр самого вычета (карточка уже есть) | до 21 |
| G14 | Тест обязан принимать третий исход как отдельный: либо добавить `git rev-parse --show-toplevel` в белый список прибора, либо сделать цель статически разрешимой | 2 |
| G15 | a: объявить производителя `no_regression_census.json` в конституции (`refresh_no_regression_census`). b: `fetch-depth: 0` в `ci-lite.yml:syntax-and-import`. c: назвать приёмник по модулю (`acceptance_tree_capability.run(...)`), как уже сделано рядом | 4 |
| G16 | Детерминировать порядок: `sorted(set(frm) \| set(to))` и/или считать оборот в центах (int) | 1 |
| G17 | Перезаписать манифест каноническим `dumps` и найти писателя, который с `87abe591c` пишет отступом 2 | 1 |
| G18 | Положить в стенд теста читателя окна (или проверять оба гейта по порядку) | 1 |
| G19 | — (у вызывающего) | 1 |

**Решения владельца:** по существу не нужны, все группы технические. Единственная пограничная — G11: скрипт закрывает карточки `owner-decision-*`, а это область инв. #14. Если фантомы, рождённые сломанным классификатором, нельзя закрывать агенту даже как «не-ответ владельца», то это вопрос предмета, а не кода. Остальное, включая G13l (переходник `landing/`, числа не меняются), решает агент.

## 4. Полный список nodeid → группа

| # | nodeid | исход | группа |
|---|---|---|---|
| 1 | `tests/test_no_utcnow.py::test_no_bare_utcnow_in_runtime` | failed | G12 |
| 2 | `tests/test_spaerror_complete.py::test_20_zero_bare_exceptions_in_spa_core` | failed | G12 |
| 3 | `spa_core/tests/test_act_day_recovery.py::TestTheHonestBatteryHoles::test_fractional_turnover_keeps_its_cents` | failed | G16 |
| 4 | `spa_core/tests/test_adapter_status_writer_census.py::TestCensusRegressions::test_live_tree_is_green_at_its_declared_ceilings` | failed | G13a |
| 5 | `spa_core/tests/test_adapter_status_writer_census.py::TestProbe::test_green_on_the_whole_contour` | failed | G13a |
| 6 | `spa_core/tests/test_announce_clock_door_census.py::TestSynthForm::test_an_unknown_directive_yields_a_string_and_the_DOOR_refuses_it` | failed | G05a |
| 7 | `spa_core/tests/test_autonomy_mandate.py::TestWiredIntoTheMandatoryStep::test_mandate_line_survives_an_unmeasurable_office` | failed | G01 |
| 8 | `spa_core/tests/test_autonomy_mandate.py::TestWiredIntoTheMandatoryStep::test_office_step_prints_the_mandate_judgement` | failed | G01 |
| 9 | `spa_core/tests/test_census_stage_root_contract.py::CensusStageRootContract::test_every_stage_census_puts_its_artifact_under_root_data` | failed | G15c |
| 10 | `spa_core/tests/test_claude_run_timeout_ownership.py::OwnershipAtTimeout::test_10_normal_exit_does_not_kill_the_detached_child` | failed | G03 |
| 11 | `spa_core/tests/test_claude_run_timeout_ownership.py::OwnershipAtTimeout::test_2_3_4_6_timeout_kills_only_what_is_proven_ours` | failed | G03 |
| 12 | `spa_core/tests/test_claude_run_timeout_ownership.py::OwnershipAtTimeout::test_7_unresolved_ownership_returns_125_and_names_survivors` | failed | G03 |
| 13 | `spa_core/tests/test_claude_run_timeout_ownership.py::OwnershipAtTimeout::test_9_evidence_is_written_before_the_first_kill` | failed | G03 |
| 14 | `spa_core/tests/test_claude_run_timeout_ownership.py::TheInstrumentsAreNotOrnaments::test_with_run_id_the_same_scene_closes` | failed | G03 |
| 15 | `spa_core/tests/test_claude_run_timeout_ownership.py::SigtermIgnoredThenSigkill::test_sigterm_ignoring_tree_is_closed_by_sigkill_with_rc_124` | failed | G03 |
| 16 | `spa_core/tests/test_constitution_right_to_fix.py::LiveControlOnTheRealTree::test_every_form_of_every_pair_is_a_declared_class` | error | G01 |
| 17 | `spa_core/tests/test_constitution_right_to_fix.py::LiveControlOnTheRealTree::test_the_first_axis_shift_rests_on_a_named_pair` | error | G01 |
| 18 | `spa_core/tests/test_constitution_right_to_fix.py::LiveControlOnTheRealTree::test_the_peer_axis_really_shifted` | error | G01 |
| 19 | `spa_core/tests/test_constitution_right_to_fix.py::LiveControlOnTheRealTree::test_the_shelf_is_readable_here_so_nothing_is_unmeasured` | error | G01 |
| 20 | `spa_core/tests/test_decision_journal_coverage.py::ReaderPopulationRatchet::test_every_production_reader_is_in_the_population` | failed | G13e |
| 21 | `spa_core/tests/test_decision_surface_census.py::LiveControlOnTheRealTree::test_the_measure_bites_here` | error | G01 |
| 22 | `spa_core/tests/test_decision_surface_census.py::LiveControlOnTheRealTree::test_the_population_is_declared_and_non_empty` | error | G01 |
| 23 | `spa_core/tests/test_decision_surface_census.py::LiveControlOnTheRealTree::test_the_senior_surface_is_asked_but_not_declared` | error | G01 |
| 24 | `spa_core/tests/test_declared_git_environment.py::TheSuiteDeclaresItsCloneDepth::test_every_pytest_job_declares_full_history` | failed | G15b |
| 25 | `spa_core/tests/test_document_field_reader.py::test_live_measurement_reports_both_liveness_numbers` | failed | G10 |
| 26 | `spa_core/tests/test_document_field_reader.py::test_live_measurement_answers_with_a_pair_of_numbers` | failed | G10 |
| 27 | `spa_core/tests/test_document_field_reader.py::test_blind_spots_name_the_one_sidedness_aloud` | failed | G10 |
| 28 | `spa_core/tests/test_document_field_reader.py::test_report_prints_the_pair_and_the_refusal_names` | failed | G10 |
| 29 | `spa_core/tests/test_edge_boundary_dataflow_census.py::TestTheObserverIsNotPartOfItsOwnPopulation::test_the_census_screens_the_population_100_published` | failed | G13d |
| 30 | `spa_core/tests/test_edge_downside_parity.py::test_downside_denominator_is_exactly_zero_where_volatility_is_not` | failed | G05b |
| 31 | `spa_core/tests/test_finding_address_price.py::WiredIntoTheCensus::test_with_a_tree_both_are_measured` | failed | G01 |
| 32 | `spa_core/tests/test_fixture_schema_gap_ratchet.py::test_the_door_sites_still_add_up_to_the_same_operand` | failed | G13c |
| 33 | `spa_core/tests/test_invisible_consumer_scale.py::WiringTest::test_measure_calls_the_coordinate_and_stores_it_under_its_own_key` | failed | G08 |
| 34 | `spa_core/tests/test_ledger_day_unit_census.py::ProbeRefusesAnUnobservedSubject::test_an_unobserved_subject_is_not_a_pass` | failed | G01 |
| 35 | `spa_core/tests/test_list_identity_census.py::MeasureRefusesInsteadOfGuessing::test_a_measured_population_with_a_candidate_outside_is_a_finding` | error | G01 |
| 36 | `spa_core/tests/test_list_identity_census.py::MeasureRefusesInsteadOfGuessing::test_a_measured_population_without_findings_is_clean` | error | G01 |
| 37 | `spa_core/tests/test_no_import_time_clock_in_tests.py::TestNoImportTimeClockInTests::test_no_unreviewed_import_time_clock` | failed | G19 |
| 38 | `spa_core/tests/test_office_absent_block_producer_aware.py::CensusRatchet::test_the_allowlist_keys_match_the_live_producer_exactly` | failed | G13k |
| 39 | `spa_core/tests/test_office_absent_block_producer_aware.py::CensusRatchet::test_the_exemption_covers_no_MORE_sites_than_it_names` | failed | G13k |
| 40 | `spa_core/tests/test_office_declaration_doors.py::TheLiveAnswerOfTheOrder::test_every_office_artifact_has_a_measurable_producer_tick` | failed | G15a |
| 41 | `spa_core/tests/test_office_subject_drift_producer_tick.py::test_the_live_office_can_measure_the_tick_of_every_artifact_it_reads` | failed | G15a |
| 42 | `spa_core/tests/test_postgres_migration.py::TestMigrateCallsites::test_live_codebase_has_zero_raw_connects` | failed | G12 |
| 43 | `spa_core/tests/test_publication_truth.py::BothPushersRunThePublicationGate::test_a_direct_push_of_an_unverified_shelf_is_blocked_by_either_pusher` | failed | G18 |
| 44 | `spa_core/tests/test_python_git_ref_provenance.py::TestRatchet::test_real_tree_matches_the_frozen_baseline` | failed | G13b |
| 45 | `spa_core/tests/test_python_git_ref_provenance.py::RegistryGovernance::test_an_intact_baseline_passes` | failed | G13b |
| 46 | `spa_core/tests/test_python_git_ref_provenance.py::RegistryReactsToTheCensus::test_removing_an_unresolved_identity_reduces_the_debt` | failed | G13b |
| 47 | `spa_core/tests/test_python_git_ref_provenance.py::RegistryReactsToTheCensus::test_the_unchanged_census_is_green` | failed | G13b |
| 48 | `spa_core/tests/test_recover_trusted_runtime.py::TestDryRunZeroMutation::test_dry_run_reaches_confirmed_broken_and_mutates_nothing` | failed | G05c |
| 49 | `spa_core/tests/test_repair_phantom_intake_cards.py::test_phantom_closed_and_source_reopened` | failed | G11 |
| 50 | `spa_core/tests/test_repair_phantom_intake_cards.py::test_close_note_explains_it_was_not_the_owner` | failed | G11 |
| 51 | `spa_core/tests/test_repair_phantom_intake_cards.py::test_empty_output_signature_also_recognised` | failed | G11 |
| 52 | `spa_core/tests/test_repair_phantom_intake_cards.py::test_mass_case_all_of_them` | failed | G11 |
| 53 | `spa_core/tests/test_repair_phantom_intake_cards.py::test_source_still_open_is_not_disturbed` | failed | G11 |
| 54 | `spa_core/tests/test_repair_phantom_intake_cards.py::test_missing_source_is_reported_not_silently_dropped` | failed | G11 |
| 55 | `spa_core/tests/test_repair_phantom_intake_cards.py::test_rerun_is_idempotent` | failed | G11 |
| 56 | `spa_core/tests/test_research_evidence_tracks.py::test_facts_jsonl_no_fact_lacks_a_citation_from_the_seed_file` | failed | G05f |
| 57 | `spa_core/tests/test_rule_second_copy_census.py::LiveControlOnTheRealTree::test_accounting_identity_holds_on_the_real_tree` | error | G01 |
| 58 | `spa_core/tests/test_rule_second_copy_census.py::LiveControlOnTheRealTree::test_every_printed_row_survives_an_independent_recheck` | error | G01 |
| 59 | `spa_core/tests/test_rule_second_copy_census.py::LiveControlOnTheRealTree::test_the_real_tree_is_measured_at_all` | error | G01 |
| 60 | `spa_core/tests/test_rule_second_copy_census_wiring.py::OfficeReadsTheNumberNotJustTheFile::test_declared_shape_is_the_shape_the_producer_actually_writes` | failed | G01 |
| 61 | `spa_core/tests/test_rule_second_copy_census_wiring.py::TheGuardsOfThisInstrumentDoNotBecomeItsOwnFinding::test_own_test_files_are_not_rows` | failed | G01 |
| 62 | `spa_core/tests/test_rule_second_copy_peer_axis.py::LiveControlOnTheRealTree::test_the_axis_is_not_empty_on_this_repository` | failed | G01 |
| 63 | `spa_core/tests/test_run_identity_key_price.py::BatteryHoleTests::test_the_guard_is_lowered_again_after_a_sweep` | error | G01 |
| 64 | `spa_core/tests/test_run_identity_key_price.py::BatteryHoleTests::test_the_instrument_excludes_itself_by_naming_the_reason` | failed | G02 |
| 65 | `spa_core/tests/test_safe_terminate_ownership.py::OwnedIsOwnedAndForeignIsNot::test_a_child_without_our_stamp_is_NOT_OWNED` | failed | G03 |
| 66 | `spa_core/tests/test_safe_terminate_ownership.py::OwnedIsOwnedAndForeignIsNot::test_a_process_with_a_DIFFERENT_run_id_is_NOT_OWNED` | failed | G03 |
| 67 | `spa_core/tests/test_safe_terminate_ownership.py::OwnedIsOwnedAndForeignIsNot::test_our_own_stamped_child_is_OWNED` | failed | G03 |
| 68 | `spa_core/tests/test_safe_terminate_ownership.py::OwnedIsOwnedAndForeignIsNot::test_the_same_command_in_the_expected_cwd_is_OWNED` | failed | G03 |
| 69 | `spa_core/tests/test_safe_terminate_ownership.py::IdentityIsNotJustThePid::test_a_pinned_identity_that_no_longer_matches_is_IDENTITY_MISMATCH` | failed | G03 |
| 70 | `spa_core/tests/test_safe_terminate_ownership.py::IdentityIsNotJustThePid::test_the_matching_identity_is_OWNED` | failed | G03 |
| 71 | `spa_core/tests/test_safe_terminate_ownership.py::GoneIsIdempotentSuccess::test_an_already_exited_process_is_PROCESS_GONE` | failed | G03 |
| 72 | `spa_core/tests/test_safe_terminate_ownership.py::GoneIsIdempotentSuccess::test_terminating_a_gone_process_is_a_no_op_success` | failed | G03 |
| 73 | `spa_core/tests/test_safe_terminate_ownership.py::GoneIsIdempotentSuccess::test_the_call_is_idempotent` | failed | G03 |
| 74 | `spa_core/tests/test_safe_terminate_ownership.py::TerminationItself::test_a_sigterm_ignoring_owned_process_needs_KILL` | failed | G03 |
| 75 | `spa_core/tests/test_safe_terminate_ownership.py::TerminationItself::test_an_owned_process_is_terminated_by_TERM` | failed | G03 |
| 76 | `spa_core/tests/test_safe_terminate_ownership.py::TerminationItself::test_identity_change_between_TERM_and_KILL_blocks_the_KILL` | failed | G03 |
| 77 | `spa_core/tests/test_safe_terminate_ownership.py::NoSecretReachesTheEvidence::test_the_identity_tuple_carries_a_hash_not_the_command` | failed | G03 |
| 78 | `spa_core/tests/test_shadow_tvl_provenance.py::TestAcceptanceProbe::test_probe_is_satisfied_on_this_tree` | failed | G13a |
| 79 | `spa_core/tests/test_shadow_tvl_provenance.py::TestAcceptanceProbe::test_probe_refuses_when_a_number_rides_without_its_rod` | failed | G13a |
| 80 | `spa_core/tests/test_shadow_tvl_provenance.py::TestAcceptanceProbe::test_probe_refuses_when_a_tvl_literal_still_reaches_the_number` | failed | G13a |
| 81 | `spa_core/tests/test_shell_git_cd_repo_identity.py::GuardOnTheGuard::test_empty_baseline_makes_the_real_tree_run_red_by_name` | failed | G05e |
| 82 | `spa_core/tests/test_shell_git_cd_repo_identity.py::GuardOnTheGuard::test_shipped_baseline_is_green_and_covers_the_measured_subject` | failed | G05e |
| 83 | `spa_core/tests/test_site_snapshot_view_shape.py::TheViewCoversTheSnapshotShape::test_every_snapshot_field_is_covered_or_declared` | failed | G13l |
| 84 | `spa_core/tests/test_slo_keepability.py::ExitCodesSeparateThreeOutcomes::test_everything_keepable_exits_zero` | failed | G06 |
| 85 | `spa_core/tests/test_state_journal_coverage_audit.py::test_live_state_no_longer_carries_uncovered_chronicle` | failed | G13j |
| 86 | `spa_core/tests/test_subject_population_census.py::PopulationCompletenessIsASeparateAssertion::test_the_precise_road_is_a_subset_of_the_recall_road` | failed | G13f |
| 87 | `spa_core/tests/test_table_form_census.py::Wiring::test_a_coordinate_without_channels_says_unmeasured` | error | G01 |
| 88 | `spa_core/tests/test_table_form_census.py::Wiring::test_a_coordinate_without_shares_says_unmeasured` | error | G01 |
| 89 | `spa_core/tests/test_table_form_census.py::Wiring::test_a_report_without_the_key_says_unmeasured` | error | G01 |
| 90 | `spa_core/tests/test_table_form_census.py::Wiring::test_a_single_missing_channel_is_named_not_skipped` | error | G01 |
| 91 | `spa_core/tests/test_table_form_census.py::Wiring::test_measure_calls_the_coordinate` | error | G01 |
| 92 | `spa_core/tests/test_table_form_census.py::Wiring::test_report_renders_the_section` | error | G01 |
| 93 | `spa_core/tests/test_table_form_census.py::Wiring::test_the_coordinate_does_not_widen_the_declared_surfaces` | error | G01 |
| 94 | `spa_core/tests/test_table_form_census.py::Wiring::test_the_coordinate_is_serialisable` | error | G01 |
| 95 | `spa_core/tests/test_table_form_census.py::Wiring::test_the_live_tree_answers_the_order` | error | G01 |
| 96 | `spa_core/tests/test_tail_value_divergence.py::AggregateTest::test_a_reachable_divergence_changes_the_verdict` | failed | G07 |
| 97 | `spa_core/tests/test_tail_value_divergence.py::AggregateTest::test_agreement_everywhere_is_its_own_verdict` | failed | G07 |
| 98 | `spa_core/tests/test_tail_value_divergence.py::AggregateTest::test_blindness_is_stated_not_implied` | failed | G07 |
| 99 | `spa_core/tests/test_tail_value_divergence.py::AggregateTest::test_counts_cover_every_read` | failed | G07 |
| 100 | `spa_core/tests/test_tail_value_divergence.py::AggregateTest::test_divergence_nobody_can_see_is_not_called_harmless` | failed | G07 |
| 101 | `spa_core/tests/test_tail_value_divergence.py::AggregateTest::test_documents_are_counted_not_reads` | failed | G07 |
| 102 | `spa_core/tests/test_tail_value_divergence.py::AggregateTest::test_kind_conflicts_are_counted_separately` | failed | G07 |
| 103 | `spa_core/tests/test_tail_value_divergence.py::AggregateTest::test_text_only_divergence_is_not_counted_as_divergence` | failed | G07 |
| 104 | `spa_core/tests/test_tail_value_divergence.py::WiringTest::test_measure_binds_the_step_and_returns_that_binding` | failed | G08 |
| 105 | `spa_core/tests/test_tail_value_divergence.py::ReportTest::test_measured_step_prints_both_numbers` | failed | G07 |
| 106 | `spa_core/tests/test_tail_value_divergence.py::WholeContourTest::test_reach_is_measured_for_every_costed_read` | failed | G07 |
| 107 | `spa_core/tests/test_tail_value_divergence.py::WholeContourTest::test_the_aggregate_reads_this_contour_end_to_end` | failed | G07 |
| 108 | `spa_core/tests/test_tail_value_divergence.py::AbsentReachIsNotAnOutcome::test_a_known_reach_still_measures` | failed | G07 |
| 109 | `spa_core/tests/test_tail_value_divergence.py::AbsentReachIsNotAnOutcome::test_an_unmeasured_reach_is_not_read_as_not_reaching` | failed | G07 |
| 110 | `spa_core/tests/test_tail_value_divergence.py::AbsentReachIsNotAnOutcome::test_kind_conflicts_are_still_counted_with_reach_present` | failed | G07 |
| 111 | `spa_core/tests/test_tail_value_divergence.py::AbsentReachIsNotAnOutcome::test_the_second_name_for_reach_is_gone_from_the_code` | failed | G09 |
| 112 | `spa_core/tests/test_timeseries_lane_modules.py::test_falling_apy_riskier_than_rising[apy_tracker]` | failed | G06 |
| 113 | `spa_core/tests/test_truncated_input_census.py::TheJanitorSeesEveryWorktree::test_trees_beyond_the_old_budget_are_still_found` | failed | G05d |
| 114 | `spa_core/tests/test_unwired_guard_modules_ratchet.py::test_no_new_guard_module_is_left_unwired` | failed | G13g |
| 115 | `spa_core/tests/test_unwired_guard_modules_ratchet.py::test_fixed_modules_leave_the_census` | failed | G13g |
| 116 | `spa_core/tests/test_unwired_registry_evidence.py::TestTheRuleOnTheRealRepo::test_the_carve_out_did_not_swallow_the_watch` | failed | G13h |
| 117 | `spa_core/tests/test_unwired_scripts_ratchet.py::TestRatchet::test_no_NEW_unwired_script_appears` | failed | G13i |
| 118 | `scripts/tests/test_check_concurrent_pytest.py::TestOpenFilesParsesRealLsof::test_a_live_process_holding_a_written_file_reads_READABLE` | failed | G04 |
| 119 | `scripts/tests/test_check_concurrent_pytest.py::TestOpenFilesParsesRealLsof::test_a_live_process_whose_only_write_target_is_unlinked_reads_UNREADABLE` | failed | G04 |
| 120 | `scripts/tests/test_check_concurrent_pytest.py::TestOpenFilesParsesRealLsof::test_a_real_file_open_for_writing_is_parsed_with_its_mode_and_inode` | failed | G04 |
| 121 | `scripts/tests/test_fill_agent_passports.py::TestManifestFormatIsPreserved::test_manifest_on_disk_is_byte_identical_to_a_reserialization` | failed | G17 |
| 122 | `scripts/tests/test_shell_git_cd_target_census.py::RatchetOnTheRealTree::test_real_tree_subject_is_within_the_baseline` | failed | G14 |
| 123 | `scripts/tests/test_shell_git_cd_target_census.py::RatchetOnTheRealTree::test_the_ratchet_is_able_to_fail` | failed | G14 |
