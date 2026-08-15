---
trackerStatus:
  type: inbox
title: Три рабочих дерева держат недоставленную работу — поднять или осознанно списать
status: new
created: 2026-08-14
---

## Что измерено (цикл #230, 2026-08-14)

Уборка мёртвых деревьев (`scripts/reap_stale_worktrees.py`, шаг 0г) сняла 43 регистрации из 70.
Остальные остались с НАЗВАННОЙ причиной, и у трёх причина одна: **там лежит работа, которой на
`origin/main` нет вовсе** (вердикт `absent`/`unique` — правило такие деревья не снимает).

- `/private/tmp/spa_wt_rnd49` — `scripts/edge_criterion_consensus.py` и
  `spa_core/tests/test_edge_criterion_consensus.py`: на origin нет НИ ОДНОГО из двух.
- `/private/tmp/spa_wt_c196` — `nimbalyst-local/tracker/own-rnd-duty-is-concentration-adr055.md`
  и `owner-decision-morfo-40-knigi-pri-propazhe-dannyh-podst.md`: карточки, которых нет в очереди
  на origin. Одна из них — про ДЕНЬГИ (40 % книги при пропаже данных).
- `/private/tmp/spa_wt_c208` — правка `docs/ORCHESTRATOR_PROTOCOL.md`,
  `spa_core/tests/test_consume_office_reports.py` и карточка
  `inbox-shag-0-ofis-iz-worktree-dokladyvaet-ne-p`. **Осторожно:** цикл #230 правил тот же
  протокол (шаг 0г) — переносить содержимое поверх нельзя, только сливать осознанно.

Ещё несколько `.claude/worktrees/*` держат `absent`-файлы (`spa_core/paper_trading/*.py` — 27
модулей аналитики; `spa_core/adapters/{radiant_arbitrum,gmx_glp_arbitrum}_adapter.py`, которые
ADR-070.17-18 велел вывести). Их разбирать отдельно и позже: часть — намеренно НЕ доставленное.

## Что сделать

1. По каждому дереву — порядок шага 0a: `ps -p <pid>` · announce-лог · **отчёту мёртвой сессии
   не верить** (перепроверять прогонами, а не читать её STATE).
2. Решить пофайлово: поднять (тесты зелёные → пуш) либо осознанно списать с причиной в журнале.
3. После подъёма дерево снимается обычным правилом (`reap_stale_worktrees.py --apply`).

## Границы

Карточки владельца из `spa_wt_c196` — **не исполнять и не закрывать**: их путь —
`needs-owner` + notify (инв. #14). Ничего из money-path сюда не входит.

## Как понять, что готово

`python3 scripts/reap_stale_worktrees.py` не показывает ни одного дерева с причиной
«здесь может лежать НЕДОСТАВЛЕННАЯ работа» — либо у каждого оставшегося есть запись в журнале,
почему списано.

Родитель: цикл #230 (карточка `inbox-shag-0a-povtoryaet-odni-i-te-zhe-6-nahod`).
