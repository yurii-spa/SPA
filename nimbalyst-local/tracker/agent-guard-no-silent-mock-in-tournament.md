---
trackerStatus:
  type: agent
title: Guard — стратегия не должна молча падать на mock, если заявленный живой адаптер не грузится
status: done
source: owner-requirement-2026-07-23 (защита от повтора S23)
created: 2026-07-23
priority: high
domain: strategy/eval integrity
---

## Зачем (owner-требование)

Класс бага S23: стратегия заявляет «беру живой Pendle», импортирует адаптер внутри `except: pass`,
адаптер мёртв → ошибка глотается молча → стратегия НАВСЕГДА на mock-числе (7%) → mock попадает в
турнир как реальная оценка. Владелец (2026-07-23): предусмотреть, чтобы это НЕ повторилось.

Тот же класс, что: fail-OPEN мониторы (memory `fail-open-monitor-class`), abstract-analytics
silently-dead (`abstract-analytics-latent-bugs`), silently-skipped tests.

## Что сделать (guard, детерминированно, LLM запрещён)

1. **Тест-guard:** для каждой стратегии, заявляющей живой источник, проверить, что заявленный адаптер
   реально ИМПОРТИРУЕТСЯ (import-based, не `compile`) — падение = красный тест, а не тихий mock.
   (Тот же принцип, что фикс гейта готовности в карте 2.)
2. **Запрет `except: pass` вокруг импорта адаптера** в стратегиях (lint/AST-проверка): молчаливое
   глотание ImportError запрещено — логировать + помечать `*_live: false` явно.
3. **Турнир помечает/исключает mock-записи:** стратегия с `*_live: false` НЕ ранжируется как живая —
   либо отдельная пометка «MOCK», либо исключение из доверенного лидерборда (см. карту
   `agent-tournament-trustworthy-real-apy.md`).

## Защита самого honesty-gate (owner-вопрос 2026-07-23)

Турнир уже имеет HONESTY GATE (`mass_tournament.py:650`, `assess_tournament_trust`): fail-CLOSED
штампует `trustworthy:false` на вырожденных/mock данных. Риск рецидива в ДВУХ формах:
1. **Снова подсунуть mock** — gate ПОЙМАЁТ (пометит false), но не предотвратит; ловят п.1–3 выше.
2. **Молча ЗАГЛУШИТЬ сам gate** (поставить `trustworthy:true` / убрать проверку) = инвариант #16.
   → добавить **тест, что honesty-gate СРАБАТЫВАЕТ** на вырожденных/mock входах (near-const returns →
   `trustworthy:false`) — тогда gate нельзя тихо удалить/ослабить (тест покраснеет). Тест-guard на
   сам guard.

## Как понять, что готово

Тест: стратегия с заявленным-живым, но не грузящимся адаптером → guard краснит; mock-запись не
попадает в доверенный рейтинг незамеченной; S23 после фикса (MP-201) проходит guard как живая;
honesty-gate доказанно срабатывает на mock-входе (нельзя тихо заглушить).

## Связано

S23-решение (`owner-decision-strategiya-s23-...`), турнир (`agent-tournament-trustworthy-real-apy.md`),
директива «оценивать стратегии по реальной доходности» (`owner-directive-head-of-investment-layer`).


---

## ✅ СВЕРКА 2026-08-17 (независимая) — ЗАКРЫТО

Проверено кодом и прогоном, не коммит-сообщением.

**п.1 — заявленный живой адаптер обязан импортироваться.**
`spa_core/tests/test_no_silent_mock_in_tournament.py::test_every_live_claim_actually_imports`
+ `test_live_claims_are_actually_measured`, с ДВУМЯ положительными контролями
(`test_broken_claim_is_detected_positive_control`,
`test_missing_attribute_claim_is_detected_positive_control`).

**п.2 — молчаливое глотание `ImportError` вокруг адаптера.** AST-храповик
`test_silent_swallow_ratchet_does_not_grow` + `test_baseline_matches_a_real_measurement`,
положительный контроль `test_silent_handler_is_detected_positive_control`, и обе
отрицательные стороны (`test_logging_handler_is_not_flagged`,
`test_reraising_handler_is_not_flagged`) — то есть храповик не красит логирующий
и перебрасывающий обработчики.

**п.3 — mock не ранжируется как живой.** В производителе
`spa_core/backtesting/mass_tournament.py`: `mock_provenance`/`is_mock_fed` (стр. 41),
пометка `mock_apy_fed` / `strategy_declares_mock` / `mock_tainted` (стр. 594–599),
`trusted_for_ranking` + отдельный `trusted_leaderboard` с собственным
`trusted_rank` (стр. 665–671), и в мете `mock_tainted_strategies` /
`mock_tainted_count` / `trusted_leaderboard_size` (стр. 743–745). Строка НЕ
удаляется из общего лидерборда — провенанс остаётся виден.
Тест: `test_mass_tournament_marks_and_excludes_mock_rows`.

**Защита самого honesty-gate.** `test_honesty_gate_still_fires_on_degenerate_data`
(gate нельзя тихо заглушить) + `test_time_is_an_input_not_the_wall_clock`.

**S23 проходит guard как живая:** `test_s23_declares_its_pt_liveness_honestly`
(и `test_stale_cache_does_not_outvote_the_predicate` — кэш `_pt_live` больше не
перебивает предикат).

**Дословный вывод моего прогона:**

```
$ python3 -m pytest spa_core/tests/test_no_silent_mock_in_tournament.py \
                   spa_core/tests/test_tournament_trust_honesty.py -q
29 passed in 47.95s
```

**Названо, не починено (к закрытию не относится):** оба файла сами дают
**6 отказов живого фида от 2 тестов** (`test_mass_tournament_marks_and_excludes_mock_rows` — 3,
`test_producer_stamps_trustworthy` — 3). Это предмет карточки
`agent-tests-reach-live-feed-222`, которая остаётся открытой.

**Что этой карточкой НЕ закрыто и живёт в соседней:** доверяемость самих чисел
турнира (реальные point-in-time ряды вместо литерала `MOCK_APY`) — карточка
`agent-tournament-trustworthy-real-apy`, п.2, остаётся открытой.
