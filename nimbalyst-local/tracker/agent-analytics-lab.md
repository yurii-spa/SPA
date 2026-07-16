---
trackerStatus:
  type: agent-task
title: Q2: аналитику в analytics_lab/
status: in-progress
source: session-2026-07-16
created: 2026-07-16
---

Q2: ~45 неподключённых аналитич. модулей → spa_core/analytics_lab/ (не удалять, сырьё для продуктового слоя). С тестами.

## Начато 2026-07-16
Пакет spa_core/analytics_lab/ создан + верифицировано 27 модулей как внешне-мёртвые (0 non-test import) + протокол переноса в README. Массовый перенос (с переписью импортов тестов, батчами+collect-gate) — следующей сессией (не рискую ботч-рефактором при 98% контекста).
