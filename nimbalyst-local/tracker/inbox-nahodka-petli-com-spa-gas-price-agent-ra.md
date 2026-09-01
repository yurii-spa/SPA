---
trackerStatus:
  type: inbox
title: "Находка петли: com.spa.gas_price_agent работает, но plist не персистентен (repo:launc"
status: new
source: nimbalyst
created: 2026-09-01
finding_key: "B1:reboot_unsafe:com.spa.gas_price_agent"
---

Находка петли ADR-066 (architecture_conformance, WARN, подтверждена 2 прогонами подряд):

com.spa.gas_price_agent работает, но plist не персистентен (repo:launchd/com.spa.gas_price_agent.plist) — не переживёт ребут

Сделано = находка исчезает из отчёта источника при следующем прогоне (мост закроет карточку сам).

_finding_key: `B1:reboot_unsafe:com.spa.gas_price_agent` · ADR-066_
