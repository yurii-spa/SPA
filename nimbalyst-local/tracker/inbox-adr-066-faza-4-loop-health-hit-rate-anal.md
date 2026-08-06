---
trackerStatus:
  type: inbox
title: "ADR-066 Фаза 4: loop_health + hit-rate аналитиков + weekly retro + храповик"
status: done
source: nimbalyst
created: 2026-08-05
adr: ADR-066
phase: 4
---

data/loop_health.json (латентность находка→карточка→закрытие, рецидив, доля взятых карточек) + hit-rate аналитиков по образцу shadow_trigger_eval (RED подтвердился? возможность была реальной по evidenced APY? неоцениваемое=UNCHECKED) + еженедельный data/loop_retro.json + строка в digest + храповик порогов (базы только улучшаются). Кандидаты на ретайр/калибровку — ТОЛЬКО карточками (R4 owner-gated). Приёмка: первый ретро-отчёт с честными UNCHECKED и ≥1 обоснованным выводом. ADR-066 Контур D.
