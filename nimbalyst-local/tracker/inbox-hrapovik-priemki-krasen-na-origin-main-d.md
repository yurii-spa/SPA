---
trackerStatus:
  type: inbox
title: "Храповик приёмки КРАСЕН на origin/main: две карточки закрыты без машинного критерия"
status: new
source: nimbalyst
created: 2026-10-25
---

## Что измерено (цикл #933, 25.10)

Храповик `spa_core/tests/test_inbox_acceptance_ratchet.py::test_no_new_card_is_in_work_without_a_criterion`
**КРАСЕН на чистом `origin/main`** (замер на `06d319511`). Это ЗАМЕР дерева, а не
находка моего цикла: рабочее дерево несло ровно три изменённых пути
(`git status --porcelain`: `scripts/cio_acceptance_rollup.py`,
`spa_core/tests/test_s49_unmeasured_is_classed.py`, `docs/mutations/ADR-810.json`),
ни один из них не карточка — значит ВХОДЫ этого теста байт в байт равны origin.

Нарушителей **два**, оба закрыты `done` 2026-10-03 без машинного критерия приёмки:

```
inbox-hrapovik-zamorozhennyh-dat-krasen-na-chi.md
inbox-neprimenennyi-otvet-vladeltsa-1-adresat-2.md
```

## Чем это НЕ является

Прошлый экземпляр того же класса (`inbox-hrapovik-priemki-krasen-na-ispravnom-sos`,
ADR-501, цикл #627) был про ДРУГОЕ: там храповик читал законное освобождение
`carried_to` как дефект, то есть краснел на ИСПРАВНОМ состоянии. Здесь состояние
неисправно по существу: две карточки действительно закрыты прозой, без мерки.

## Что надо сделать

Объявить обеим карточкам пробу из реестра `card_acceptance.PROBES` — ту, что мерит
ИСХОД, ради которого карточка заводилась, — либо, если исход уже недостижим и
карточка закрыта по другой причине, назвать эту причину формой, которую храповик
умеет читать (`carried_to=<существующий путь>`).

**Дописывать файлы в `scripts/inbox_acceptance_baseline.json` ЗАПРЕЩЕНО** (инв. #16):
база только убывает, и гашение падения дописыванием есть ровно тот дефект, ради
которого храповик написан.

## Как понять, что готово

`SPA_ENV=ci python3 -m pytest spa_core/tests/test_inbox_acceptance_ratchet.py -q`
зелен на чистом `origin/main`, и число в базе НЕ выросло.

## Откуда взялось

Заказ G810 п. 4 (ADR-810, цикл #933). Полный разбор — в журнале `docs/journal/2026-W43.md`,
цикл #933.
