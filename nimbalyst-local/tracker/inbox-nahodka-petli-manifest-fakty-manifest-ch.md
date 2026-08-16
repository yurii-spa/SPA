---
trackerStatus:
  type: inbox
title: "Находка петли: манифест ↔ факты: manifest --check вернул дрейф (см. build_architectur"
status: done
source: nimbalyst
created: 2026-08-15
finding_key: "B5:drift:manifest --check вернул дрейф (см. build_architecture_manifest.py)"
---

Находка петли ADR-066 (architecture_conformance, WARN, подтверждена 2 прогонами подряд):

манифест ↔ факты: manifest --check вернул дрейф (см. build_architecture_manifest.py)

Сделано = находка исчезает из отчёта источника при следующем прогоне (мост закроет карточку сам).

_finding_key: `B5:drift:manifest --check вернул дрейф (см. build_architecture_manifest.py)` · ADR-066_

## Закрыто 16.08

**Схлопнуто 16.08 в `agent-manifest-drift-morning-digest`: то же самое другими словами**
(кластер К4 триажа `docs/BACKLOG_TRIAGE_2026-08-16.md`) — обе карточки об одном дрейфе
«манифест ↔ факты», и корневая содержит и конкретный случай (`com.spa.morning_digest`),
и более широкий замер (манифест 92 агента против флота 77 — расхождение 15 записей).

**Корневая карточка остаётся ОТКРЫТОЙ.** Триаж относил обе к «уже сделано», но на этом
дереве это не подтвердилось: `_manifest_drift_problems()` возвращает `None` («не прод-хост»,
`~/Library/LaunchAgents` без `com.spa.*.plist`), то есть находка B5 из облака НЕ ИЗМЕРИМА —
её источник живёт на Маке. Закрывать по зелёному прогону, который отвечает на другой вопрос,
нельзя (`.claude/rules/deployment.md`, «четыре вопроса — четыре сторожа»).
