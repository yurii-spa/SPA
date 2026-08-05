---
trackerStatus:
  type: inbox
title: "ADR-066 Фаза 1: сторож architecture_conformance (B1–B5) + positive controls"
status: new
source: nimbalyst
created: 2026-08-05
adr: ADR-066
phase: 1
---

spa_core/monitoring/architecture_conformance.py: fleet↔manifest в обе стороны, свежесть продуктов по SLO, замыкание потребления (consumer_required ⇒ потребитель+ресит), designed-дрейф, ролевые нарушения ADR-004. Семантика OK/UNCHECKED/WARN/CRITICAL, exit 0/1/2, старение слабых сигналов, data/architecture_conformance.json, алерт через push_policy. Тесты — репродукции находок аудита 2026-08-05 (реестр 19 дней, swarm_dwell вне реестра, io_* без потребителя). Launchd 6ч через deploy-gate. Приёмка: на текущем проде сторож КРАСНЫЙ ровно по находкам аудита. ADR-066 Контур B.
