---
trackerStatus:
  type: inbox
title: "Находка петли: data/apy_composition.json: возраст 8.9ч > SLO 7ч (класс agent_registry"
status: done
source: nimbalyst
created: 2026-10-16
finding_key: "B2:stale:data/apy_composition.json"
status_trail:
  - "2026-10-16T15:44:00.825527+00:00 new -> done · queue.set_status/closed_by:findings_bridge/evidence:finding B2:stale:data/apy_composition.json absent in the fresh report (ADR-066 C2)"
---

Находка петли ADR-066 (architecture_conformance, WARN, подтверждена 2 прогонами подряд):

data/apy_composition.json: возраст 8.9ч > SLO 7ч (класс agent_registry: 19 дней молчаливого протухания)

Сделано = находка исчезает из отчёта источника при следующем прогоне (мост закроет карточку сам).

_finding_key: `B2:stale:data/apy_composition.json` · ADR-066_
