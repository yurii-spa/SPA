---
trackerStatus:
  type: inbox
title: "Находка петли: data/candidate_registry.json: возраст 39.0ч > SLO 26ч (класс agent_reg"
status: done
source: nimbalyst
created: 2026-09-29
finding_key: "B2:stale:data/candidate_registry.json"
status_trail:
  - "2026-09-30T23:19:00.704620+00:00 new -> done · queue.set_status"
---

Находка петли ADR-066 (architecture_conformance, WARN, подтверждена 2 прогонами подряд):

data/candidate_registry.json: возраст 39.0ч > SLO 26ч (класс agent_registry: 19 дней молчаливого протухания)

Сделано = находка исчезает из отчёта источника при следующем прогоне (мост закроет карточку сам).

_finding_key: `B2:stale:data/candidate_registry.json` · ADR-066_
