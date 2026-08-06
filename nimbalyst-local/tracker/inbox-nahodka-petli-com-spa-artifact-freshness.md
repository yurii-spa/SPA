---
trackerStatus:
  type: inbox
title: "Находка петли: com.spa.artifact_freshness работает, но plist не персистентен (repo:sc"
status: done
source: nimbalyst
created: 2026-08-05
finding_key: "B1:reboot_unsafe:com.spa.artifact_freshness"
---

Находка петли ADR-066 (architecture_conformance, WARN, подтверждена 2 прогонами подряд):

com.spa.artifact_freshness работает, но plist не персистентен (repo:scripts/com.spa.artifact_freshness.plist) — не переживёт ребут

Сделано = находка исчезает из отчёта источника при следующем прогоне (мост закроет карточку сам).

_finding_key: `B1:reboot_unsafe:com.spa.artifact_freshness` · ADR-066_

> **Цикл #128 (2026-08-06):** закрывается ТОЛЬКО деплоем (plist в `~/Library/LaunchAgents` +
> перезапуск), а деплой owner-gated — агент этого не делает. Заведена карточка владельцу
> `owner-decision-dva-agenta-ne-perezhivut-perezagruzku-ra` (обе находки этого класса разом,
> с прецедентом 16.07 и корневой причиной: deploy-gate бутстрапит из репо-пути). Статус
> карточки намеренно оставлен `new` — мост закроет её сам, когда находка уйдёт из отчёта.
