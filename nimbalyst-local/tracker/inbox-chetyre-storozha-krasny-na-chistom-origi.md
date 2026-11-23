---
trackerStatus:
  type: inbox
title: "Четыре сторожа красны на чистом origin/main (замер #1218), пятый закрыт тем же циклом"
status: new
source: nimbalyst
created: 2026-11-23
kind: task
priority: medium
twin_key: "sha256:a7868e657a45b3c1734afd41ba16dac0b515bf5ee89c388a783558bc6213b535"
---

## Что случилось и почему это важно

Цикл #1218 мерил другой класс и попутно прогнал 114 сторожей на ЧИСТОМ
`origin/main` 2fc564a0e (одноразовый worktree, без чужих правок). **Пять из них
красны ДО любой моей правки** — то есть красны на `main` прямо сейчас:

| тест | что он говорит |
|---|---|
| `test_decision_journal_coverage.py::ReaderPopulationRatchet::test_every_production_reader_is_in_the_population` | читатель прода вне объявленного населения |
| `test_edge_boundary_dataflow_census.py::TestTheObserverIsNotPartOfItsOwnPopulation::test_the_census_screens_the_population_100_published` | наблюдатель попал в своё же население |
| `test_tier_curator.py::test_no_module_consumes_report_to_mutate_tiers` | модуль потребляет отчёт тир-куратора, чтобы двигать тиры |
| `test_unsynced_hard_imports.py::TestNoUndeliverableHardDependency::test_no_unsynced_file_hard_imports_spa_core` | 4 файла `docs/evidence/yield-evidence-01-2026-11-05/calc/{a,b,c,d}.py` жёстко импортируют `spa_core.trading_research`, а в прод не приедут НИ ОДНИМ механизмом |
| ~~`test_script_path_launch_imports.py`~~ | **ЗАКРЫТ циклом #1218**: `scripts/edge_risk_shape_adaptive_blend.py` не мог импортировать `spa_core` при запуске ПО ПУТИ; бутстрап взят из авторского коммита `92d095a7d` невлитой ветки, не выдуман. 1 failed → 10 passed |

Воспроизведено ДВАЖДЫ: в одноразовом worktree на 2fc564a0e и в отдельном чистом
дереве. Это не регрессия цикла и не окружение — состояние `main`.

Отдельно: **в `--json` вердикта контрольного прогона доступны 29 имён из 70**,
поэтому «есть ли эти четыре в красном наборе CI» — НЕ ИЗМЕРЕНО, и нулём это не
считается (имена берутся только из артефакта `report.json`).

## Что от тебя нужно

Это задача агенту, не владельцу. Порядок:

1. Сверить четыре имени с артефактом `report.json` последнего контрольного
   прогона — в красном наборе CI они или нет. Третий исход обязателен.
2. Чинить У ПИСАТЕЛЯ, а не дописыванием в базу храповика (инв. #16): у каждого
   из четырёх сторож называет рычаг прямо в сообщении.
3. `test_unsynced_hard_imports` решается одним из трёх названных способов
   (доставить файл · снять файл · убрать жёсткую зависимость); выбор ВТОРОГО и
   ТРЕТЬЕГО за агентом, выбор ПЕРВОГО задевает прод-дерево ⇒ владелец.

## Как понять, что готово

Прогон четырёх названных файлов на чистом `origin/main` даёт 0 failed, и ни
одна база храповика не выросла.

## Что будет после

Красный набор CI укоротится на четыре имени, и у следующего цикла станет меньше
шума при сличении дельты.
