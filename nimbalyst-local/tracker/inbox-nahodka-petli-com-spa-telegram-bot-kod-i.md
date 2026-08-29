---
trackerStatus:
  type: inbox
title: "Находка петли: com.spa.telegram_bot: код и манифест называют РАЗНЫЙ продукт (только в"
status: new
source: nimbalyst
created: 2026-08-29
finding_key: "B7:manifest_parity:com.spa.telegram_bot"
---

Находка петли ADR-066 (architecture_conformance, WARN, подтверждена 2 прогонами подряд):

com.spa.telegram_bot: код и манифест называют РАЗНЫЙ продукт (только в объявлении: data/kill_switch_active.json, data/tg_bot_v2_offset.json; только в манифесте: —) — артефакт объявлен кодом, но манифест его не знает — он без SLO и без объявленного потребителя

Сделано = находка исчезает из отчёта источника при следующем прогоне (мост закроет карточку сам).

_finding_key: `B7:manifest_parity:com.spa.telegram_bot` · ADR-066_
