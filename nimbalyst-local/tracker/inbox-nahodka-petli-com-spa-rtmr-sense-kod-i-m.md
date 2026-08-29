---
trackerStatus:
  type: inbox
title: "Находка петли: com.spa.rtmr_sense: код и манифест называют РАЗНЫЙ продукт (только в о"
status: new
source: nimbalyst
created: 2026-08-29
finding_key: "B7:manifest_parity:com.spa.rtmr_sense"
---

Находка петли ADR-066 (architecture_conformance, WARN, подтверждена 2 прогонами подряд):

com.spa.rtmr_sense: код и манифест называют РАЗНЫЙ продукт (только в объявлении: data/monitoring/signals/latest.json; только в манифесте: —) — артефакт объявлен кодом, но манифест его не знает — он без SLO и без объявленного потребителя

Сделано = находка исчезает из отчёта источника при следующем прогоне (мост закроет карточку сам).

_finding_key: `B7:manifest_parity:com.spa.rtmr_sense` · ADR-066_
