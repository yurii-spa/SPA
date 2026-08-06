---
trackerStatus:
  type: agent-task
title: "Два предсуществующих красных теста на main: дрейф манифеста morning_digest и храповик литеральных дат"
status: backlog
source: session-2026-08-06-cycle125
created: 2026-08-06
priority: medium
---

## Находка

На `origin/main` **два падающих теста, оба предсуществующие** — измерено дважды: на чистом
чекауте `origin/main` до работ цикла #125 (`b27cc0d1f`) и после (`0a9a6de3d`), наборы падений
совпадают пофамильно.

**1. `test_architecture_manifest.py::test_generator_check_passes_on_this_machine_or_skips`**
`architecture/manifest.json` не знает plist-полей агента `com.spa.morning_digest`:
`plist_source`, `schedule`, `program` — все три `None`, при том что `launchd/com.spa.morning_digest.plist`
лежит в репозитории. `build_architecture_manifest.py` честно возвращает 3 дрейфа и exit 2.
Сторож B5 этот дрейф ВИДИТ (проверено: `_manifest_drift_problems()` возвращает его), то есть
находка дойдёт и до карточки моста — но красный тест на main остаётся красным до починки.
В CI тест скипается (нет `~/Library/LaunchAgents/com.spa.*`), поэтому он краснит только на проде.

**2. `test_frozen_date_ratchet.py::test_no_new_file_joins_the_frozen_date_class`**
В класс «литеральная дата рядом с понятием свежести» вошёл новый файл —
`spa_core/tests/test_consumption_receipts.py` (ADR-066 Фаза 2). Храповик ровно для этого и
написан: база может ТОЛЬКО уменьшаться.

## Что сделать

1. Манифест: перегенерировать механические поля (`build_architecture_manifest.py --write`) —
   курация при этом не трогается. **Осторожно:** после этого `morning_digest` получит
   `plist_source: repo:...` ⇒ `reboot_safe: false`, и сторож честно заведёт находку «не переживёт
   ребут». Это верно и полезно, но появится новая карточка — знать заранее.
2. Храповик: **починить фикстуру** в `test_consumption_receipts.py` — инъектировать часы
   (`now=`) либо взять относительные отметки `spa_core/tests/_freshness.py::ts(hours_ago=N)`.
   **Добавлять файл в `frozen_date_baseline.json` ЗАПРЕЩЕНО** — база только уменьшается
   (`.claude/rules/deployment.md`).

## Acceptance

- оба теста зелёные на прод-хосте, и ни один другой тест не изменён ради этого;
- база храповика не выросла ни на строку;
- если починка манифеста породила новую находку сторожа — она названа, а не заглушена.

## Почему не сделал сразу

Цикл #125 держал другую карточку (ADR-066 Фаза 3), а `--write` меняет курацию агента, которого
я не изучал. Молча чинить сторожа, который краснеет на ВЕРНОЕ состояние, правило запрещает.
