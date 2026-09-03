---
trackerStatus:
  type: inbox
title: "Находка петли: манифест ↔ факты: com.spa.io_chief_investment: schedule 'interval:300s"
status: done
source: nimbalyst
created: 2026-09-02
finding_key: "B5:drift:com.spa.io_chief_investment"
status_trail:
  - "2026-09-03T11:46:21.311471+00:00 new -> done · queue.set_status"
---

Находка петли ADR-066 (architecture_conformance, WARN, подтверждена 2 прогонами подряд):

манифест ↔ факты: com.spa.io_chief_investment: schedule 'interval:300s' → 'interval:3600s'

Сделано = находка исчезает из отчёта источника при следующем прогоне (мост закроет карточку сам).

_finding_key: `B5:drift:com.spa.io_chief_investment` · ADR-066_
