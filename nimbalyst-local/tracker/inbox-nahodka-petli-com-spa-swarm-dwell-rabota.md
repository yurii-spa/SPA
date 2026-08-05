---
trackerStatus:
  type: inbox
title: "Находка петли: com.spa.swarm_dwell работает, но plist не персистентен (repo:launchd/c"
status: new
source: nimbalyst
created: 2026-08-05
finding_key: "B1:reboot_unsafe:com.spa.swarm_dwell"
---

Находка петли ADR-066 (architecture_conformance, WARN, подтверждена 2 прогонами подряд):

com.spa.swarm_dwell работает, но plist не персистентен (repo:launchd/com.spa.swarm_dwell.plist) — не переживёт ребут

Сделано = находка исчезает из отчёта источника при следующем прогоне (мост закроет карточку сам).

_finding_key: `B1:reboot_unsafe:com.spa.swarm_dwell` · ADR-066_
