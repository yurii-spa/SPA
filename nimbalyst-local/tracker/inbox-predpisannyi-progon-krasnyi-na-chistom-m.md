---
trackerStatus:
  type: inbox
title: "Предписанный прогон КРАСНЫЙ на чистом main: 17 падений, замер на пришпиленном af1d972eb"
status: new
source: nimbalyst
created: 2026-08-29
priority: high
---

Найдено замером цикла #427: контрольный полный прогон предписанного набора на
**пришпиленном чистом `origin/main` (`af1d972eb`)**, без единой правки в дереве.

    python3 -m pytest spa_core/tests/ -q -p no:randomly
    18 failed, 98161 passed, 619 skipped  (2:12:05)

Одно из восемнадцати (`test_frozen_date_ratchet`) цикл #427 починил и доставил.
**Остальные семнадцать стоят на `main` прямо сейчас** — то есть предписанный
`CLAUDE.md` прогон, тот самый, который гейтит CI, КРАСНЫЙ на чистой ветке.

## Что именно красное (по файлам, 17 падений в 10 файлах)

| файл | падений |
|---|---|
| `test_office_opportunities_are_observations.py` | 3 |
| `test_api_surface_snapshot.py` | 3 |
| `test_absent_observation_ratchet.py` | 3 |
| `test_telegram_outbound_guard.py` | 2 |
| `test_unwired_scripts_ratchet.py` | 1 |
| `test_telegram_selfheal_spam.py` | 1 |
| `test_telegram_flood_shared.py` | 1 |
| `test_state_journal_coverage_audit.py` | 1 |
| `test_session_anchor_proves_nothing.py` | 1 |
| `test_doc_drift.py` | 1 |

Полный поимённый список — в `docs/journal/2026-W35.md`, раздел цикла #427.

## Почему это карточка, а не строчка

Красный набор на `main` — это не фон, это **отключённый сторож**: пока в нём
семнадцать постоянных падений, восемнадцатое (настоящее) никто не заметит.
Ровно этим механизмом в проекте уже теряли находки — «сторож, который всегда
красный, читается как сторож, которого нет».

Два признака, что часть из них — не дефекты кода, а **зависимость вердикта от
окружения**, и чинить их надо у источника:

- `test_session_anchor_proves_nothing::test_announce_refuses_to_record_a_timer_as_the_anchor`
  судит по литеральному `SPA_SESSION_PID: "42391"` — ОС переиспользует номера
  процессов, это литеральный pid, то есть та же бомба замедленного действия,
  что литеральная дата;
- `test_state_journal_coverage_audit::test_live_state_no_longer_carries_uncovered_chronicle`
  судит ЖИВОЙ `docs/STATE.md` (сейчас MISSING = строка 84, циклы 408/416/425) —
  падает от чужой недописанной хроники, а не от кода.

## Что от исполнителя

