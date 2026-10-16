---
trackerStatus:
  type: inbox
title: "Находка петли: data/asset_registry_gap_price.json: возраст 9.0ч > SLO 7ч (класс agent"
status: done
source: nimbalyst
created: 2026-10-16
finding_key: "B2:stale:data/asset_registry_gap_price.json"
status_trail:
  - "2026-10-16T15:44:11.386061+00:00 new -> done · queue.set_status/closed_by:findings_bridge/evidence:finding B2:stale:data/asset_registry_gap_price.json absent in the fresh report (ADR-066 C2)"
---

Находка петли ADR-066 (architecture_conformance, WARN, подтверждена 2 прогонами подряд):

data/asset_registry_gap_price.json: возраст 9.0ч > SLO 7ч (класс agent_registry: 19 дней молчаливого протухания)

Сделано = находка исчезает из отчёта источника при следующем прогоне (мост закроет карточку сам).

_finding_key: `B2:stale:data/asset_registry_gap_price.json` · ADR-066_
