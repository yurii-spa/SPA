---
trackerStatus:
  type: inbox
title: "Находка петли: манифест ↔ факты: com.spa.dfb_capture: plist_source 'launch_agents' → "
status: done
source: nimbalyst
created: 2026-08-31
finding_key: "B5:drift:com.spa.dfb_capture"
status_trail:
  - "2026-08-31T17:37:47.178680+00:00 new -> done · queue.set_status"
---

Находка петли ADR-066 (architecture_conformance, WARN, подтверждена 2 прогонами подряд):

манифест ↔ факты: com.spa.dfb_capture: plist_source 'launch_agents' → 'repo:launchd/com.spa.dfb_capture.plist'; reboot_safe True → False

Сделано = находка исчезает из отчёта источника при следующем прогоне (мост закроет карточку сам).

_finding_key: `B5:drift:com.spa.dfb_capture` · ADR-066_
