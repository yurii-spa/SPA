---
trackerStatus:
  type: inbox
title: "ADR-070.13: тревогу core-agent-down гасит agent_health"
status: done
source: nimbalyst
created: 2026-08-07
adr: ADR-070
---

По двум чистым снимкам подряд (решение владельца 2026-08-07, ADR-070 п.13)

---

## Закрытие (аудит очереди, 26.08)

Решено коммитом 8a9c826d1 (own-28): resolve('core_agent_down') зовёт только self_heal и только после чистого прогона (fail-closed на пустом снимке/окне) — тот же вопрос «кто гасит тревогу», другая реализация (self_heal вместо agent_health), закрыт по существу.
