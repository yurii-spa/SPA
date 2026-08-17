---
trackerStatus:
  type: agent-task
title: "Два артефакта одного цикла втрое расходятся в оценке потерь: 451 б.п. против 132 б.п."
status: done
source: session-2026-08-08-owner-answers
created: 2026-08-08
priority: medium
tags: [observability, capital-efficiency, apy-honesty, adr-055]
---

## Что нашлось

Один и тот же цикл 2026-08-08, два артефакта, одна и та же строка простоя — и разные числа.

| | `capital_efficiency.json` | `allocation_rationale.json` |
|---|---|---|
| упущенная доходность | **451.1 б.п./год** | **132.4 б.п./год** |
| `moonwell_base` | +$20 000 @ **22.56 %** | +$20 000 @ **6.62 %** |
| `aave_v3` | +$35 000 @ **4.77 %** | +$40 000 @ **3.31 %** |

Снимок адаптеров (`adapter_status.json`, 09:57 UTC) говорит: `moonwell_base` = **6.6223 %**,
`aave_v3` = **3.3051 %**. То есть числа `allocation_rationale` совпадают со снимком, а числа
`capital_efficiency` — нет, и именно из них считается `best_qualifying_apy_pct = 22.5558` и
итоговые 451 б.п.

## Почему это важно

`forgone_yield_bps_est` — это ЧИСЛО, КОТОРОЕ ЧИТАЕТ ВЛАДЕЛЕЦ, когда решает, насколько срочно
чинить простой капитала. Оно завышено в 3.4 раза относительно второго артефакта того же цикла.
Обе оценки не могут быть верны одновременно.

22.56 % у base-пула USDC — само по себе подозрительное число: оно вне диапазона RiskPolicy
(1–30 % формально проходит, но втрое выше живого наблюдения того же пула).

## Что сделать

1. Найти, из какого источника `capital_efficiency` берёт APY (похоже, не из того снимка, что
   `allocation_rationale`), и свести к одному.
2. Проверить, не подмешивается ли туда reward/incentive-APY вместо base-APY.
3. Закрепить тестом: два артефакта одного цикла обязаны сходиться по APY одного и того же пула.

Капитал не двигается, поведение не меняется — это честность отчётности.

---

## 🔎 СВЕРКА 2026-08-17 (код + прогон) → `done`

**Все три пункта «что сделать» закрыты в коде, проверено прогоном, не по журналу.**

1. **Источник сведён к одному, и он назван.** `spa_core/monitoring/capital_efficiency.py`:
   `_live_apys()` (строки 187–233) вместо голого числа возвращает четвёртым полем ВЕРДИКТ строки —
   `observed` либо названную причину (`apy_unobserved:<source>` / `apy_row_stale:<age>h` /
   `apy_row_undated`); признак наблюдения берётся из `OBSERVED_APY_SOURCES`
   (`spa_core.adapters.apy_aggregator`), а не выдумывается локально. `_cycle_evidenced_apys()`
   (строки 243–276) делает очную ставку с `apy_evidenced_pct` последней записи
   `allocation_rationale_history.jsonl` — то есть ровно с тем артефактом, чьи числа разошлись.
2. **Ответ на «не подмешивается ли reward-APY» — нет, подмешивался ЛИТЕРАЛ.** 22.5558 % у
   `moonwell_base` пришли строкой рейтинга с меткой `fallback` (число, помеченное самим
   производителем как НЕ наблюдение). Это зафиксировано положительным контролем
   `test_a_literal_apy_may_not_price_idle_capital`: после починки `best_qualifying_apy_pct`
   = 3.3051 (живой `aave_v3`), а литеральная комната названа
   (`headroom_apy_unobserved` + `apy_unobserved:fallback` в `headroom_excluded`),
   `0 < forgone_yield_bps_est < 100` вместо 451.
3. **Храповик стоит:** `spa_core/tests/test_apy_one_observation_per_cycle.py` —
   `test_two_artifacts_of_one_cycle_must_agree_about_a_pool` (дословные 4.77 % vs 3.31 %
   ⇒ `apy_diverging_from_cycle == ["aave_v3"]`, `verdict == "UNKNOWN"`),
   `test_end_to_end_one_snapshot_gives_both_artifacts_the_same_number` (сквозная проводка
   `adapter_status` → рейтинг → тревога) + контроли в обратную сторону
   (`test_agreement_within_rounding_noise_is_not_a_divergence`,
   `test_a_stale_history_line_does_not_veto_a_fresh_ranking` — иначе «починкой» было бы вечное UNKNOWN).

Прогон сверки: `python3 -m pytest spa_core/tests/test_apy_one_observation_per_cycle.py -q`
→ `19 passed in 0.50s`. Кода не менял.
