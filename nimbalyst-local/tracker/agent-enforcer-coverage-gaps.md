---
trackerStatus:
  type: agent
title: Закрыть дыры покрытия policy_enforcer — добавить проверки T2-per-protocol + chain-caps (зеркало policy.py)
status: backlog
source: owner-decision-2026-07-23 (Решение 4, пере-скоуп)
created: 2026-07-23
priority: high
domain: money-path (значения RiskPolicy НЕ меняем; pre_cutover_gate + ADR)
---

## Что случилось (разбор 2026-07-23)

Карточка `own-25`/«бумажный тест» Решение 4 предполагала расхождение ЗНАЧЕНИЙ enforcer vs policy.py.
Замер показал: **расхождение значений уже устранено 2026-07-08** (enforcer читает из RiskConfig,
per-protocol 25%→40%, ложный T1-floor 55% убран); d6_risk_gates больше НЕ CRITICAL (сейчас INFO).

**Реальная работа — дыры ПОКРЫТИЯ:** `validate_positions` в enforcer'е не проверяет часть кэпов
`policy.py`:
- `max_concentration_t2` = **20%** (T2 на один протокол) — сейчас юзается единый 40%;
- `BASE_CHAIN_CAP` = **20%**;
- `max_l2_total_allocation` = **50%**;
- `max_single_chain_allocation` = **90%**.

## Что нужно

Добавить в enforcer проверки, зеркалящие `policy.py` (значения брать из RiskConfig, не хардкодить).
Только усиление, значения не меняются. LLM запрещён. Money-path ⇒ изолированный workspace + тесты +
`pre_cutover_gate` + ADR.

## Как понять, что готово

Тест: T2-протокол на 21% → enforcer краснит (сейчас пропускает); Base>20%/L2>50%/single-chain>90% →
краснят; текущий портфель проходит (замер 2026-07-23: T2 pendle 19.9%, Base 5%, L2 5%, eth 74.5% — OK);
значения RiskConfig byte-identical; ADR принят.

## Наблюдения на будущее (не в скоупе этой карты)

- T3 total 14.9% при потолке 15% — портфель впритык к T3-границе (susde + extra_finance_base оба T3).
- 5/24 стейл-фидов (d1/d2/d3/d_riskwire WARNING) — отдельная линия этапа D, см. карту про аллокатор.
