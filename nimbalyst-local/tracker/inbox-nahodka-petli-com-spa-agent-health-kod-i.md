---
trackerStatus:
  type: inbox
title: "Находка петли: com.spa.agent_health: код и манифест называют РАЗНЫЙ продукт (только в"
status: new
source: nimbalyst
created: 2026-09-10
finding_key: "B7:manifest_parity:com.spa.agent_health"
---

Находка петли ADR-066 (architecture_conformance, WARN, подтверждена 2 прогонами подряд):

com.spa.agent_health: код и манифест называют РАЗНЫЙ продукт (только в объявлении: —; только в манифесте: data/orphaned_pytest.json) — манифест знает продукт, которого нет в объявлении — объявление отстало или пишет не точка входа

Сделано = находка исчезает из отчёта источника при следующем прогоне (мост закроет карточку сам).

_finding_key: `B7:manifest_parity:com.spa.agent_health` · ADR-066_
