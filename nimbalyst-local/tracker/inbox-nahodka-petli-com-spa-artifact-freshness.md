---
trackerStatus:
  type: inbox
title: "Находка петли: com.spa.artifact_freshness работает, но plist не персистентен (repo:sc"
status: new
source: nimbalyst
created: 2026-08-05
finding_key: "B1:reboot_unsafe:com.spa.artifact_freshness"
---

Находка петли ADR-066 (architecture_conformance, WARN, подтверждена 2 прогонами подряд):

com.spa.artifact_freshness работает, но plist не персистентен (repo:scripts/com.spa.artifact_freshness.plist) — не переживёт ребут

Сделано = находка исчезает из отчёта источника при следующем прогоне (мост закроет карточку сам).

_finding_key: `B1:reboot_unsafe:com.spa.artifact_freshness` · ADR-066_
