---
trackerStatus:
  type: agent-task
title: "Повторяющийся сбой com.spa.orchestrator: exit_nonzero:1"
status: backlog
source: problem_store
created: 2026-10-14
acceptance_probe: "problem_absent:com.spa.orchestrator.exit_nonzero_1"
problem_id: com.spa.orchestrator.exit_nonzero_1
agent: com.spa.orchestrator
cause_code: "exit_nonzero:1"
problem_source: agent_health
---

## Что случилось
Условие `exit_nonzero:1` у `com.spa.orchestrator` повторилось 2+ раз за 7 дн. (источник: `agent_health`). Это Problem C6 (ADR-580 §C6), ключ `com.spa.orchestrator|exit_nonzero:1` — повторяющаяся причина, не разовый сбой.

## Почему это важно
Раньше повтор просто слал владельцу тот же алерт заново (замер A4_reliability.md: 14+14 CRIT/recovered флапов, 7 «bootstrap failed» за 35 минут). Эта карточка — ОДНА на `(com.spa.orchestrator, exit_nonzero:1)`: повтор инкрементирует `occurrences` в `data/problems.json`, а не плодит вторую карточку на тот же повод.

**Что это НЕ означает** (F10, ADR-580 §C6 REVIEW_1 amendment — прежняя формулировка здесь была неточной): сама карточка Telegram НЕ глушит, и её `status` на это не влияет. Тишину при повторе ТОЙ ЖЕ причины даёт `push_policy`'s собственный edge-триггер — и только когда зовущий передаёт УСТОЙЧИВЫЙ `dedup_key` (так с F1 устроен `agent_health_critical`: отпечаток строится из кода причины `cause_from_agent_issue`, а не из дрейфующего текста). У источника `agent_health` может быть своя, независимая проводка `push_policy` (другой `event_key`, свой `dedup_key` или вовсе прямой зов без дедупа) — закрыть ЭТУ карточку или оставить её открытой НЕ переключает тишину Telegram ни в одну сторону; проверять надо `push_state.json` того `event_key`, а не статус Problem.

## Что нужно сделать
Найти корневую причину и записать её (`spa_core.monitoring.problem_store.record_rca(problem_id='com.spa.orchestrator.exit_nonzero_1', cause=..., fix_ref=..., regression_test=...)`), затем починить так, чтобы условие перестало наблюдаться.

## Как понять, что готово
Проба `problem_absent:com.spa.orchestrator.exit_nonzero_1` отвечает `satisfied`: RCA записан И условие не наблюдалось 2 прогона(ов) подряд (`data/problems.json → problems["com.spa.orchestrator|exit_nonzero:1"]`).
