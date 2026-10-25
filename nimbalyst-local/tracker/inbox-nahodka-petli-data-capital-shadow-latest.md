---
trackerStatus:
  type: inbox
title: "Находка петли: data/capital_shadow/latest.json: consumer_required, но НИ ОДНОГО ресит"
status: done
source: nimbalyst
created: 2026-10-04
finding_key: "B3:no_consumption:data/capital_shadow/latest.json"
status_trail:
  - "2026-10-06T22:53:50.933362+00:00 new -> done · queue.set_status/closed_by:owner_queue.intake/history_check/evidence:duplicate of existing work (verdict IN_PROGRESS): Карточка ровно про эту находку уже лежит в очереди с 04.10 — `nimbalyst-local/tracker/inbox-nahodka-petli-data-capital-shadow-latest.md`, тот же `find"
---

Находка петли ADR-066 (architecture_conformance, WARN, подтверждена 2 прогонами подряд):

data/capital_shadow/latest.json: consumer_required, но НИ ОДНОГО ресита потребления (ядро аудита 2026-08-05: отчёты в никуда)

Сделано = находка исчезает из отчёта источника при следующем прогоне (мост закроет карточку сам).

_finding_key: `B3:no_consumption:data/capital_shadow/latest.json` · ADR-066_
