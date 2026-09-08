---
trackerStatus:
  type: inbox
title: Храповик литеральных дат снова КРАСНЫЙ на main — два ДРУГИХ файла (cio_failure_modes, decision_reproducibility)
status: new
source: nimbalyst
created: 2026-09-08
domain: тесты / CI (НЕ money-path)
priority: high
---

## Что нашли (замер 2026-09-08, цикл #524)

`spa_core/tests/test_frozen_date_ratchet.py::test_no_new_file_joins_the_frozen_date_class`
падает **на чистом `origin/main` f1b44c8b5** (контрольное дерево `/tmp/spa_c524_ctl`,
приколотое к тому же sha, — тот же вердикт, тот же набор имён):

```
E   AssertionError: New test file(s) pin a literal date next to a freshness concept:
E       test_cio_failure_modes.py
E       test_decision_reproducibility.py
```

Это НЕ те два файла, что закрывала карточка `agent-frozen-date-ratchet-red-on-main`
(`done`, 05.08, там были `test_apy_series*.py`) — новое население того же класса.

## Почему это надо чинить, а не гасить

База храповика (`frozen_date_baseline.json`) может **только уменьшаться**
(`.claude/rules/deployment.md`). Дописать туда файл, чтобы покрасить CI зелёным, —
ровно тот дефект, ради которого храповик написан, и прямое нарушение инв. #16.

## Что делать

Для КАЖДОГО из двух файлов — порядок предпочтения из правила, сверху вниз:

1. **время — ВХОД:** функция, судящая о свежести, принимает `now=` (умолчание — реальные
   часы), тест передаёт фиксированный `now` И фиксированные отметки. Тогда файл выходит
   из класса пометкой `# FROZEN-DATE-OK: injected-clock — <как именно>`, и претензия
   ПРОВЕРЯЕТСЯ разбором AST (`test_injected_clock_claim.py`) — записка без инъекции
   не проходит;
2. относительные отметки `spa_core/tests/_freshness.py::ts(hours_ago=N)`;
3. литеральная дата только если сама дата является предметом — тогда
   `# FROZEN-DATE-OK: <причина>`.

## Как понять, что готово

`SPA_ENV=ci PYTHONHASHSEED=0 python3 -m pytest spa_core/tests/test_frozen_date_ratchet.py
spa_core/tests/test_injected_clock_claim.py -q` — зелено, и `frozen_date_baseline.json`
**не вырос ни на строку**.

## Образец в том же дереве

`spa_core/tests/test_office_absent_artifact_producer_aware.py` (доставлен ЭТИМ же
циклом, ADR-261) — приём №1 целиком: один якорь `self.now`, обе отметки сцены
(`os.utime` производителя и `generated_at` отчёта бегуна) строятся вычитанием от него,
ни одна проба не спрашивает стенных часов.
