---
trackerStatus:
  type: inbox
title: "ADR-070.22: paper-модуль dwell-защёлки"
status: done
source: nimbalyst
created: 2026-08-07
adr: ADR-070
---

Advisory форвард; выигрыш — просадка на треть (решение владельца 2026-08-07, ADR-070 п.22)

## Закрыто 16.08

Посылка перепроверена на этом дереве (волна 0 триажа `docs/BACKLOG_TRIAGE_2026-08-16.md`):

- `spa_core/strategy_lab/swarm/dwell_hysteresis_forward.py` существует (19 109 байт) —
  advisory-форвард dwell-защёлки (`DWELL_K = 2`) поверх самого медленного сигнала выхода
  `ecdr#23(10/30)`, со своей paper-книгой `data/swarm/dwell_hysteresis_book.jsonl`
  (append-only) и контрольной рукой «защёлка снята»;
- тесты есть: `spa_core/tests/test_swarm_dwell_hysteresis_forward.py`.

Модуль построен — работы по карточке ноль, нужен был только перевод статуса.
