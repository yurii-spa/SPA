---
trackerStatus:
  type: inbox
title: "Находка петли: data/unobserved_turnover_dependence.json: возраст 13.0ч > SLO 7ч (клас"
status: done
source: nimbalyst
created: 2026-09-14
finding_key: "B2:stale:data/unobserved_turnover_dependence.json"
status_trail:
  - "2026-09-14T15:20:50.477558+00:00 new -> done · queue.set_status"
---

Находка петли ADR-066 (architecture_conformance, WARN, подтверждена 2 прогонами подряд):

data/unobserved_turnover_dependence.json: возраст 13.0ч > SLO 7ч (класс agent_registry: 19 дней молчаливого протухания)

Сделано = находка исчезает из отчёта источника при следующем прогоне (мост закроет карточку сам).

_finding_key: `B2:stale:data/unobserved_turnover_dependence.json` · ADR-066_
