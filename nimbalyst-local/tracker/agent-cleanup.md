---
trackerStatus:
  type: agent-task
title: Чистка репо (мёртвый код) фазами
status: in-progress
source: session-2026-07-16
created: 2026-07-16
---

Фазами с гейтом тестов: 49 скриптов + 9 модулей → archive/attic (обратимо). Дальше pass-3 кандидаты.


---

## Вход от аудита 21.08 (ночь): вердикты по «сиротам» — разобрано состязательно

Из 13 подозреваемых **8 оказались ЖИВЫМИ** (внутрипакетные вызывающие; полный список
и строки вызовов — docs/AUDIT_IDLE_BUT_IMPORTANT_2026-08-21.md §C, вторая редакция).
Для чистки остаётся ровно:

1. **УДАЛИТЬ `spa_core/strategy_lab/aggressive_lab_runner.py`** (+ его
   test_aggressive_lab_run_daily.py и докстринг-ссылку в aggressive_lab/run.py:88) —
   вторая голова оркестрации, launchd зовёт aggressive_lab.run, раннер мёртв.
2. **Перенести 3 test_*.py из spa_core/analytics/gross_of/ в spa_core/tests/**
   (косметика; НЕ удалять — единственные тесты трёх живых анализаторов).
3. НЕ трогать: promotion_rates, capacity_sizing, fair_value, rate_floor_recal,
   tier_policy, tail_overlay, onchain_nav, sequencer_tip_config, liquidator/,
   exit_liquidity_validation (двум последним — осознанный research-keep).

Отдельно НЕ для чистки (задачи подключения, у аудита §A): rank_demotion_forward
(вторая рука ADR-074 без обёртки) и monthly_statement (выписки гниют с июня).
