---
trackerStatus:
  type: inbox
title: "Находка петли: data/asset_registry_gap_price.json: возраст 15.9ч > SLO 7ч (класс agen"
status: done
source: nimbalyst
created: 2026-09-27
finding_key: "B2:stale:data/asset_registry_gap_price.json"
status_trail:
  - "2026-09-28T00:12:28.654624+00:00 new -> done · queue.set_status"
---

Находка петли ADR-066 (architecture_conformance, WARN, подтверждена 2 прогонами подряд):

data/asset_registry_gap_price.json: возраст 15.9ч > SLO 7ч (класс agent_registry: 19 дней молчаливого протухания)

Сделано = находка исчезает из отчёта источника при следующем прогоне (мост закроет карточку сам).

_finding_key: `B2:stale:data/asset_registry_gap_price.json` · ADR-066_
