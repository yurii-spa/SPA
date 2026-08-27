---
trackerStatus:
  type: inbox
title: "Находка петли: манифест ↔ факты: com.spa.tracker_status_sentinel: plist_source 'repo:"
status: done
source: nimbalyst
created: 2026-08-27
finding_key: "B5:drift:com.spa.tracker_status_sentinel"
claimed_by: pid14899
claimed_at: 2026-08-27T10:29:14Z
status_trail:
  - "2026-08-27T10:41:47.085279+00:00 new -> done · queue.set_status · cycle-14899"
---

Находка петли ADR-066 (architecture_conformance, WARN, подтверждена 2 прогонами подряд):

манифест ↔ факты: com.spa.tracker_status_sentinel: plist_source 'repo:launchd/com.spa.tracker_status_sentinel.plist' → 'launch_agents'; reboot_safe False → True

Сделано = находка исчезает из отчёта источника при следующем прогоне (мост закроет карточку сам).

_finding_key: `B5:drift:com.spa.tracker_status_sentinel` · ADR-066_

---

**Разобрано циклом #394 (2026-08-27).** Дрейф был настоящим и в ту сторону, в которую надо:
факты ушли вперёд манифеста. Владелец установил оба plist'а в `~/Library/LaunchAgents` 27.08
(инв. #12), а манифест держал `repo:launchd/…` / `reboot_safe: false`.

Сделано: `architecture/manifest.json` пересобран из фактов
(`scripts/build_architecture_manifest.py --write`) + докурирована запись
`com.spa.orchestrator2` (ADR-149, `intent: designed` — код готов, установка остаётся
отдельным действием владельца), которой в манифесте не было вовсе. Проверка после:
«OK: манифест соответствует фактам (95 агентов)», находок B1/B5 — ноль.
