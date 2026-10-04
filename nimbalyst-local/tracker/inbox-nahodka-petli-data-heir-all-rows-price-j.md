---
trackerStatus:
  type: inbox
title: "Находка петли: data/heir_all_rows_price.json: возраст 13.2ч > SLO 7ч (класс agent_reg"
status: done
source: nimbalyst
created: 2026-10-03
finding_key: "B2:stale:data/heir_all_rows_price.json"
status_trail:
  - "2026-10-04T15:23:41.623429+00:00 new -> done · queue.set_status/closed_by:findings_bridge/evidence:finding B2:stale:data/heir_all_rows_price.json absent in the fresh report (ADR-066 C2)"
---

Находка петли ADR-066 (architecture_conformance, WARN, подтверждена 2 прогонами подряд):

data/heir_all_rows_price.json: возраст 13.2ч > SLO 7ч (класс agent_registry: 19 дней молчаливого протухания)

Сделано = находка исчезает из отчёта источника при следующем прогоне (мост закроет карточку сам).

_finding_key: `B2:stale:data/heir_all_rows_price.json` · ADR-066_
