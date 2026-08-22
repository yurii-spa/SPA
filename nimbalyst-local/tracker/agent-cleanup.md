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

1. ✅ **СДЕЛАНО 2026-08-22 (ночь):** `aggressive_lab_runner.py` удалён; докстринг-ссылка в
   `aggressive_lab/run.py` переписана. **Отклонение от формулировки — осознанное:**
   `test_aggressive_lab_run_daily.py` НЕ удалён целиком — из трёх тестов раннеру принадлежал
   один (`test_runner_resolves_run_daily_first`, удалён вместе с ним), два других охраняют
   живую проводку `run.py` (real-feeds guard бага замороженного трека 2026-07-06) и сохранены
   (инв. #16: молча сузить сторожа живого агента нельзя).
2. ✅ **СДЕЛАНО 2026-08-22 (ночь):** 3 test_*.py перенесены в `spa_core/tests/test_gross_of/`
   (295 тестов переехали без потерь: 0 осталось в analytics/, 393 = 295+98 собираются на новом
   месте; Run-строки докстрингов обновлены).
3. НЕ трогать: promotion_rates, capacity_sizing, fair_value, rate_floor_recal,
   tier_policy, tail_overlay, onchain_nav, sequencer_tip_config, liquidator/,
   exit_liquidity_validation (двум последним — осознанный research-keep).

Отдельно НЕ для чистки (задачи подключения, у аудита §A): rank_demotion_forward
(вторая рука ADR-074 без обёртки) и monthly_statement (выписки гниют с июня).
