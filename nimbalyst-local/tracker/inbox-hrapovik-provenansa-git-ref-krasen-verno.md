---
trackerStatus:
  type: inbox
title: "Храповик провенанса git-ref красен верно: предмет вырос на 28 площадок"
status: new
source: nimbalyst
created: 2026-11-04
priority: high
intake_kind: task
twin_key: "sha256:99d9895f06ba2cd88135112da31cd7eed87ff8c7b7cbd61f1a4aafd9529f2792"
---

## Что измерено (цикл #1029, 2026-11-04)

Храповик `spa_core/tests/test_python_git_ref_provenance.py` красен на `origin/main`
**верно**: предмет ВЫРОС на **28** площадок. Прибор
`scripts/python_git_ref_provenance.py --root . --baseline scripts/python_git_ref_provenance_baseline.json`
печатает их поимённо и выходит ненулевым.

Это НЕ бомба теста и НЕ ложное срабатывание: за время с заморозки базы в дерево
приехали 28 новых чтений git-ref (`origin/main`), у которых НЕ доказано, что
обновитель (`fetch`) исполнился до чтения. Четыре имени набора красны от одной
причины:

- `TestRatchet::test_real_tree_matches_the_frozen_baseline`
- `RegistryGovernance::test_an_intact_baseline_passes`
- `RegistryReactsToTheCensus::test_removing_an_unresolved_identity_reduces_the_debt`
- `RegistryReactsToTheCensus::test_the_unchanged_census_is_green`

Замер оси личности удалённого: `by_url=0` · `by_config=70` · `by_var=15` (НЕ ИЗМЕРЕНО);
**ДОКАЗАНО ПО ОБЕИМ ОСЯМ: 0 из 85**.

## Почему цикл #1029 это НЕ починил

Два пути, и оба вне одной правки:

1. **Дописать 28 имён в базу — ЗАПРЕЩЕНО** (инв. #16 и правило храповика: база может
   только уменьшаться). Это было бы гашение сторожа, а не починка.
2. **Загейтить 28 площадок** — правка ~12 production-модулей, среди них
   `spa_core/monitoring/card_acceptance.py` (8 площадок), `spa_core/studio_os/provenance.py`,
   `spa_core/monitoring/duplicate_subject_census.py`, `scripts/cio_acceptance_rollup.py`.
   Это отдельная работа с своей приёмкой, а не прицеп к чужому пушу.

## Первая работа

Разложить 28 по ПРИЧИНЕ, а не по файлу: сколько из них — «обновитель есть, но не
доминирует», сколько — «обновителя нет вовсе», сколько — `by_var` (аргумент двери не
разобран, то есть третий исход прибора, а не площадка). Только после разложения
становится видно, одна это починка или три.

## Как понять, что готово

`python3 scripts/python_git_ref_provenance.py --root . --baseline scripts/python_git_ref_provenance_baseline.json`
выходит 0, и ни одна строка базы не дописана (сверить `git diff` базы: только удаления).
