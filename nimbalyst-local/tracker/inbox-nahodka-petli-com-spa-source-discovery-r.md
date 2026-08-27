---
trackerStatus:
  type: inbox
title: "Находка петли: com.spa.source_discovery работает, но plist не персистентен (repo:laun"
status: done
source: nimbalyst
created: 2026-08-27
finding_key: "B1:reboot_unsafe:com.spa.source_discovery"
claimed_by: pid14899
claimed_at: 2026-08-27T10:29:14Z
status_trail:
  - "2026-08-27T10:41:46.651047+00:00 new -> done · queue.set_status · cycle-14899"
---

Находка петли ADR-066 (architecture_conformance, WARN, подтверждена 2 прогонами подряд):

com.spa.source_discovery работает, но plist не персистентен (repo:launchd/com.spa.source_discovery.plist) — не переживёт ребут

Сделано = находка исчезает из отчёта источника при следующем прогоне (мост закроет карточку сам).

_finding_key: `B1:reboot_unsafe:com.spa.source_discovery` · ADR-066_

---

**Разобрано циклом #394 (2026-08-27).** Находка была ВЕРНА по своему контракту и УСТАРЕЛА по
факту: `reboot_safe` она читает из манифеста, а манифест отстал от фактов. Замер: оба plist'а
лежат в `~/Library/LaunchAgents` (владелец установил их 27.08 в 00:10/00:18 — инв. #12,
установка руками владельца), `launchctl list` показывает обоих. То есть агенты РЕБУТ переживут,
а манифест продолжал объявлять их «подготовленными, не установленными».

Сделано: `architecture/manifest.json` пересобран из фактов
(`scripts/build_architecture_manifest.py --write`) — `plist_source: launch_agents`,
`reboot_safe: true`, поле `notes` больше не утверждает «не установлен». Проверка после:
`build_architecture_manifest.py` → «OK: манифест соответствует фактам (95 агентов)»;
`architecture_conformance` не выдаёт ни одной находки классов B1/B5.
