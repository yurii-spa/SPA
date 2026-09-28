---
trackerStatus:
  type: inbox
title: "Находка петли: com.spa.site_freshness: объявлено PRODUCES (data/site_freshness_report"
status: new
source: nimbalyst
created: 2026-09-28
finding_key: "B7:contradiction:com.spa.site_freshness"
---

Находка петли ADR-066 (architecture_conformance, WARN, подтверждена 2 прогонами подряд):

com.spa.site_freshness: объявлено PRODUCES (data/site_freshness_report.json, landing/src/data/track_snapshot.json), а собственный модуль пишет ещё и (site_numbers.json) — объявление и код расходятся, и читатель продукта опирается на неверный контракт

Сделано = находка исчезает из отчёта источника при следующем прогоне (мост закроет карточку сам).

_finding_key: `B7:contradiction:com.spa.site_freshness` · ADR-066_
