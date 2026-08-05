---
trackerStatus:
  type: inbox
title: "ADR-066 Фаза 3: house_view_gap + мост находка→карточка"
status: new
source: nimbalyst
created: 2026-08-05
adr: ADR-066
phase: 3
---

house_view_gap (детерминированная сверка house_view+RED/YELLOW сигналов с фактической аллокацией, расхождения в data/house_view_gap.json, только сверка) + scripts/findings_to_cards.py: dedup-ключ, гистерезис, rate-limit ≤5/сутки (отложенное — в отчёт, не молча), авто-закрытие при исчезновении находки, CRITICAL→needs-owner+Telegram, остальное→agent-backlog, только через orchestrator_queue.py create. Приёмка: искусственная находка проходит находка→карточка→закрытие без рук. ADR-066 Контуры C1–C2.
