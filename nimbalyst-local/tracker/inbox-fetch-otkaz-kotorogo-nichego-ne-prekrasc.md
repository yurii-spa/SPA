---
trackerStatus:
  type: inbox
title: "fetch, отказ которого ничего не прекращает: четыре мутирующих зова работают на кэше неизмеренного возраста"
status: new
source: nimbalyst
created: 2026-09-12
priority: high
domain: delivery
---

Замер ADR-361 (цикл #582, прибор `scripts/shell_git_ref_provenance.py`): из 12 зовов,
читающих `origin/main`, у **семи** свежесть ссылки не доказана, и **четыре** из них
МУТИРУЮТ дерево или историю.

`refs/remotes/origin/main` — локальная ссылка: она хранит значение и не хранит ни
возраста, ни провенанса. `git fetch`, чей код возврата не проверен, при недоступной
сети оставляет её прежней, а следующая строка читает кэш, ничего об этом не зная.
Возраст кэша замерен по `git reflog` прод-дерева (2017 записей, 18.06–12.09): медиана
0.26 ч, p90 1.46 ч, **максимум 224.5 ч — 9.4 суток**.

| файл | зовы | что происходит при отказе `fetch` |
|---|---|---|
| `scripts/git_autopush.sh` | 121, 128, 133, 136, 139 | в коде написано вслух: `log "⚠️ Fetch failed (network?), proceeding with cached remote state"`, затем три `reset --hard origin/main` и `rebase origin/main`. Агент работает ежечасно под launchd |
| `scripts/agent_novel_edge_rnd.sh` | 58 | `fetch \|\| echo WARN`, затем `git show origin/main:docs/DYNAMIC_LEVERAGE_GUARDIAN.md` — номер следующей идеи берётся из кэша. Скрипт написан ПОСЛЕ инцидента 29.07, когда две сессии взяли один номер |
| `scripts/session_index_lag_warning.sh` | 19 | `fetch 2>/dev/null`, затем `rev-list --count HEAD..origin/main` — «отстаёт на N коммитов» может быть посчитано по стухшему кэшу и подано как измеренное |

**Как надо** — выход из класса уже написан в самом наборе: `code_sync_from_origin.sh`
(`if ! git fetch …; then write_status FETCH_FAILED; return 0; fi`) и
`agent_system_briefing.sh` (`git fetch … && git reset …`). Обе формы прибор признаёт
доказанными.

## Что сделать

1. `git_autopush.sh`: при отказе `fetch` — НЕ продолжать на кэше. Либо выход с
   названной причиной, либо явный режим «работаю на кэше возрастом N» с записью
   возраста (`git reflog show refs/remotes/origin/main -1 --date=iso`), а не молчаливое
   продолжение. Это путь доставки — менять только с разрешения владельца
   (`.claude/rules/deployment.md` §6).
2. `agent_novel_edge_rnd.sh`, `session_index_lag_warning.sh`: отказ `fetch` обязан
   давать «НЕ ИЗМЕРЕНО» с причиной, а не число из кэша (инвариант #17).
3. После починки **уменьшить** `scripts/shell_git_ref_provenance_baseline.json`.
   База может только уменьшаться; дописывать в неё запрещено.

Соседняя карточка того же набора, но про ДРУГОЙ вопрос (каталог, а не ссылка):
`inbox-katalog-dostavki-beretsya-iz-okruzheniya`.
