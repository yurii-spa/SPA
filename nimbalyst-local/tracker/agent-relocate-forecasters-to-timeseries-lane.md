---
trackerStatus:
  type: agent
title: Линия время-рядов для 18 форкастеров (поток 3 own-27)
status: backlog
source: own-27-decision-2026-08-04
created: 2026-08-04
priority: medium
domain: analytics relocation (advisory; risk-gate НЕ трогать)
---

Построить фид живых APY-рядов из data/historical_apy* (оси дат НЕ совпадают — выравнивать по дате) и подключить 18 форкастеров/компараторов. Разблокирует также часть 140 непроводимых Tier-B и 38 dormant-by-design. Список: docs/analytics_relocation_plan_2026-08-04.md, поток 3.

## Как понять, что готово
Модули потока дают видимый выход в своём новом доме (rationale/отчёт/série-скоры), прогоны
тестов зелёные, ни один тест не ослаблен (инв.16).
