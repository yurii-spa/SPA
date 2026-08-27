---
trackerStatus:
  type: inbox
title: "Находка петли: com.spa.tracker_status_sentinel работает, но plist не персистентен (re"
status: new
source: nimbalyst
created: 2026-08-27
finding_key: "B1:reboot_unsafe:com.spa.tracker_status_sentinel"
---

Находка петли ADR-066 (architecture_conformance, WARN, подтверждена 2 прогонами подряд):

com.spa.tracker_status_sentinel работает, но plist не персистентен (repo:launchd/com.spa.tracker_status_sentinel.plist) — не переживёт ребут

Сделано = находка исчезает из отчёта источника при следующем прогоне (мост закроет карточку сам).

_finding_key: `B1:reboot_unsafe:com.spa.tracker_status_sentinel` · ADR-066_
