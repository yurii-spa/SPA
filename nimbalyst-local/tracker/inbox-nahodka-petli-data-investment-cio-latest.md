---
trackerStatus:
  type: inbox
title: "Находка петли: data/investment_cio/latest.json: consumer_required, но НИ ОДНОГО ресит"
status: done
source: nimbalyst
created: 2026-10-04
finding_key: "B3:no_consumption:data/investment_cio/latest.json"
status_trail:
  - "2026-10-04T20:42:08.794914+00:00 new -> done · queue.set_status/closed_by:findings_bridge/evidence:finding B3:no_consumption:data/investment_cio/latest.json absent in the fresh report (ADR-066 C2) · cycle-16566"
---

Находка петли ADR-066 (architecture_conformance, WARN, подтверждена 2 прогонами подряд):

data/investment_cio/latest.json: consumer_required, но НИ ОДНОГО ресита потребления (ядро аудита 2026-08-05: отчёты в никуда)

Сделано = находка исчезает из отчёта источника при следующем прогоне (мост закроет карточку сам).

_finding_key: `B3:no_consumption:data/investment_cio/latest.json` · ADR-066_
