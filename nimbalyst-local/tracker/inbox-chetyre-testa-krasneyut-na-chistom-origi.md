---
trackerStatus:
  type: inbox
title: Четыре теста краснеют на чистом origin/main bbfcc9724 — храповик наблюдения отстал на три площадки + джоба CI без истории
status: new
source: nimbalyst
created: 2026-10-08
---

## Замер (цикл #808, 08.10, ДВА дерева)

Четыре теста краснеют на ЧИСТОЙ копии `origin/main` `bbfcc9724` — измерено в отдельном
дереве (`git worktree add origin/main`), ни одно падение не внесено циклом #808. Набор
падений в рабочем дереве цикла и в чистом совпадает пофамильно.

| тест | файл |
|---|---|
| `test_tree_introduces_no_new_member` | `spa_core/tests/test_absent_observation_ratchet.py` |
| `test_ceiling_is_reanchoring_not_growth` | там же |
| `test_baseline_and_tree_agree_member_for_member` | там же |
| `test_every_pytest_job_declares_full_history` | `spa_core/tests/test_declared_git_environment.py` |

### 1–3. Храповик отсутствующего наблюдения (инв. #17): база отстала на ТРИ площадки

```
сигнал or_falsy: в дереве 151, в базе 148; только в дереве:
  spa_core/monitoring/reachability_of_the_rest.py:ad75c5b822d6#0
  spa_core/trading_research/forward.py:67566b8990d7#0
  spa_core/trading_research/forward.py:b4c5db9e03cb#0
только в базе: []
```

Три площадки `or_falsy` приехали с волнами, которые базу не перемеряли:
`reachability_of_the_rest.py` — коммит `58e0e0dfd` (ADR-566, G98.2), `forward.py` —
`9b09e7d0b` (ADR-640, CAPITAL-SOURCES-01). «Только в базе: []» значит, что база не
выросла и не сжалась — она просто не знает о трёх новых.

⚠️ **Дописывать в базу, чтобы погасить падение, ЗАПРЕЩЕНО** (инв. #17 прямо: «база может
только уменьшаться; дописывать в неё, чтобы погасить падение, запрещено»). Правильный ход —
посмотреть на три площадки и либо убрать `or`-подстановку (тогда база сама не растёт), либо
записать решение о каждой с обоснованием. Это НЕ переанкеровка потолка.

### 4. Джоба CI гоняет pytest без истории репозитория

```
ci-lite.yml:syntax-and-import — fetch-depth не объявлена (умолчание 1)
```

Тот самый класс из `.claude/rules/deployment.md` («GIT-ОКРУЖЕНИЕ в тестах»): тесты, чей
предмет — настоящая история доставки, без истории честно отказывают и не мерят НИЧЕГО.
Лечится одной строкой `fetch-depth: 0` у `actions/checkout` в этой джобе.

## Что сделать

Автономная задача агента: hardening, не owner-gated, risk-логики не касается. Три
площадки `or_falsy` разобрать поимённо (каждая — своё решение, не групповое), джобе
`ci-lite.yml:syntax-and-import` объявить полную историю.

## Как понять, что готово

На чистой копии `origin/main` обе батареи зелёные, и база `or_falsy` при этом НЕ выросла.
