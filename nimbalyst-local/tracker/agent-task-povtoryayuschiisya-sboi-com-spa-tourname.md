---
trackerStatus:
  type: agent-task
title: "Повторяющийся сбой com.spa.tournament_engine: stale_log"
status: done
source: problem_store
created: 2026-10-15
acceptance_probe: "problem_absent:com.spa.tournament_engine.stale_log"
problem_id: com.spa.tournament_engine.stale_log
agent: com.spa.tournament_engine
cause_code: stale_log
problem_source: agent_health
status_trail:
  - "2026-10-16T04:24:16.274541+00:00 backlog -> done · queue.set_status/closed_by:agent:arb-16.10/evidence:ложная тревога после перезагрузки 15.10, условие не наблюдается на коде ef317cbd (agent_health 01:22Z); RCA записан в data/problems.json, Problem CLOSED"
---

## Что случилось
Условие `stale_log` у `com.spa.tournament_engine` повторилось 2+ раз за 7 дн. (источник: `agent_health`). Это Problem C6 (ADR-580 §C6), ключ `com.spa.tournament_engine|stale_log` — повторяющаяся причина, не разовый сбой.

## Почему это важно
Раньше повтор просто слал владельцу тот же алерт заново (замер A4_reliability.md: 14+14 CRIT/recovered флапов, 7 «bootstrap failed» за 35 минут). Эта карточка — ОДНА на `(com.spa.tournament_engine, stale_log)`: повтор инкрементирует `occurrences` в `data/problems.json`, а не плодит вторую карточку на тот же повод.

**Что это НЕ означает** (F10, ADR-580 §C6 REVIEW_1 amendment — прежняя формулировка здесь была неточной): сама карточка Telegram НЕ глушит, и её `status` на это не влияет. Тишину при повторе ТОЙ ЖЕ причины даёт `push_policy`'s собственный edge-триггер — и только когда зовущий передаёт УСТОЙЧИВЫЙ `dedup_key` (так с F1 устроен `agent_health_critical`: отпечаток строится из кода причины `cause_from_agent_issue`, а не из дрейфующего текста). У источника `agent_health` может быть своя, независимая проводка `push_policy` (другой `event_key`, свой `dedup_key` или вовсе прямой зов без дедупа) — закрыть ЭТУ карточку или оставить её открытой НЕ переключает тишину Telegram ни в одну сторону; проверять надо `push_state.json` того `event_key`, а не статус Problem.

## Что нужно сделать
Найти корневую причину и записать её (`spa_core.monitoring.problem_store.record_rca(problem_id='com.spa.tournament_engine.stale_log', cause=..., fix_ref=..., regression_test=...)`), затем починить так, чтобы условие перестало наблюдаться.

## Как понять, что готово
Проба `problem_absent:com.spa.tournament_engine.stale_log` отвечает `satisfied`: RCA записан И условие не наблюдалось 2 прогона(ов) подряд (`data/problems.json → problems["com.spa.tournament_engine|stale_log"]`).
