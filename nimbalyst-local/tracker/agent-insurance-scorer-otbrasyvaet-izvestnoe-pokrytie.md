---
trackerStatus:
  type: agent-task
title: "protocol_insurance_scorer выбрасывает ИЗВЕСТНОЕ страховое покрытие и объявляет его нулём"
status: done
source: session-cycle-158
created: 2026-08-08
---

Найдено при исполнении ADR-070 п.15 (выдуманная казна 2% TVL). **Отдельный дефект того же
рода, намеренно НЕ чинившийся в том же цикле** — он двигает advisory-скоры всех протоколов,
а карточка владельца была про казну.

## Что именно

Контекст-ветка `spa_core/analytics/protocol_insurance_scorer.py::score` строит payload из
структурного профиля и жёстко проставляет:

```python
"has_insurance": False,
"insurance_coverage_pct": 0.0,
```

При этом структурная база **знает** покрытие: `generic_profile_for()` кладёт
`insurance_coverage_pct` (= `systemic["insurance_pct_of_tvl"]`) и `insurance_fund_usd`.
То есть модуль берёт измеренный факт и заменяет его нулём.

Это зеркало починенной казны: там выдумывали число, которого нет, здесь выбрасывают число,
которое есть. Оба варианта — утверждение о протоколе, ничем не подкреплённое.

## Почему это важнее, чем кажется

`_ModuleAdapter._coerce_score` не находит в результате ни одного ключа из `_SCORE_KEYS` и
падает в fallback «первый попавшийся `*_score`» — по порядку вставки это `coverage_score`.
Он равен 0.0 у КАЖДОГО протокола ⇒ агрегатор видит `risk_score = 0.0` для всех, и модуль
размечен `blind_equal` (`_protocol_blindness.py`), то есть исключён из composite и confidence.
Измерено циклом #158: aave_v3 / pendle / maple / morpho_steakhouse — все 0.0.

Иначе говоря, модуль слеп не «по природе задачи», а из-за двух подстановок подряд.

## Что сделать

1. Брать `insurance_coverage_pct` из профиля, `has_insurance` = покрытие > 0 (факт, не догадка).
2. Проверить, не начал ли `_coerce_score` читать осмысленную величину, и не переворачивает ли
   она знак (шкала модуля: больше = ЛУЧШЕ защищён; агрегатор ждёт больше = ОПАСНЕЕ). Возможно,
   правильный ответ — дать модулю явный ключ из `_SCORE_KEYS` с правильной полярностью.
3. Перегенерировать разметку слепоты **в sandbox-чекауте**
   (`python3 scripts/audit_protocol_blindness.py --emit-markup`) — файл помечен «не редактировать
   вручную». Если модуль перестал быть слепым, он вернётся в composite: это изменение
   advisory-сигнала, поэтому мерить до/после и писать замер в карточку.
4. Тесты в обе стороны + положительный контроль на нынешнем поведении.

## Как понять, что готово

`insurance_coverage_pct` в результате контекст-ветки различается между протоколами и совпадает
с `systemic.insurance_pct_of_tvl` базы; разметка слепоты перегенерирована; замер влияния на
composite приложен.

---

## 🔎 СВЕРКА 2026-08-17 (код + прогон) → `done`

Критерий карточки состоит из трёх утверждений; проверены все три.

**1. Покрытие берётся из базы и различается между протоколами.**
`spa_core/analytics/protocol_insurance_scorer.py`, контекст-ветка `score()` (строки 211–225):
`_cov_pct = float(_p["insurance_coverage_pct"])`, `"has_insurance": _cov_pct > 0.0` —
литералов `False` / `0.0` в payload больше нет. Прогон:
`python3 -m pytest spa_core/tests/test_insurance_known_coverage.py spa_core/tests/test_protocol_insurance_scorer.py -q`
→ `102 passed, 12 subtests passed in 0.81s`. Внутри — положительные контроли
`test_payload_coverage_matches_systemic_field` (совпадение с `systemic.insurance_pct_of_tvl`),
`test_has_insurance_is_a_fact_not_a_literal`, `test_coverage_differs_between_protocols`,
`test_coverage_score_no_longer_constant_zero`.

**2. Полярность и ключ (п.2 карточки).** Добавлен явный `risk_score = 100 − total`
(строка 331) — ключ из `_SCORE_KEYS`, поэтому `_coerce_score` больше не падает в fallback
«первый попавшийся `*_score`». Держат `test_result_carries_a_known_score_key`,
`test_risk_score_is_inverted_protection`, `test_polarity_higher_is_more_dangerous`,
`test_coercion_no_longer_falls_back_to_coverage_score`.

**3. Разметка слепоты ПЕРЕГЕНЕРИРОВАНА — и это видно в файле, а не в отчёте.**
На момент написания `test_insurance_known_coverage.py` она ещё не была обновлена (об этом честно
сказано в его докстринге), но перегенерация состоялась позже тем же днём:
`spa_core/analytics/_protocol_blindness.py` — `AUDIT_GENERATED_AT = "2026-08-17T19:20:18.403861Z"`,
и строки `"protocol_insurance_scorer": "blind_equal"` в `PROTOCOL_BLIND_DETAIL` **больше нет**
(проверено `grep`; удаление видно дифом `9fc702a10`, где `AUDIT_GENERATED_AT` сменился
с `2026-08-05T10:53` на `2026-08-17T18:31`). `spa_core/analytics/signal_aggregator.py:64`
исключает из composite ровно `PROTOCOL_BLIND_MODULES = frozenset(PROTOCOL_BLIND_DETAIL)` ⇒
модуль вернулся в сводный балл.

**Замер влияния (для протокола).** Модульный: было `risk_score = 0.0` у всех протоколов
вселенной — стало aave_v3 67.7143 · pendle 89.3734 · maple 90.2306 · morpho_steakhouse 89.0877 ·
compound_v3 68.2857 (воспроизводится тестами `test_context_scores_differ_across_audit_trio`,
`test_every_known_protocol_scores_and_universe_is_not_constant`). Сдвиг СВОДНОГО балла
(+0.5…+0.6 при неизменном confidence) взят из записи о перегенерации разметки `9fc702a10`
и мной заново НЕ измерялся — composite-прогон пишет в `data/`, которое эта сверка не трогает.
Кода не менял.
