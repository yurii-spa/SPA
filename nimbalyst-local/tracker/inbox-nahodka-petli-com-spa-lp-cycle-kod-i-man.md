---
trackerStatus:
  type: inbox
title: "Находка петли: com.spa.lp_cycle: код и манифест называют РАЗНЫЙ продукт (только в объ"
status: done
source: nimbalyst
created: 2026-09-10
finding_key: "B7:manifest_parity:com.spa.lp_cycle"
status_trail:
  - "2026-10-04T20:42:10.896123+00:00 new -> done · queue.set_status/closed_by:findings_bridge/evidence:finding B7:manifest_parity:com.spa.lp_cycle absent in the fresh report (ADR-066 C2) · cycle-16566"
---

Находка петли ADR-066 (architecture_conformance, WARN, подтверждена 2 прогонами подряд):

com.spa.lp_cycle: код и манифест называют РАЗНЫЙ продукт (только в объявлении: —; только в манифесте: data/sleeve_inputs_aggressive.jsonl) — манифест знает продукт, которого нет в объявлении — объявление отстало или пишет не точка входа

Сделано = находка исчезает из отчёта источника при следующем прогоне (мост закроет карточку сам).

_finding_key: `B7:manifest_parity:com.spa.lp_cycle` · ADR-066_
