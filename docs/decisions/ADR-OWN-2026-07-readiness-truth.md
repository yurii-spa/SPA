# ADR-OWN-2026-07-readiness-truth — Публичная поверхность не может говорить READY, пока настоящий гейт отказывает

**Дата:** 2026-07-29 · **Статус:** ПРИНЯТО (владелец: «вариант А», рекомендация карточки)
**Связано:** карточка `owner-decision-otchet-gotovnosti-govorit-gotovy-hotya-t.md` (2026-07-17)

## Контекст

`spa_core/analytics/golive_readiness_report.py` (отдаётся в `/api/v1/golive`-fallback, Telegram-дайджест,
`pre_deploy_check`) публиковал **READY (96/100)** при живом отказе настоящего гейта
(`golive_status.json ready:false`). Две причины: (1) READY считался только по баллам (≥80), а
30-дневный трек в шкалу не заложен; (2) страховка «backtest-гейт не пройден → BLOCKED» была мертва —
искала категорию `gate_status`, которую v10.41 переименовал в `gates`.

## Решение (вариант А)

**READY на любой публичной поверхности ⇔ `golive_status.json ready == true` И score ≥ 80.**
Баллы — прогресс-бар; готовность решает только гейт. Это прямое следствие инвариантов
«refusal-first» и «не выдавать paper за live» (§8 CLAUDE.md).

Дополнительно: мёртвое BLOCKED-правило заменено прямой проверкой файла гейта
(`pre_paper_backtest_gate.json status != PASS → BLOCKED`) — независимо от имён категорий.

## Реализация

- `overall_status()` в `golive_readiness_report.py` (2026-07-29, запушено в main).
- Тесты: `test_golive_readiness_report.py` 101 passed; старый тест «READY по одним баллам»
  изменён ОСОЗНАННО (закреплял дефект) — обоснование в докстринге теста + журнал W31 (правило #16).
- Артефакт `data/reports/golive_readiness_2026-07-29.json` перегенерирован: `NOT_READY`.