Разобрать по одному, каждый — на вопрос «это дефект кода, устаревшая фикстура
или вердикт, решаемый окружением?». **Ослаблять/скипать запрещено** (инвариант
#16): красный тест — сигнал. Ответ «фикстура устарела» закреплять починкой
фикстуры, а не расширением базы храповика.

## Как понять, что готово

Полный предписанный прогон на чистом `origin/main` даёт ноль падений — либо
каждое оставшееся названо поимённо с записанной причиной, почему оно красное
осознанно (как `edge_exposure_depth` в `docs/STATE.md`).

---

## Перемер цикла #489 (2026-09-05) — краснота ЖИВА, состав `absent_observation` уточнён

Контрольный прогон `test_absent_observation_ratchet.py` на **пришпиленном чистом
`origin/main` 7a2612685** (отдельное дерево, без единой правки): **3 failed, 17 passed** —
те же три теста, что перечислены выше.

Уточнение к строке таблицы: краснота не «сдвиг строк» (тот класс закрыт хеш-ключом,
карточка `inbox-hrapovik-otsutstvie-nablyudeniya-krasnee`, done). Сегодня это **10
НЕПЕРЕЧИСЛЕННЫХ членов класса** — в дереве 202 при базе 192, «только в базе: []», то есть
база не устарела, а отстала от кода. Поимённо новые живут в четырёх файлах:
`scripts/check_owner_order_starvation.py`, `spa_core/monitoring/architecture_conformance.py`,
`spa_core/monitoring/capital_evidence_coverage.py` (три места),
`spa_core/monitoring/findings_bridge.py`, `spa_core/telegram/reports/daily.py`.

Дописывать их в базу ЗАПРЕЩЕНО (сам храповик это и говорит) — чинить писателей.

**Дифференциал цикла #489:** дерево с правками ADR-230 даёт **тот же самый список**, что
чистый `origin/main`, — новый модуль `apy_composition.py` в классе не состоит (первая
редакция состояла тремя местами, они убраны, а не внесены в базу). То есть эта краснота
к доставке #489 отношения не имеет и ею не создана.

## Перемер цикла #634 (2026-09-18): краснота ЖИВА, и СОСТАВ СМЕНИЛСЯ ПОЛНОСТЬЮ

Контрольный прогон `spa_core/tests/` на **пришпиленном чистом `origin/main` `c32b997b`**
(отдельное дерево, без единой правки): **18 failed, 249 passed** на радиусе из 10 файлов;
полный прогон того же каталога в дереве цикла #634 — **18 failed, 104 021 passed, 641
skipped** (2 ч 14 мин).

**Дифференциал: множества падений РАВНЫ ПОИМЁННО** (не по числу — по именам; сравнивать
числа значило бы принять замену одного падения другим за отсутствие изменений). Вклад
доставки #634 (`7bdd28e0`, ADR-417) в красноту — **ноль**.

**Главное в этом перемере — не число, а СОСТАВ: он не пересекается с замером 29.08 ни
одним файлом.**

| файл | падений (18.09) |
|---|---|
| `test_heir_all_rows_price.py` | 7 |
| `test_heir_all_rows_price_survivors.py` | 3 |
| `test_capital_observability_history.py` | 1 |
| `test_cio_brief_book_wiring.py` | 1 |
| `test_deploy_site_snapshot.py` | 1 |
| `test_edge_boundary_dataflow_census.py` | 1 |
| `test_owner_gate_approval_scope.py` | 1 |
| `test_python_git_ref_provenance.py` | 1 |
| `test_state_journal_coverage_audit.py` | 1 |
| `test_tracker_board_matches_cards.py` | 1 |

Против таблицы 29.08 совпадает РОВНО ОДНА строка — `test_state_journal_coverage_audit.py`;
остальные девять файлов новые, а все девять прежних (`test_office_opportunities_are_observations`,
`test_api_surface_snapshot`, `test_absent_observation_ratchet`, `test_telegram_outbound_guard`,
`test_unwired_scripts_ratchet`, `test_telegram_selfheal_spam`, `test_telegram_flood_shared`,
`test_session_anchor_proves_nothing`, `test_doc_drift`) сегодня зелены.

**Что это значит и чего НЕ значит.** Значит: прежние падения чинились, и класс не застыл.
НЕ значит, что стало лучше — число то же (17–18), а набор обновился целиком. То есть
краснота ведёт себя как ПОТОК, а не как остаток: одни чинятся, другие заводятся, и всё это
время предписанный прогон остаётся отключённым сторожем ровно в том смысле, что описан выше.
Мерить эту карточку числом падений поэтому нельзя — только поимённым составом с датой.

**Не чинится прицепом намеренно** (инв. #16): ни одно из 18 к предмету цикла #634 отношения
не имеет, а тихая правка чужого красного теста — ровно тот путь, которым сторожа становятся
декорацией. Одно из них уже несёт свою карточку
(`inbox-test-tozhdestva-kapitala-krasen-na-chist`, 16.09).

---

## Перезамер 2026-09-20 (цикл #645), пришпилен `origin/main` 6916ba90

Карточка жива. Замер сделан не полным набором, а ВЫБОРКОЙ
(`spa_core/tests/ -k "bridge or office or manifest or architecture or ratchet or census or probe"`,
3763 теста) — то есть это **нижняя граница**, а не новый полный перечень:

    2 failed, 3761 passed, 9 skipped (15:08)

Оба красных воспроизведены на ЧИСТОМ пришпиленном дереве (`/tmp/spa_c645_ctl`,
тот же sha, без единой правки) — то есть это состояние `main`, а не чьей-то работы:

| тест | что говорит |
|---|---|
| `test_edge_boundary_dataflow_census.py::…::test_the_census_screens_the_population_100_published` | `36 != 35` — население выросло на модуль, число в тесте не перевыведено |
| `test_python_git_ref_provenance.py::TestRatchet::test_real_tree_matches_the_frozen_baseline` | `предмет ВЫРОС на 2 — scripts/check_owner_gate.py:242, 248` |

Второй — храповик, и он говорит ровно то, ради чего написан: в `check_owner_gate.py`
появились два новых чтения git-ref, которых нет в базе. **Дописывать базу запрещено**
(инв. #16), чинить надо читателей либо обосновать рост записью в журнал.

`scripts/tests/` в том же дереве — **447 passed, зелено целиком**.
