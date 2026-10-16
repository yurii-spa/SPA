---
trackerStatus:
  type: inbox
title: Храповик литеральных дат КРАСНЫЙ на origin/main — test_cockpit_dispatch.py вошёл в закрытый класс
status: new
created: 2026-10-16
---

## Что измерено (цикл #884, 2026-10-16)

На ЧИСТОЙ вершине `origin/main` (проверено в отдельном дереве, ни одного своего файла):

```
FAILED spa_core/tests/test_frozen_date_ratchet.py::test_no_new_file_joins_the_frozen_date_class
  assert not ['test_cockpit_dispatch.py']
  New test file(s) pin a literal date next to a freshness concept
```

Файл `spa_core/tests/test_cockpit_dispatch.py` приехал доставкой 16.10 (ARB раунд 5, п. 2/4,
`e46f89633`) и закрепил литеральную дату рядом с понятием свежести. Храповик
(`.claude/rules/deployment.md`, раздел «Время в тестах») запрещает такому файлу входить в класс:
бомба замедленного действия — тест упадёт просто от того, что сдвинулся календарь, по причине,
не имеющей отношения к проверяемому поведению.

## Что НЕ делать

**Дописывать файл в `spa_core/tests/frozen_date_baseline.json` ЗАПРЕЩЕНО** — база двигается
только вниз (инв. #16, то же правило у `design_status_baseline.json`,
`site_numbers_baseline.json`, `inbox_acceptance_baseline.json`). Это ровно то, ради чего
храповик существует.

## Что делать

Чинить фикстуру в порядке предпочтения из правила:

1. **время — вход:** функция, судящая о свежести, принимает `now` (умолчание — реальные часы);
   тест передаёт фиксированный `now` И фиксированные отметки — обе стороны закреплены;
2относительные отметки `spa_core/tests/_freshness.py::ts(hours_ago=N)`, если часы
   инъектировать нельзя;
3. литеральная дата — только если сама дата является ПРЕДМЕТОМ, и тогда пометка
   `# FROZEN-DATE-OK: <причина>`. Причина `injected-clock` **сверяется с кодом** по AST
   (`test_injected_clock_claim.py`) — записка не есть инъекция.

## Критерий приёмки

Объявляет берущая сессия. Предмет: `test_frozen_date_ratchet.py::test_no_new_file_joins_the_frozen_date_class`
зелёный на чистой вершине БЕЗ пополнения базы (`git diff` по `frozen_date_baseline.json` пуст),
и `test_injected_clock_claim.py` подтверждает причину, если выбран приём №3.

## Откуда

Цикл #884 (ADR-769). Красное — ЧУЖОЕ: ни один файл этого цикла в находке не назван, и она
воспроизводится на чистой вершине. Прицепом не починено намеренно (инв. #16: правка чужого
теста без разбора его предмета — то самое молчаливое ослабление). Рядом живёт ВТОРОЙ чужой
красный той же батареи, уже окарточенный:
`inbox-ci-lite-gonyaet-pytest-bez-istorii-repoz` (`new` с 08.10, `ci-lite.yml` гоняет pytest
без `fetch-depth: 0`).
