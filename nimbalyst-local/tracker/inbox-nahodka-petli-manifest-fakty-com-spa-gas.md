---
trackerStatus:
  type: inbox
title: "Находка петли: манифест ↔ факты: com.spa.gas_price_agent: plist_source 'repo:launchd/"
status: new
source: nimbalyst
created: 2026-09-01
finding_key: "B5:drift:com.spa.gas_price_agent"
---

Находка петли ADR-066 (architecture_conformance, WARN, подтверждена 2 прогонами подряд):

манифест ↔ факты: com.spa.gas_price_agent: plist_source 'repo:launchd/com.spa.gas_price_agent.plist' → 'launch_agents'; reboot_safe False → True

Сделано = находка исчезает из отчёта источника при следующем прогоне (мост закроет карточку сам).

_finding_key: `B5:drift:com.spa.gas_price_agent` · ADR-066_
