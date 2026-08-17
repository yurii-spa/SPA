---
trackerStatus:
  type: agent
title: S76 угадывает единицу измерения доходности по величине числа — настоящие 0.5 % превращаются в 50 %
status: done
source: находка цикла #121 при работе над AUD-18 (2026-08-05)
created: 2026-08-05
priority: medium
domain: advisory-стратегия (турнир), НЕ RiskPolicy и НЕ money-path
---

## Что найдено

`spa_core/strategies/s76_concentrated_lp.py::compute_weighted_apy`:

```python
raw = apy_data.get(protocol, FALLBACK_APY.get(protocol, 0.0))
apy_pct = float(raw)
# aerodrome_usdc_lp fallback is stored as decimal (0.085) not percent
if protocol == "aerodrome_usdc_lp" and apy_pct < 1.0:
    apy_pct = apy_pct * 100.0
```

Единица измерения определяется **величиной числа**, а не контрактом. Следствие: живая
доходность пула в 0.5 % годовых (в процентах — именно так требует докстринг метода)
читается как 0.005 в долях, домножается на 100 и даёт 50 %. Смешанная доходность
стратегии при этом выходит ~30.9 % вместо честных ~1.2 %.

Это ровно тот класс, который в проекте уже закрывали: правдоподобное ЧИСЛО вместо отказа.
Причём закрывали его **в этом же репозитории и именно этой формулировкой** —
`spa_core/adapters/apy_contract.py` заводился с явной пометкой: «replaces the old
`v < 1.0 → ×100` magnitude heuristic (which read a true sub-1% percent APY as 100x too
large)». S76 остался с эвристикой, от которой ушли адаптеры.

## Почему не починено сразу

Правка меняет ЧИСЛО, которое стратегия публикует в турнир, — это не рефакторинг.
Автономный цикл такое не двигает молча. Поведение зафиксировано тестом как есть
(`spa_core/tests/test_s76_concentrated_lp.py::test_sub_one_percent_lp_apy_is_inflated_x100_CURRENT_BEHAVIOUR`),
чтобы изменение стало ОСОЗНАННЫМ: любой, кто поправит формулу, увидит красный тест
с объяснением, а не тихо сдвинет публикуемую доходность.

## Что предлагается сделать

Убрать угадывание и брать доходность через канонический контракт
(`spa_core/adapters/apy_contract.py`), как это уже делают адаптеры и S22: единица
объявлена, конверсия ровно одна, отсутствие данных = отказ, а не подстановка.

Отдельно проверить остальные стратегии на ту же эвристику — S76 вряд ли единственная
(в S22 её уже сняли, значит класс известен и мигрирован не полностью).

## Как понять, что готово

- `compute_weighted_apy` больше не зависит от величины входного числа;
- тест `..._CURRENT_BEHAVIOUR` заменён на тест нового контракта (обе стороны: настоящие
  0.5 % остаются 0.5 %; десятичный вход отвергается или конвертируется по объявленному правилу);
- прогон турнира до/после показывает, какие именно опубликованные числа сдвинулись.

## Ссылки

- Родительская задача: `agent-aud18-strategy-unit-tests.md`
- Тот же класс, уже закрытый в адаптерах: `spa_core/adapters/apy_contract.py`


---

## ✅ СВЕРКА 2026-08-17 (независимая) — ЗАКРЫТО

Три критерия карточки проверены по отдельности.

**(а) `compute_weighted_apy` больше не зависит от величины входного числа.**
`spa_core/strategies/s76_concentrated_lp.py:151-201`: эвристики `if protocol ==
"aerodrome_usdc_lp" and apy_pct < 1.0: apy_pct *= 100` в файле НЕТ. Вместо неё —
объявленная единица модуля `APY_UNIT` и одна конверсия через
`apy_decimal_from_declared(candidate, APY_UNIT, protocol=protocol)`
(`spa_core/adapters/apy_contract.py`); значение вне sane-band ⇒ **fail-closed в
объявленный `FALLBACK_APY`**, не домножение. Конверсия доля→процент ровно одна —
`return total_decimal * 100.0`.

**(б) `..._CURRENT_BEHAVIOUR` заменён тестом контракта, обе стороны.**
`spa_core/tests/test_s76_concentrated_lp.py`: старого имени в файле нет;
на его месте `test_true_sub_one_percent_apy_stays_sub_one_percent` (докстринг
прямо называет замену) — проверяет ОБЕ стороны: честные 0.5 % у T1-ноги проходят
немасштабированными, и LP с честными 0.5 % даёт lp_off-бленд 3.43 %, а не ~30.9 %.
Вторая сторона контракта — `test_percent_leak_rejected_to_fallback_never_rescaled`
(3.5/12.0 в долевом контракте отвергается в fallback, НИКОГДА не пересчитывается).
Плюс `test_live_decimal_values_blended_and_converted_once` — на неисправленном
коде он красный (в докстринге записано ожидаемое значение 7.21 старой эвристики).

Дословный вывод:

```
$ python3 -m pytest spa_core/tests/test_s76_concentrated_lp.py -q
30 passed, 4 subtests passed in 0.26s
```

**(в) «прогон турнира до/после — какие опубликованные числа сдвинулись».**
Ответ измерен, а не прогнан: **ни одного.** `compute_weighted_apy` не вызывается
НИКЕМ за пределами самих модулей стратегий и их тестов
(`grep -rln "compute_weighted_apy"` даёт только `spa_core/strategies/s*.py`),
а турнир зовёт исключительно `get_allocation` / `allocate`
(`spa_core/backtesting/mass_tournament.py:432`) и никакой рефлексии по методам
не делает. Опубликованный радиус правки — ноль.

**Остаток класса НАЗВАН (не входит в эту карточку).** Живые магнитудные эвристики
того же вида, не тронутые: `price_feeds/protocol_direct_feed.py:246,293` ·
`adapters/pendle_pt_adapter.py:310` · `adapters/ethena_susde_adapter.py:128` ·
`bee/backtest_live_fit.py:429,529` · `bee/walk_forward.py:175` ·
`strategies/s_basis.py:169` · `monitoring/bts_monitor.py:256` ·
`monitoring/series_anomaly_detector.py:134`. Плюс замер: **36 из 36 адаптеров
`ADAPTER_REGISTRY` единицу ещё не объявляют** — это отдельная карточка.
