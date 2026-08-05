---
trackerStatus:
  type: inbox
title: "ADR-066 Фаза 0: манифест архитектуры (машиночитаемая конституция)"
status: backlog
source: nimbalyst
created: 2026-08-05
adr: ADR-066
phase: 0
---

Схема architecture/manifest.json (agents: layer/role/intent/produces+SLO/consumes/consumer_required/governed_by; artifacts: producer/consumers/slo_hours) + генератор из plist'ов и реестра + ручное курирование намерения. Все 71 живых + 9 known-not-loaded агентов, intent проставлен честно (active/designed/retired). Приёмка: манифест полон, designed≠active явно, генератор идемпотентен. Дизайн: docs/decisions/ADR-066-architecture-conformance-and-decision-loop.md (Контур A).
