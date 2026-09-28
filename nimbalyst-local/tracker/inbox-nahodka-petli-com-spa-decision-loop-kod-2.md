---
trackerStatus:
  type: inbox
title: "Находка петли: com.spa.decision_loop: код и манифест называют РАЗНЫЙ продукт (только "
status: new
source: nimbalyst
created: 2026-09-28
finding_key: "B7:manifest_parity:com.spa.decision_loop"
---

Находка петли ADR-066 (architecture_conformance, WARN, подтверждена 2 прогонами подряд):

com.spa.decision_loop: код и манифест называют РАЗНЫЙ продукт (только в объявлении: data/duplicate_subject_census.json; только в манифесте: —) — артефакт объявлен кодом, но манифест его не знает — он без SLO и без объявленного потребителя

Сделано = находка исчезает из отчёта источника при следующем прогоне (мост закроет карточку сам).

_finding_key: `B7:manifest_parity:com.spa.decision_loop` · ADR-066_
