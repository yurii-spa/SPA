---
trackerStatus:
  type: agent
title: Переселить 9 трекеров в слой отчётности (поток 2 own-27)
status: backlog
source: own-27-decision-2026-08-04
created: 2026-08-04
priority: medium
domain: analytics relocation (advisory; risk-gate НЕ трогать)
---

9 трекеров/отчётников из бывшего Tier-B подключить секциями в пост-цикловый analytics_runner (MP-104) и/или дневной дайджест. Список: docs/analytics_relocation_plan_2026-08-04.md, поток 2.

## Как понять, что готово
Модули потока дают видимый выход в своём новом доме (rationale/отчёт/série-скоры), прогоны
тестов зелёные, ни один тест не ослаблен (инв.16).
