---
trackerStatus:
  type: inbox
title: "Находка петли: data/candidate_registry.json: активный артефакт отсутствует на диске —"
status: done
source: nimbalyst
created: 2026-09-15
finding_key: "B2:missing:data/candidate_registry.json"
status_trail:
  - "2026-10-04T20:42:08.407689+00:00 new -> done · queue.set_status/closed_by:findings_bridge/evidence:finding B2:missing:data/candidate_registry.json absent in the fresh report (ADR-066 C2) · cycle-16566"
---

Находка петли ADR-066 (architecture_conformance, WARN, подтверждена 2 прогонами подряд):

data/candidate_registry.json: активный артефакт отсутствует на диске — артефакт не объявлен продуктом ни одной переписи бегуна ⇒ «отработал ли ЕГО производитель» НЕ ИЗМЕРЕНО; подставлять сюда чужого бегуна нельзя

Сделано = находка исчезает из отчёта источника при следующем прогоне (мост закроет карточку сам).

_finding_key: `B2:missing:data/candidate_registry.json` · ADR-066_
