---
trackerStatus:
  type: agent-task
title: Брифинг печатает «все агенты в норме» под вердиктом WARNING и скрывает его причину
status: done
source: nimbalyst
created: 2026-08-01
priority: high
---

## Как найдено

Не воспроизводил намеренно. Цикл #75: очередь на origin пуста → мандат. Смотрел живой
`docs/SYSTEM_BRIEFING.md` (файл, который `CLAUDE.md` ОБЯЗЫВАЕТ читать в начале каждой сессии) и
увидел вердикт, противоречащий собственному объяснению.

## Что измерено (дословно, живой брифинг 2026-08-01 17:13 UTC)

```
## 🤖 Agent Health
⚠️ **WARNING** — 70 OK / 0 WARN / 0 CRIT  (of 70)  ·  snapshot 31m ago
_All agents nominal_
```

Вердикт `WARNING` — и тут же «_All agents nominal_» при `0 WARN / 0 CRIT`. Причина WARNING в
секции НЕ названа вообще. А в самом снимке `data/agent_health.json` она есть:

```json
"system_issues": [
  "fleet parity stale 507.9h (>26h) — drift guard not re-run",
  "capital-efficiency LAZY: 15% deployable capital idle at 0% — ~127bps/yr forgone ..."
]
```

## Почему это дефект, а не косметика

`agent_health_monitor.build_report`: `overall = _worst(system_status, *[статусы агентов])`, где
`system_status` поднимается до WARNING ИМЕННО из `system_issues`. То есть вердикт секции целиком
объясним — объяснение просто не печатается: `build_agents_section`
(`scripts/update_system_briefing.py`) строит текст ТОЛЬКО из `d["agents"]` и ключ `system_issues`
не читает НИ РАЗУ. Когда все агенты OK, а проблема системная, ветка `else` печатает
успокоительное «_All agents nominal_» — утверждение о том, чего секция не проверяла.

Это класс #29/#31/#35–#38/#40 (fail-OPEN: публикуется «всё в порядке» о непроверенном), но в
более вредной форме: тут не молчание, а **успокоение, прямо противоречащее вердикту в той же
строке**.

**Радиус измерен, а не предположен:** `fleet parity stale 507.9h` — это ~21 день. Сторож дрейфа
флота не перезапускался с ~11.07, WARNING висел всё это время, и ни один цикл его не заметил —
потому что в единственном файле, который все читают, причина невидима.

## Acceptance criteria

- при непустом `system_issues` секция печатает их ВЕРБАТИМ (не пересказ, не агрегат);
- «_All agents nominal_» невозможно напечатать при `overall != OK` (fail-CLOSED: если вердикт
  не-OK, а причин в снимке нет — так и написать, а не успокаивать);
- положительные контроли: при `overall=OK` и пустом `system_issues` секция байт-в-байт прежняя;
  per-agent problems печатаются как прежде; счётчики по-прежнему эхо снимка ±0;
- инвариант #16: ни один существующий ассерт не ослаблен (в частности
  `tests/test_health_surfaces_consistent.py:113` «All agents nominal»).

**Не входит:** пороги, эскалация, сам `agent_health_monitor` (его вердикт ПРАВИЛЬНЫЙ — врёт
только витрина), перезапуск сторожа дрейфа флота (launchd = домен владельца), RiskPolicy /
kill-switch / живой трек / `landing/**`.

## Результат (цикл #75, 2026-08-01)

**СДЕЛАНО.** `build_agents_section` печатает `system_issues` вербатим; «_All agents nominal_»
достижимо только при `overall == OK` (fail-CLOSED — не-OK вердикт без причин публикуется как
«cause NOT STATED»). Монитор, пороги, эскалация и счётчики НЕ тронуты — врала только витрина.

Проверка: +13 герметичных тестов (`tests/test_briefing_agent_health_reasons.py`), **9 из 13
красные на чистом origin**, 4 положительных контроля зелёные в обе стороны; соседние файлы
витрины 37 passed (ассерт «All agents nominal» сохранён); `tests/` 12 911 passed = ровно +13 при
1 предсуществующем падении; `spa_core/tests/` 90 684 / 0 failed (baseline #74 без изменений);
`--collect-only` ровно +13; mypy без новых ошибок; lint 163/0; живой read-only смоук.

Побочно (не входило в задачу, поэтому карточкой владельцу
`owner-decision-storozh-rashozhdeniya-flota-ne-zapuskals`): причина WARNING — сторож расхождения
флота — **не привязан ни к какому расписанию**, поэтому его WARNING не погаснет никогда.
