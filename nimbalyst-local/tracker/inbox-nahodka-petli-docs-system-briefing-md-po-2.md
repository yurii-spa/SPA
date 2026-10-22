---
trackerStatus:
  type: inbox
title: "Находка петли: docs/SYSTEM_BRIEFING.md: последний ресит старше бюджета потребления 26"
status: done
source: nimbalyst
created: 2026-10-20
finding_key: "B3:consumption_stale:docs/SYSTEM_BRIEFING.md"
status_trail:
  - "2026-10-22T03:59:25.371531+00:00 new -> done · queue.set_status/closed_by:findings_bridge/evidence:finding B3:consumption_stale:docs/SYSTEM_BRIEFING.md absent in the fresh report (ADR-066 C2)"
---

Находка петли ADR-066 (architecture_conformance, WARN, подтверждена 2 прогонами подряд):

docs/SYSTEM_BRIEFING.md: последний ресит старше бюджета потребления 26ч — потребитель замолчал

Сделано = находка исчезает из отчёта источника при следующем прогоне (мост закроет карточку сам).

_finding_key: `B3:consumption_stale:docs/SYSTEM_BRIEFING.md` · ADR-066_
