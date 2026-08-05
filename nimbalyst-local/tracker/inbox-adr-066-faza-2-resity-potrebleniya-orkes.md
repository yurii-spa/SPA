---
trackerStatus:
  type: inbox
title: "ADR-066 Фаза 2: реситы потребления + оркестратор/digest читают офис"
status: done
source: nimbalyst
created: 2026-08-05
adr: ADR-066
phase: 2
---

Протокол data/consumption_receipts.jsonl (append-only). Обязательный шаг цикла оркестратора: читать chief_investment.json + _health.json + architecture_conformance.json + house_view_gap.json, писать реситы (правка docs/ORCHESTRATOR_PROTOCOL.md + промпта scripts/agent_orchestrator.sh — утверждено ADR-066). Daily digest: строка house_view (постура+топ-конфликт) + строка conformance. Приёмка: B3 для io_* перестаёт быть красным честным путём. ADR-066 Контуры C3–C4.
