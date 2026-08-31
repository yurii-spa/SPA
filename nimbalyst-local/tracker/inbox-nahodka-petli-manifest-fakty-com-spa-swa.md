---
trackerStatus:
  type: inbox
title: "Находка петли: манифест ↔ факты: com.spa.swarm_dwell: plist_source 'launch_agents' → "
status: new
source: nimbalyst
created: 2026-08-31
finding_key: "B5:drift:com.spa.swarm_dwell"
---

Находка петли ADR-066 (architecture_conformance, WARN, подтверждена 2 прогонами подряд):

манифест ↔ факты: com.spa.swarm_dwell: plist_source 'launch_agents' → 'repo:launchd/com.spa.swarm_dwell.plist'; reboot_safe True → False

Сделано = находка исчезает из отчёта источника при следующем прогоне (мост закроет карточку сам).

_finding_key: `B5:drift:com.spa.swarm_dwell` · ADR-066_
