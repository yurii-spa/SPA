---
trackerStatus:
  type: inbox
title: "Находка петли: data/audit_trail_rate_input_coverage.json: возраст 9.0ч > SLO 7ч (клас"
status: done
source: nimbalyst
created: 2026-10-16
finding_key: "B2:stale:data/audit_trail_rate_input_coverage.json"
status_trail:
  - "2026-10-16T15:44:15.865641+00:00 new -> done · queue.set_status/closed_by:findings_bridge/evidence:finding B2:stale:data/audit_trail_rate_input_coverage.json absent in the fresh report (ADR-066 C2)"
---

Находка петли ADR-066 (architecture_conformance, WARN, подтверждена 2 прогонами подряд):

data/audit_trail_rate_input_coverage.json: возраст 9.0ч > SLO 7ч (класс agent_registry: 19 дней молчаливого протухания)

Сделано = находка исчезает из отчёта источника при следующем прогоне (мост закроет карточку сам).

_finding_key: `B2:stale:data/audit_trail_rate_input_coverage.json` · ADR-066_
