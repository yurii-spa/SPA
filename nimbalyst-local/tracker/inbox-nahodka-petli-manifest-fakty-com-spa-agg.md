---
trackerStatus:
  type: inbox
title: "Находка петли: манифест ↔ факты: com.spa.aggressive_lab: schedule 'interval:86400s' →"
status: done
source: nimbalyst
created: 2026-09-02
finding_key: "B5:drift:com.spa.aggressive_lab"
status_trail:
  - "2026-09-03T11:46:13.734565+00:00 new -> done · queue.set_status"
---

Находка петли ADR-066 (architecture_conformance, WARN, подтверждена 2 прогонами подряд):

манифест ↔ факты: com.spa.aggressive_lab: schedule 'interval:86400s' → 'calendar:00:00,06:00,12:00,18:00'

Сделано = находка исчезает из отчёта источника при следующем прогоне (мост закроет карточку сам).

_finding_key: `B5:drift:com.spa.aggressive_lab` · ADR-066_
