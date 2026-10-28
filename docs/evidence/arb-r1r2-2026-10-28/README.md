# ARB 27.10 · R1/R2 — перенос ревью и исправление (ADR-839)

Что здесь лежит и откуда:

| файл | что это |
|---|---|
| `ARB_REVIEW.md` | ревью ARB от 27.10, дословно (источник — рабочий каталог ARB `arb_2026-10-27/review_backlog_closure`) |
| `reproduce_boundaries.py` · `reproduction_results.json` | воспроизведения ARB на коде `e111f037`, дословно. Скрипт читал прод-дерево; копии проверенных модулей не перенесены — они совпадают с `e111f037` побайтно (sha256 в `reproduction_results.json`) и лежат в истории git |
| `reproduction_results_after_fix.json` | те же пять сцен на исправленном коде (замер 28.10, писатель не подменён; каждый отказ сверен на «карточка не тронута / файл итога не создан»). Скрипт замера в `docs/evidence/` не хранится: файл вне автосинка, импортирующий `spa_core`, запрещён сторожем `test_unsynced_hard_imports`. Те же сцены — тесты: `test_owner_session_answer.py::test_arb_case_1/2/3_*`, `test_work_packet_chain.py::test_arb_wrong_task_*`, `::test_arb_unregistered_unrun_probe_*` |

Итог: 5 из 5 сцен отказывают (таблица «до → после» — в ADR-839). Мутации `docs/mutations/ADR-839.json`: 20/20 убито.
Реальные данные не тронуты: 18 карточек ответов 27.10 не переписывались (сверка с реестром — 18/18 на origin), `approval.json`/`outcome.json`
сценария 27.10 в `~/studio-os-serve/task_prep/…/20261027T145059Z-bb29cae0/` — md5 до и после замера совпали.
