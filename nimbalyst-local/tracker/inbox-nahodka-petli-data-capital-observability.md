---
trackerStatus:
  type: inbox
title: "Находка петли: data/capital_observability_history.json: возраст 8.3ч > SLO 7ч (класс "
status: done
source: nimbalyst
created: 2026-10-14
finding_key: "B2:stale:data/capital_observability_history.json"
status_trail:
  - "2026-10-14T09:16:37.979649+00:00 new -> done · queue.set_status/closed_by:owner_queue.intake/history_check/evidence:duplicate of existing work (verdict IN_PROGRESS): Карточка ровно на эту находку уже есть и открыта: `inbox-nahodka-petli-data-capital-observability.md` (status `new`, создана 2026-10-14, `finding_key:"
---

Находка петли ADR-066 (architecture_conformance, WARN, подтверждена 2 прогонами подряд):

data/capital_observability_history.json: возраст 8.3ч > SLO 7ч (класс agent_registry: 19 дней молчаливого протухания)

Сделано = находка исчезает из отчёта источника при следующем прогоне (мост закроет карточку сам).

_finding_key: `B2:stale:data/capital_observability_history.json` · ADR-066_
