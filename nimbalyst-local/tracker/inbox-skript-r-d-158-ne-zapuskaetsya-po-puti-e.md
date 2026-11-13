---
trackerStatus:
  type: inbox
title: "Скрипт R&D #158 не запускается по пути: edge_risk_shape_adaptive_blend без бутстрапа sys.path красит храповик path-launch на main"
status: new
source: nimbalyst
created: 2026-11-13
priority: medium
found_by: cycle-1119
twin_key: "sha256:427e603a234a8d2dfb5e31c28c5d7b90c73987a408927e230190a36e3dd29322"
---

## Что случилось

Храповик `spa_core/tests/test_script_path_launch_imports.py::test_no_new_script_breaks_when_launched_by_path` КРАСЕН на чистом
`origin/main` 5159151f0 (воспроизведено циклом #1119 в отдельном worktree, не только в CI): он называет
`scripts/edge_risk_shape_adaptive_blend.py` из R&D-доставки 5159151f0 (novel-edge-rnd, 13.11, #157 IOB + #158 CFH).

Скрипт ввозит пакет репозитория (`from spa_core.strategy_lab.aggressive_lab…`, строки 42–43) БЕЗ бутстрапа `sys.path`
выше первого импорта. Рука зовёт скрипт ПО ПУТИ (`python3 scripts/edge_risk_shape_adaptive_blend.py`), и `sys.path[0]`
у такого процесса — каталог `scripts/`, а не корень: `ModuleNotFoundError: spa_core` — ровно авария 12.09 (ADR-347)
и форма, которую этот же цикл закрывал у 11 скриптов транша двери (ADR-1000 § 2.1).

## Что сделать

1. Поставить бутстрап корня репозитория ВЫШЕ первого `from spa_core…` (образец — ADR-1000: `_SPA_REPO_ROOT =
   str(Path(__file__).resolve().parents[1]); if … not in sys.path: sys.path.insert(0, …)`), либо убрать импорт пакета, если
   скрипт обязан быть самодостаточным (прочие `edge_*` — stdlib-only).
2. Прогнать `spa_core/tests/test_script_path_launch_imports.py` — обязан зеленеть без правки `path_launch_import_baseline.json`
   (дописывать базу ЗАПРЕЩЕНО, инв. #16).
3. Проба приёмки — назвать из реестра `card_acceptance.PROBES` ДО взятия в работу (`.claude/rules/acceptance.md`).

## Как понять, что готово

Храповик зелёный на `origin/main` без изменения базы; скрипт запускается по пути из чужого каталога (`cd /tmp && python3 <abs>/scripts/edge_risk_shape_adaptive_blend.py --help`).

## Контекст

Не предмет владельца (ADR-285): кода R&D, капитал не двигает. Найдено пакетом «связанных» тестов цикла #1119 (журнал W46 #1119).
