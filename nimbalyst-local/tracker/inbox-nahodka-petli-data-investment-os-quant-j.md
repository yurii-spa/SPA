---
trackerStatus:
  type: inbox
title: "Находка петли: data/investment_os/quant.json: последний ресит старше бюджета потребле"
status: done
source: nimbalyst
created: 2026-10-20
finding_key: "B3:consumption_stale:data/investment_os/quant.json"
status_trail:
  - "2026-10-22T03:59:22.553873+00:00 new -> done · queue.set_status/closed_by:findings_bridge/evidence:finding B3:consumption_stale:data/investment_os/quant.json absent in the fresh report (ADR-066 C2)"
---

Находка петли ADR-066 (architecture_conformance, WARN, подтверждена 2 прогонами подряд):

data/investment_os/quant.json: последний ресит старше бюджета потребления 26ч — потребитель замолчал

Сделано = находка исчезает из отчёта источника при следующем прогоне (мост закроет карточку сам).

_finding_key: `B3:consumption_stale:data/investment_os/quant.json` · ADR-066_
