# CI v5 повтор 40478342792 (d8baff308) — ПОЛНЫЙ, критерии по исходам выполнены, но доставка ОТКАЗАНА гейтом — и гейт был прав наполовину

Дата: 2026-10-27, 09:07–09:37 UTC. Ветка `release/task-prep-20261027`, SHA `d8baff308b75712e1a9e70b80f1b7b3cb22db4be`.

## Полнота
population 136 549 · passed 135 768 · skipped 719 · **failed 62** · error 0 · **not obtained 0** · collect errors 0 ·
шардов **12/12**. Вердикт CI — **RED** (давние падения main); зелёным его не называю.

## Сравнение (`scripts/ci_control.py compare`)
| база | new | pre-existing | fixed |
|---|---|---|---|
| родитель 6ca0ce2a8 / 40353173933 | 5 | 57 | 9 |
| main 908015739 / 40454032149 | **1** | 61 | 9 |
| v4 4a326236b / 40465677790 | 5 | 57 | 1 |

- **9 исправленных исходов** (`test_python_git_ref_provenance.py`, RegistryGovernance ×4, RegistryReactsToTheCensus ×1, TestRatchet ×4) — каждый `ok` в потоке шардов, не skip.
- Тесты пакета исполнены: `test_model_roles_contract` 27, `_probe` 78, `_review` 19, `test_role_pack` 15, `test_task_prep` 43, `test_task_prep_record` 38, `test_owner_view*` 127 — все `ok`.
- 5 «новых против родителя» на main уже красные (там pre-existing) — не от пакета.
- **1 новый против main** — `test_card_acceptance::TestRegisteredProbesAreReal::test_every_registered_probe_returns_a_known_verdict`: `Failed: Timeout (>180.0s)` внутри пробы `ledger_census_artifact_reaches_the_cycle` (`ledger_parse_census.view_reference_files` → `rglob`). Тот же SHA d8baff308 этот тест ПРОШЁЛ в 40469786128; на родителе 6ca0ce2a8 и на v4 он падал тем же таймаутом; модуль `ledger_parse_census` в пакет не входит. Нестабилен по скорости раннера — не от пакета.

## Скрытая регрессия, найденная гейтом пушера
Сухой прогон штатного пушера (`--expected-base 2d94de8b9…`, байты 24 файлов = blob релиза, `BLOBS_MATCH`) дал **ОТКАЗ rc 7 (номера ADR)**:
1. «в INDEX.md нет строки ADR-OWN» — **по сути ВЕРНО**: `test_live_registry_of_decisions_is_intact` на кандидате получил **27-ю** жалобу (`ADR-OWN-2026-10-23-model-independent-studio.md … решение вне реестра`) против 26 на main. `compare` по имени теста её не видит: тест красный и на main. Критерий «новых failed нет» по ИСХОДАМ выполнялся, по СОДЕРЖАНИЮ — нет.
2. «номер ADR-OWN уже занят» — **дефект гейта**: шапка `scripts/adr_number.py` объявляет именованные ключи отдельным пространством без распределения, а проверки судили `OWN` как номер; любое новое решение владельца было недоставляемо по построению.

`--allow-adr-collision` НЕ использовался (мандат: гейты не обходить). Файл ADR из релиза выкинуть нельзя — `role_pack` читает его как источник полномочий роли.

## Что сделано
- **Починка гейта** отдельным изменением: `fix/adr-named-family-20261027` = `cbc92bc4e` (на main 2d94de8b9): для именованного ключа — только ссылка в реестре тем же разбором, что `check_index_links`; числовой ряд не изменён; 5 тестов, контроль в обе стороны (мутации — по 2 красных), журнал W44. CI **40483603156**.
- **Кандидат v6** `release/task-prep-20261027-v6` = `df98c5afe` (поверх cbc92bc4e): байты пакета = d8baff308 (24 пути) + одна строка `INDEX.md`. Реестр на v6 — 25 жалоб, ровно как на main+гейт; исправленный гейт на наборе v6 — rc 0. CI **40483606025**.
- Резерв прода снят ДО попытки пуша: `~/studio-os-serve/backups/task_prep_delivery_20261027T094056Z/` (архив 10 018 файлов, `git status --porcelain` 2729 строк, неотслеживаемых 693, HEAD прода). `deployment_acceptance` до — OK (rc 0). Свежая сверка: все 24 пути — новые и в проде отсутствуют либо побайтно равны main.

Production и `main` НЕ изменены. Результат d8baff308 кандидату v6 не приписывается — у v6 свой CI.
