---
trackerStatus:
  type: inbox
title: "Находка петли: манифест ↔ факты: com.spa.source_discovery: plist_source 'launch_agent"
status: new
source: nimbalyst
created: 2026-08-31
finding_key: "B5:drift:com.spa.source_discovery"
---

Находка петли ADR-066 (architecture_conformance, WARN, подтверждена 2 прогонами подряд):

манифест ↔ факты: com.spa.source_discovery: plist_source 'launch_agents' → 'repo:launchd/com.spa.source_discovery.plist'; reboot_safe True → False

Сделано = находка исчезает из отчёта источника при следующем прогоне (мост закроет карточку сам).

_finding_key: `B5:drift:com.spa.source_discovery` · ADR-066_
