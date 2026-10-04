---
trackerStatus:
  type: inbox
title: "Находка петли: data/investment_os/liquidity.json: возраст 36.0ч > SLO 26ч (класс agen"
status: done
source: nimbalyst
created: 2026-10-03
finding_key: "B2:stale:data/investment_os/liquidity.json"
status_trail:
  - "2026-10-04T07:28:52.320555+00:00 new -> done · queue.set_status/closed_by:findings_bridge/evidence:finding B2:stale:data/investment_os/liquidity.json absent in the fresh report (ADR-066 C2)"
---

Находка петли ADR-066 (architecture_conformance, WARN, подтверждена 2 прогонами подряд):

data/investment_os/liquidity.json: возраст 36.0ч > SLO 26ч (класс agent_registry: 19 дней молчаливого протухания)

Сделано = находка исчезает из отчёта источника при следующем прогоне (мост закроет карточку сам).

_finding_key: `B2:stale:data/investment_os/liquidity.json` · ADR-066_
