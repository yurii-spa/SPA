---
trackerStatus:
  type: inbox
title: "Находка петли: data/candidate_discovery_status.json: возраст 39.0ч > SLO 26ч (класс a"
status: done
source: nimbalyst
created: 2026-09-29
finding_key: "B2:stale:data/candidate_discovery_status.json"
status_trail:
  - "2026-09-30T23:18:58.213334+00:00 new -> done · queue.set_status"
---

Находка петли ADR-066 (architecture_conformance, WARN, подтверждена 2 прогонами подряд):

data/candidate_discovery_status.json: возраст 39.0ч > SLO 26ч (класс agent_registry: 19 дней молчаливого протухания)

Сделано = находка исчезает из отчёта источника при следующем прогоне (мост закроет карточку сам).

_finding_key: `B2:stale:data/candidate_discovery_status.json` · ADR-066_
