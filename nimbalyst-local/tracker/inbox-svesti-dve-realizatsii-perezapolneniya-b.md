---
trackerStatus:
  type: inbox
title: Свести две реализации перезаполнения бюджета в одну (ADR-072 vs версия параллельной сессии)
status: new
source: nimbalyst
created: 2026-08-08
priority: high
---

Решение владельца 09.08 (вариант 1): освободившийся после страховок бюджет перезаполняется внутри тех же потолков. Реализаций ДВЕ: (а) ADR-072 redistribute_freed_budget в risk_gate.py — в проде, chain-aware, повторный проход гейта, cap_bound-именование, 11 тестов, замер кэш 25%→10%; (б) версия параллельной сессии из карточки owner-decision-posle-strahovki-dengi-ostayutsya-sirotam. Задача: сверить, оставить ОДНУ (базой — прод-версию), вторую удалить, тесты объединить, sandbox-замер до/после, pre_cutover_gate. Два механизма одного назначения = будущий конфликт в money-path.
