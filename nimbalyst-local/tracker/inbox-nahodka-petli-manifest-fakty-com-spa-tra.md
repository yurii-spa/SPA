---
trackerStatus:
  type: inbox
title: "Находка петли: манифест ↔ факты: com.spa.tracker_status_sentinel: plist_source 'repo:"
status: new
source: nimbalyst
created: 2026-08-27
finding_key: "B5:drift:com.spa.tracker_status_sentinel"
---

Находка петли ADR-066 (architecture_conformance, WARN, подтверждена 2 прогонами подряд):

манифест ↔ факты: com.spa.tracker_status_sentinel: plist_source 'repo:launchd/com.spa.tracker_status_sentinel.plist' → 'launch_agents'; reboot_safe False → True

Сделано = находка исчезает из отчёта источника при следующем прогоне (мост закроет карточку сам).

_finding_key: `B5:drift:com.spa.tracker_status_sentinel` · ADR-066_
