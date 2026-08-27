---
trackerStatus:
  type: inbox
title: "Находка петли: com.spa.source_discovery работает, но plist не персистентен (repo:laun"
status: new
source: nimbalyst
created: 2026-08-27
finding_key: "B1:reboot_unsafe:com.spa.source_discovery"
---

Находка петли ADR-066 (architecture_conformance, WARN, подтверждена 2 прогонами подряд):

com.spa.source_discovery работает, но plist не персистентен (repo:launchd/com.spa.source_discovery.plist) — не переживёт ребут

Сделано = находка исчезает из отчёта источника при следующем прогоне (мост закроет карточку сам).

_finding_key: `B1:reboot_unsafe:com.spa.source_discovery` · ADR-066_
