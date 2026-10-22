---
trackerStatus:
  type: inbox
title: "Находка петли: data/investment_os/onchain.json: последний ресит старше бюджета потреб"
status: done
source: nimbalyst
created: 2026-10-20
finding_key: "B3:consumption_stale:data/investment_os/onchain.json"
status_trail:
  - "2026-10-22T03:59:19.837832+00:00 new -> done · queue.set_status/closed_by:findings_bridge/evidence:finding B3:consumption_stale:data/investment_os/onchain.json absent in the fresh report (ADR-066 C2)"
---

Находка петли ADR-066 (architecture_conformance, WARN, подтверждена 2 прогонами подряд):

data/investment_os/onchain.json: последний ресит старше бюджета потребления 26ч — потребитель замолчал

Сделано = находка исчезает из отчёта источника при следующем прогоне (мост закроет карточку сам).

_finding_key: `B3:consumption_stale:data/investment_os/onchain.json` · ADR-066_
