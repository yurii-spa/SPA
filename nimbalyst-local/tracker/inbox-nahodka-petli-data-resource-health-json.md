---
trackerStatus:
  type: inbox
title: "Находка петли: data/resource_health.json: consumer_required, но НИ ОДНОГО ресита потр"
status: new
source: nimbalyst
created: 2026-10-04
finding_key: "B3:no_consumption:data/resource_health.json"
---

Находка петли ADR-066 (architecture_conformance, WARN, подтверждена 2 прогонами подряд):

data/resource_health.json: consumer_required, но НИ ОДНОГО ресита потребления (ядро аудита 2026-08-05: отчёты в никуда)

Сделано = находка исчезает из отчёта источника при следующем прогоне (мост закроет карточку сам).

_finding_key: `B3:no_consumption:data/resource_health.json` · ADR-066_
