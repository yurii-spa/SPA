---
trackerStatus:
  type: inbox
title: "Находка петли: com.spa.apiserver: код и манифест называют РАЗНЫЙ продукт (только в об"
status: new
source: nimbalyst
created: 2026-08-29
finding_key: "B7:manifest_parity:com.spa.apiserver"
---

Находка петли ADR-066 (architecture_conformance, WARN, подтверждена 2 прогонами подряд):

com.spa.apiserver: код и манифест называют РАЗНЫЙ продукт (только в объявлении: data/interest.jsonl, data/pilot_requests.jsonl, data/site_analytics.jsonl; только в манифесте: —) — артефакт объявлен кодом, но манифест его не знает — он без SLO и без объявленного потребителя

Сделано = находка исчезает из отчёта источника при следующем прогоне (мост закроет карточку сам).

_finding_key: `B7:manifest_parity:com.spa.apiserver` · ADR-066_
