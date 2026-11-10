# ADR-976 — Ответ владельца 10.11 (вариант 1) исполнен: окно свежести 36 ч стареет и снимок оркестратора — одна дверь `_within_window` на оба источника, проба `snapshot_evidence_ages_out` satisfied

- **Статус:** принято (исполнение ответа владельца; money-path `spa_core/allocator/`, пороги RiskPolicy не тронуты)
- **Дата:** 2026-11-10
- **Цикл:** #1093 (`cycle-63852`), заказ G963 п. 1 карточки приказа `inbox-task-portfolio-cio-dynamic-capital-alloc`
- **Карточка-исполнитель:** `inbox-ispolnit-otvet-vladeltsa-10-11-variant-1` (проба `snapshot_evidence_ages_out`
  объявлена ДО работы циклом #1092 — ADR-975; этой сессией НЕ правилась, `.claude/rules/acceptance.md` п. 2)
- **Ответ владельца:** `owner-decision-proverka-svezhesti-dannyh-ne-primenyaets` — вариант 1, 2026-11-10T11:05Z,
  Telegram; записан ADR-975 (форма ADR-839)
- **Продолжает:** ADR-969 (§26, находка `evidence_that_never_ages`) · ADR-061/ADR-303 (окно 36 ч у второго
  источника, 2026-08-04) · ADR-053 (TVL только живым) · ADR-972 (образец исполнения ответа владельца: проба
  от одной сессии, работа — другой)
- **Батарея:** `spa_core/tests/test_allocator_snapshot_window_owner_answer_2026_11_10.py` (новая, 14 проверок) +
  двойник аллокатора образца 09.11 `spa_core/tests/_never_aging_allocator.py` + правки трёх тестов, чьё
  УТВЕРЖДЕНИЕ сменилось ответом владельца (инв. #16, таблица ниже)

## Решение (что сделано)

Владелец 10.11 выбрал **вариант 1**: применить к снимку собственного опросчика
(`data/adapter_orchestrator_status.json`) **то же окно 36 часов**, что и ко второму источнику
(`data/adapter_status.json`). Замер ADR-969 (ось C §26): на сдвиге часов на год **9 протоколов** источника
`orchestrator_live` оставались «доказанными» — умри опросчик, гейт `_fundable` вечно считал бы его последний
снимок свежим. Строка `CLAUDE.md` «stale-фид → `unevidenced`» была верна про один источник из двух.

| | до (ADR-061/303) | после (этот ADR) | ответ владельца | проверка |
|---|---|---|---|---|
| правило | окно `_EVIDENCE_MAX_AGE_H = 36` ч применяется ТОЛЬКО к `adapter_status.json`; запись снимка оркестратора с `live_data=true` — доказательство навсегда | окно применяется к ОБОИМ источникам **через одну дверь** `_within_window(as_of, fallback_ts)` с тем же входом `now`; возраст записи снимка — от её `last_updated`, иначе от `generated_at` файла; неразбираемая/отсутствующая отметка ⇒ не доказательство (fail-CLOSED, инв. #2) | «Вариант 1 — применить к снимку то же окно 36 часов» | `test_snapshot_entry_outside_the_window_is_not_evidence` · `…inside…` · `…generated_at_is_the_clock` · `…unparseable_last_updated…` · `…no_stamp_at_all…` |
| одна дверь, одна константа | — | сдвиг `_EVIDENCE_MAX_AGE_H` двигает ОБА источника вместе; второй копии окна нет | «то же окно» | `test_one_door_one_window_for_both_sources`; мутация M04 (вторая копия литералом `36.0`) |
| прибор §26 на живых данных | `APY-evidenced 22→9` на сдвиге 8760 ч; **CRITICAL `evidence_that_never_ages`** ({'orchestrator_live': 9}) | `APY-evidenced 22→0`, `TVL 19→0`; находки `evidence_that_never_ages` **нет** (остались `result_depends_on_the_clock` — это и есть окно, работающее на обоих, — и `fifth_input_unpinnable`, предмет G957) | — | `python3 -m spa_core.analytics.determinism_census --data-dir <прод>/data --no-write` |
| проба приёмки | `not_satisfied`: «на сдвиге 8760 ч годными остаются 9 протоколов {'orchestrator_live': 9}» | **`satisfied`**: «годных протоколов нет ни у одного источника (окно 36.0 ч действует на оба)» | — | `card_acceptance.PROBES["snapshot_evidence_ages_out"]` на `--data-dir` прод |
| боевой путь без `now` | стенные часы | стенные часы (умолчание не менялось) | — | `test_default_clock_is_the_wall_clock_only_when_now_is_absent` |
| `CLAUDE.md` строка о деградации | «stale-фид → unevidenced» без оговорки | «…окно 36 ч стареет ОБА источника…» + вторая команда проверки + дата 10.11 | — | строка таблицы «Проверенные факты» |
| пороги RiskPolicy v1.0 | — | **не тронуты** | — | `pre_cutover_gate --json-only --no-save`: `defenses_passed 17/17`, `all_defenses_fired=True`, `is_inert=True` |

**Почему возраст — от записи, а не только от файла.** Запись снимка несёт `last_updated` (у живого снимка
10.11 — одна отметка на все 11 записей, равная `generated_at`), и это та же дисциплина, что у
`live_apy_as_of` второго источника: перенесённое вперёд наблюдение обязано стареть по своим часам. Если
записи отметки нет — часы файла; если отметка есть, но не разбирается — возраст неизвестен, а неизвестный
возраст доказательством не является (мутация M02 держит именно это звено: «упасть на `generated_at`» — fail-OPEN).

**Чего это НЕ делает.** `_load_evidenced_tvl` не менялся: он читает ОДИН источник (`adapter_status.json`) и уже
стареет по окну (ADR-303) — на живых данных `TVL 19→0`, нестареющей ветки там не было. Пятый вход §26 (`now` у
точки входа аллокатора и тюнера) по-прежнему не пришпиливается вызывающим — это заказ G957, отдельная работа.

## Что сменилось в тестах — и почему это не ослабление (инв. #16)

Ни один тест не удалён, не скипнут и не сужен. У трёх проверок сменилось УТВЕРЖДЕНИЕ при том же предмете;
каждая несёт пометку «ИЗМЕНЕНО НАМЕРЕННО (ADR-976, инв. #16)», и прежний исход остался ДОСТИЖИМЫМ сценой —
двойником аллокатора образца 09.11 (`spa_core/tests/_never_aging_allocator.py`: ветка снимка игнорирует `now`,
ветка `adapter_status` идёт через настоящую дверь). Проба `snapshot_evidence_ages_out` не правилась ни на символ.

| файл · тест | было | стало | прежний исход достижим |
|---|---|---|---|
| `test_determinism_census::test_axis_c_names_the_source_that_never_ages` | на живом аллокаторе `{'orchestrator_live': 1}` | то же утверждение — на двойнике; живой аллокатор — новый `test_axis_c_live_allocator_ages_both_sources_out` (`{}`) | да — тот же тест, через `install(monkeypatch)` |
| `test_determinism_census::test_axis_c_result_changes_from_the_clock_alone` | на сдвиге 48 ч выживал `from_orchestrator` | на сдвиге 48 ч годных нет (`[]`); предмет «зависит от одних часов» не изменился — `changed_at_offsets == [48.0]` | да — двойником |
| `test_probe_snapshot_evidence_ages_out::test_probe_on_the_scene_names_the_source_that_never_ages` | `not_satisfied` на живом аллокаторе | `not_satisfied` — на двойнике; живой аллокатор — новый `test_probe_on_the_live_allocator_scene_is_satisfied` | да — тот же тест |

Контроль в ОБЕ стороны у самого прибора и пробы сохранён: `test_the_old_defect_is_still_reachable_and_still_caught`
подставляет двойника и требует от прибора находку, а от пробы — `not_satisfied` с именем источника.

## Приёмка

- батарея (10 файлов: новый + проба + §26 + `test_allocator_evidence_gate` · `…_source_shape` · `test_apy_provenance` ·
  `test_feed_staleness_policy` · `test_defi_engine` · `test_pre_cutover_gate` · `test_allocator_advisors`): **213 passed**
  после правки трёх утверждений (до неё — 1 failed: ровно пришпиленный дефект, таблица выше);
- мутации (`delta_mutation_run.py`, спецификация `docs/mutations/SMC-976-2026-11-10.json`, отдельное дерево
  `/private/tmp/spa_mut_1093`, 4 якоря уникальны): **4/4 убиты в один проход** (M01 окно снято · M02 неразбираемая отметка падает на `generated_at` · M03 отметка записи игнорируется · M04 вторая копия окна литералом), выживших 0, окно прибора снято (`--window-check` → код 0), байты аллокатора сверены md5 с деревом доставки;
- `pre_cutover_gate --json-only --no-save`: **17/17 defenses, all fired, inert**; живое `data/` не тронуто;
- прибор §26 на прод-данных (`--no-write`): `evidence_that_never_ages` **исчезла**; проба на прод-данных — **`satisfied`**;
- соседи и храповики — в журнале цикла #1093 (`docs/journal/2026-W46.md`): **2 failed, 6147 passed, 22 skipped** за 33 мин 38 с (223 файла, финальные байты полного набора ADR-974…977, цикл #1094) — оба падения красны на чистом `origin/main` e2ec97d9f (`/private/tmp/spa_base_1094`, дифференциально): `test_inbox_acceptance_ratchet::test_no_new_card_is_in_work_without_a_criterion` (карточки этого цикла не названы) и `test_tier_curator::test_no_module_consumes_report_to_mutate_tiers` (`cadence_census.py`, чужой долг); своих 0.

## Последствия

- Карточка-исполнитель `inbox-ispolnit-otvet-vladeltsa-10-11-variant-1` → `done` с этим ADR как доказательством;
  карточка владельца `…proverka-svezhesti…` (`ingested`) получает ссылку на исполнение.
- Ответ владельца исполнен в тот же день (11:05Z → этот цикл), а не через 13 дней, как у §28 (ADR-971).
- Утверждение `CLAUDE.md` «реакция на деградацию автоматическая» теперь верно про оба источника доказательности.

## Команда перемера

```bash
SPA_ENV=ci python3 -m spa_core.analytics.determinism_census --data-dir /Users/yuriikulieshov/Documents/SPA_Claude/data --no-write
SPA_ENV=ci PYTHONHASHSEED=0 python3 -m pytest spa_core/tests/test_allocator_snapshot_window_owner_answer_2026_11_10.py spa_core/tests/test_probe_snapshot_evidence_ages_out.py spa_core/tests/test_determinism_census.py -q -p no:randomly
```
