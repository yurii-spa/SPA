---
trackerStatus:
  type: inbox
title: "Храповик замороженных дат КРАСЕН на чистом origin/main: test_record_survival_census.py принёс литеральную дату"
status: new
source: nimbalyst
created: 2026-10-10
---

## Замер (цикл #823, 10.10, ДВА дерева)

Храповик замороженных дат КРАСЕН на **чистой копии `origin/main` `a326d063e`** — измерено в
отдельном дереве (`git worktree add origin/main`); файл внесён не этим циклом.

```
test_no_new_file_joins_the_frozen_date_class
  New test file(s) pin a literal date next to a freshness concept:
    test_record_survival_census.py
```

## Почему это важно

Тест с литеральной датой рядом с понятием свежести начинает падать просто от того, что
сдвинулся календарь, — по причине, не имеющей отношения к проверяемому поведению
(`.claude/rules/deployment.md`, «Время в тестах»). Пока он красен, его собственный предмет
(перепись переживания записи, ADR-534) не проверяет НИЧЕГО: красный тест читается как
«сломано», и настоящая поломка в нём была бы неотличима от сдвига календаря.

⚠️ **Дописывать файл в `frozen_date_baseline.json` ЗАПРЕЩЕНО** — база может только
уменьшаться (инв. #16). Выход ровно один из трёх, по порядку предпочтения правила:

1. **инъекция часов** — передать `now=` И отметки, выведенные от ТОГО ЖЕ якоря, и объявить
   это строкой `# FROZEN-DATE-OK: injected-clock — <как>`. Претензию сверяет AST
   (`spa_core/tests/test_injected_clock_claim.py`), записка без инъекции не проходит;
2. относительные отметки — `spa_core.tests._freshness.ts(hours_ago=N)`;
3. если дата САМА является предметом — `# FROZEN-DATE-OK: <причина>`.

Образец выхода №1, сделанный тем же циклом: `spa_core/tests/test_receipt_channel_cost.py`
(ADR-684) — якорь уезжает входом в `build_report(..., now=NOW)` и `run(..., now=NOW)`, обе
стороны закреплены от одного якоря.

## Как понять, что готово

`SPA_ENV=ci python3 -m pytest spa_core/tests/test_frozen_date_ratchet.py spa_core/tests/test_injected_clock_claim.py -q`
зелёный БЕЗ дописывания в базу.

---

## ЗАМЕР цикла #878 (2026-10-16): в класс вошёл ВТОРОЙ файл, и карточек на класс уже ТРИ

Замерено на чистой вершине (зеркало `origin/main` `f3931465f`, ни одной своей правки):

```
SPA_ENV=ci PYTHONHASHSEED=0 python3 -m pytest spa_core/tests/test_frozen_date_ratchet.py -q
→ 1 failed, 22 passed
E  New test file(s) pin a literal date next to a freshness concept:
E      test_mission_ui_static.py
```

Файл принесён **не этим классом работ**: `spa_core/tests/test_mission_ui_static.py` появился
коммитом `2df987cec` (15.10 22:11, «Director OS release, ADR-762»). То есть красный держится
на origin с вечера 15.10 и к `test_record_survival_census.py` из шапки этой карточки не
относится — это ВТОРОЙ житель класса одновременно.

**Главное здесь не файл, а счёт карточек.** На один храповик открыто **три** карточки в
статусе `new`, каждая про свой файл: `inbox-hrapovik-literalnyh-dat-krasen-na-origin`
(`test_cio_failure_modes`, `test_decision_reproducibility`), эта
(`test_record_survival_census`) и `inbox-hrapovik-dat-krasnyi-na-origin-main-u-dv` (пометка
`FROZEN-DATE-OK` вне комментария). Четвёртую по новому файлу я НЕ завёл намеренно: это была
бы ровно та очередь из однотипных карточек, которой храповик глохнет. Вред уже не в
литеральной дате — вред в том, что **красный стал постоянным, и поэтому его перестают читать**
(тот же механизм, что у ⛔-строки моста, висевшей 41 сутки).

Цикл #878 этот красный НЕ гасил и не трогал (инв. #16); в своём предписанном прогоне назвал
его чужим и предсуществующим, измерив дифференциально на вершине без своих правок.
