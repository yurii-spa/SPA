---
trackerStatus:
  type: inbox
title: "Находка петли: data/journal_population_backfill.json: активный артефакт отсутствует н"
status: done
source: nimbalyst
created: 2026-09-11
finding_key: "B2:missing:data/journal_population_backfill.json"
status_trail:
  - "2026-09-12T02:10:31.648701+00:00 new -> done · queue.set_status"
---

Находка петли ADR-066 (architecture_conformance, WARN, подтверждена 2 прогонами подряд):

data/journal_population_backfill.json: активный артефакт отсутствует на диске — производитель spa_core/monitoring/journal_population_backfill.py назван в составе ступени бегуна (findings_bridge_report.json)

Сделано = находка исчезает из отчёта источника при следующем прогоне (мост закроет карточку сам).

_finding_key: `B2:missing:data/journal_population_backfill.json` · ADR-066_
