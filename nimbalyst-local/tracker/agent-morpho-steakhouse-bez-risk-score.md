---
trackerStatus:
  type: agent-task
title: "morpho_steakhouse — 40 % книги — отсутствует в реестре риск-скоров, и три теста краснеют на main из-за этого"
status: done
source: session-2026-08-08-autopilot
created: 2026-08-08
priority: high
tags: [risk, registry, coverage, ci]
---

## Что нашлось

Контрольный прогон на **чистом `origin/main`** (не на моих правках) даёт три стабильных падения:

```
test_every_registry_protocol_has_a_risk_score  → adapters with no risk_score: ['morpho_steakhouse']
test_registry_is_not_empty_and_expected_size   → 35 скоров при 36 адаптерах в реестре
test_exported_json_snapshot_is_consistent      → morpho_steakhouse missing from exported JSON
```

**Почему это не косметика.** `morpho_steakhouse` — **крупнейшая позиция книги: $40 000, 40 %
капитала, ровно в потолке T1**. Протокол, в который вложено 40 % денег, не имеет записи в
`PROTOCOL_RISK_SCORES` и не попадает в экспортируемый JSON-снимок риск-оценок.

Это не «упавший тест». Это ровно тот класс, который разбирался весь день: сторож честно называет
дыру, а дыра стоит на самом дорогом месте книги.

## Что проверить прежде, чем чинить

1. **Читает ли money-path эти скоры и что он делает при отсутствии записи.** Если аллокатор при
   пропуске молча трактует протокол как «средний» — это подстановка того же класса, что мы
   сегодня вычищали из адаптеров, только этажом выше. Если fail-CLOSED — дыра ограничена
   отчётностью.
2. **Почему запись пропала.** Скор мог никогда не заводиться (протокол добавлен позже реестра
   скоров) либо выпасть при регенерации. Это разные починки.
3. Не спрятана ли та же дыра у соседей: сравнить множества `ADAPTER_REGISTRY` и
   `PROTOCOL_RISK_SCORES` целиком, а не только по счётчику.

## Чего НЕ делать

Не дописывать скор «по аналогии с Aave», чтобы покрасить тест зелёным. Риск-оценка крупнейшей
позиции — это утверждение о риске 40 % капитала; она либо выведена по той же методике, что
остальные, либо её нет и это надо назвать вслух.

## Закрыто 16.08

Посылка перепроверена на этом дереве (волна 0 триажа `docs/BACKLOG_TRIAGE_2026-08-16.md`),
а не по журналу:

- `spa_core/risk/protocol_risk_map.py:97` — запись `"morpho_steakhouse": {"tier": "T2",
  "risk_score": 0.30, ...}` присутствует, комментарий ссылается на ADR-070 п.6
  («один vault — один риск», оценка `morpho_blue`);
- `data/protocol_risk_map.json` — ключ `morpho_steakhouse` в экспортированном снимке ЕСТЬ;
- `python3 -m pytest tests/test_risk_scoring_completeness.py -q` → **10 passed** (0.24s).
  Все три теста, красневшие на чистом `origin/main` по замеру цикла #167
  (`test_every_registry_protocol_has_a_risk_score`, `test_registry_is_not_empty_and_expected_size`,
  `test_exported_json_snapshot_is_consistent`) — зелёные.

Покрывает также схлопнутую сюда `inbox-adr-070-6-morpho-steakhouse-otsenka-morp` (кластер К1).
