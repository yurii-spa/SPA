---
trackerStatus:
  type: inbox
title: "Находка петли: data/resource_health.json: consumer_required, но НИ ОДНОГО ресита потр"
status: done
source: nimbalyst
created: 2026-10-04
finding_key: "B3:no_consumption:data/resource_health.json"
status_trail:
  - "2026-10-04T20:42:09.201604+00:00 new -> done · queue.set_status/closed_by:findings_bridge/evidence:finding B3:no_consumption:data/resource_health.json absent in the fresh report (ADR-066 C2) · cycle-16566"
---

Находка петли ADR-066 (architecture_conformance, WARN, подтверждена 2 прогонами подряд):

data/resource_health.json: consumer_required, но НИ ОДНОГО ресита потребления (ядро аудита 2026-08-05: отчёты в никуда)

Сделано = находка исчезает из отчёта источника при следующем прогоне (мост закроет карточку сам).

_finding_key: `B3:no_consumption:data/resource_health.json` · ADR-066_
