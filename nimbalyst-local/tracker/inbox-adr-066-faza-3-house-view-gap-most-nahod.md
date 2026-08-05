---
trackerStatus:
  type: inbox
title: "ADR-066 Фаза 3: house_view_gap + мост находка→карточка"
status: done
source: nimbalyst
created: 2026-08-05
adr: ADR-066
phase: 3
---

house_view_gap (детерминированная сверка house_view+RED/YELLOW сигналов с фактической аллокацией, расхождения в data/house_view_gap.json, только сверка) + scripts/findings_to_cards.py: dedup-ключ, гистерезис, rate-limit ≤5/сутки (отложенное — в отчёт, не молча), авто-закрытие при исчезновении находки, CRITICAL→needs-owner+Telegram, остальное→agent-backlog, только через orchestrator_queue.py create. Приёмка: искусственная находка проходит находка→карточка→закрытие без рук. ADR-066 Контуры C1–C2.

## Выполнено — цикл #125 (2026-08-06)

**C1 `spa_core/monitoring/house_view_gap.py`** — детерминированная сверка house_view + сигналов
аналитики с ФАКТИЧЕСКОЙ аллокацией, расхождения в `data/house_view_gap.json`. Только сверка,
капитал не двигает (ADR-066 P5). Проверки: G1 возможность ≥L3 не в книге И отказ нигде не назван ·
G2 негативный сигнал по удерживаемому протоколу (RED/red-team → CRITICAL; жёлтый → WARN weak,
стареет) · G3 постура RED без запаса кэша · G4 простой сверх буфера не объяснён (ADR-055).
Названный отказ (`blocked_protocols` / `below_median_cap` / ноги последнего хода) находкой НЕ
является; непрочитанный rationale — UNCHECKED, а не «не назван». Формат находки побуквенно равен
`architecture_conformance` (мост читает оба одним кодом). Живой прогон против прода: WARN,
7 расхождений, все настоящие.

**C2 `scripts/findings_to_cards.py`** — мост находка→карточка→закрытие. Dedup по ключу
`<источник>/<key>` · гистерезис (новая/эскалировавшая; слабым нужно 2 подтверждения; CRITICAL
сразу; cooldown повторного открытия 24ч) · rate-limit ≤5/сутки с ПОИМЁННЫМ списком отложенного ·
авто-закрытие с дописанным эвиденсом · CRITICAL → `owner-decision`/`needs-owner` (формат §2.4) +
Telegram, остальное → `agent-task`/`backlog`. Карточки только через `orchestrator_queue.py`. Без
`--apply` мост не мутирует ничего. **Непрочитанный/протухший источник не закрывает НИ ОДНОЙ
карточки** (fail-CLOSED: сломанный сторож не смеет «чинить» очередь).

**Интеграция:** Steps 5–6 в `scripts/run_daily_paper_cycle.sh` (оба не-фатальные) · оба продукта
объявлены в `architecture/manifest.json` (SLO 26ч, потребитель `orchestrator_protocol`) ·
`consume_office_reports.py` показывает их суть · Шаг 0-офис протокола обновлён (C3).

**Приёмка карточки выполнена дословно:** `test_findings_to_cards.py::
test_acceptance_finding_becomes_a_card_and_closes_itself` — искусственная находка проходит
находка→карточка→закрытие без единого ручного действия, через НАСТОЯЩИЙ `orchestrator_queue.py`.
Всего 66 тестов (34 C1 + 25 C2 + 7 доставки); 10 мутаций покраснили ровно свои тесты, после
отката 66/66. Ни один существующий тест не изменён. mypy на новых модулях чист,
`lint_llm_forbidden` 172/0.
