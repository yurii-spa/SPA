---
trackerStatus:
  type: agent
title: Переселить 13 оптимизаторов в советники аллокатора (поток 1 own-27)
status: backlog
source: own-27-decision-2026-08-04
created: 2026-08-04
priority: medium
domain: analytics relocation (advisory; risk-gate НЕ трогать)
---

13 модулей-оптимизаторов из бывшего Tier-B подключить advisory-входом в data/allocation_rationale.json (shadow-триггер уже пишет его каждый цикл). Advisory никогда не гейтит. Список и назначение: docs/analytics_relocation_plan_2026-08-04.md, поток 1.

## Как понять, что готово
Модули потока дают видимый выход в своём новом доме (rationale/отчёт/série-скоры), прогоны
тестов зелёные, ни один тест не ослаблен (инв.16).
