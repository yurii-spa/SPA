---
trackerStatus:
  type: inbox
title: "Храповик литеральных дат КРАСНЫЙ на main: test_act_day_recovery.py вошёл в закрытый класс (замер #602)"
status: new
source: nimbalyst
created: 2026-09-14
---

## Находка (замер 2026-09-14, цикл #602)

Храповик литеральных дат (`spa_core/tests/test_frozen_date_ratchet.py::test_no_new_file_joins_the_frozen_date_class`)
**КРАСНЫЙ на `origin/main`** — измерено дифференциально, на чистом контроле того же
sha `427be46cb`, прогнанном ОДНОВРЕМЕННО с субъектом:

```
E  AssertionError: New test file(s) pin a literal date next to a freshness concept:
E      test_act_day_recovery.py
```

Файл `spa_core/tests/test_act_day_recovery.py` доставлен циклом #601 (ADR-383) и вошёл в
закрытый класс: литеральная дата рядом с понятием свежести, без пометки `FROZEN-DATE-OK`
и без инъекции часов. Вклад цикла #602 в это падение **нулевой** — файл красный и без
моих правок.

## Почему это не чинится прицепом

Инвариант #16: намеренная правка чужого теста допустима только с обоснованием и записью,
а «покрасить зелёным» дописыванием в `frozen_date_baseline.json` **запрещено** правилом
`.claude/rules/deployment.md` прямым текстом. Правильная починка — одна из двух:
инъекция часов в `test_act_day_recovery.py` (преференция №1 правила) либо пометка
`# FROZEN-DATE-OK: <причина>`, если дата там ЯВЛЯЕТСЯ предметом (в ADR-383 дата
2026-09-11 — исторический инцидент, так что вторая ветка вероятна). Решать это должен
тот, кто знает замысел теста, а не мимоходом сосед.

## Приёмка

`SPA_ENV=ci python3 -m pytest spa_core/tests/test_frozen_date_ratchet.py -q` — зелено,
и `test_act_day_recovery.py` не появляется в списке новых членов класса. Пометка, если
она будет выбрана, обязана нести ПРИЧИНУ: голый маркер храповик отвергает сам.
