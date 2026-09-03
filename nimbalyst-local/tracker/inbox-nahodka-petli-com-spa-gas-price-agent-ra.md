---
trackerStatus:
  type: inbox
title: "Находка петли: com.spa.gas_price_agent работает, но plist не персистентен (repo:launc"
status: done
source: nimbalyst
created: 2026-09-01
finding_key: "B1:reboot_unsafe:com.spa.gas_price_agent"
claimed_by: cycle-94385
claimed_at: 2026-09-02T23:40:00Z
status_trail:
  - "2026-09-03T11:46:08.754476+00:00 new -> done · queue.set_status"
---

Находка петли ADR-066 (architecture_conformance, WARN, подтверждена 2 прогонами подряд):

com.spa.gas_price_agent работает, но plist не персистентен (repo:launchd/com.spa.gas_price_agent.plist) — не переживёт ребут

Сделано = находка исчезает из отчёта источника при следующем прогоне (мост закроет карточку сам).

_finding_key: `B1:reboot_unsafe:com.spa.gas_price_agent` · ADR-066_
