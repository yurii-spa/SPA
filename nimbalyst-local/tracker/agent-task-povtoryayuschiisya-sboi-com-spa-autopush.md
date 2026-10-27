---
trackerStatus:
  type: agent-task
title: "Повторяющийся сбой com.spa.autopush: log_missing_(never_ran?)"
status: done
source: problem_store
created: 2026-10-15
acceptance_probe: "problem_absent:com.spa.autopush.log_missing__never_ran"
problem_id: com.spa.autopush.log_missing__never_ran
agent: com.spa.autopush
cause_code: log_missing_(never_ran?)
problem_source: agent_health
status_trail:
  - "2026-10-16T04:23:34.474039+00:00 backlog -> done · queue.set_status/closed_by:agent:arb-16.10/evidence:ложная тревога после перезагрузки 15.10, условие не наблюдается на коде ef317cbd (agent_health 01:22Z); RCA записан в data/problems.json, Problem CLOSED"
---

## Что случилось
Условие `log_missing_(never_ran?)` у `com.spa.autopush` повторилось 2+ раз за 7 дн. (источник: `agent_health`). Это Problem C6 (ADR-580 §C6), ключ `com.spa.autopush|log_missing_(never_ran?)` — повторяющаяся причина, не разовый сбой.

## Почему это важно
Раньше повтор просто слал владельцу тот же алерт заново (замер A4_reliability.md: 14+14 CRIT/recovered флапов, 7 «bootstrap failed» за 35 минут). Эта карточка — ОДНА на `(com.spa.autopush, log_missing_(never_ran?))`: повтор инкрементирует `occurrences` в `data/problems.json`, а не плодит вторую карточку на тот же повод.

**Что это НЕ означает** (F10, ADR-580 §C6 REVIEW_1 amendment — прежняя формулировка здесь была неточной): сама карточка Telegram НЕ глушит, и её `status` на это не влияет. Тишину при повторе ТОЙ ЖЕ причины даёт `push_policy`'s собственный edge-триггер — и только когда зовущий передаёт УСТОЙЧИВЫЙ `dedup_key` (так с F1 устроен `agent_health_critical`: отпечаток строится из кода причины `cause_from_agent_issue`, а не из дрейфующего текста). У источника `agent_health` может быть своя, независимая проводка `push_policy` (другой `event_key`, свой `dedup_key` или вовсе прямой зов без дедупа) — закрыть ЭТУ карточку или оставить её открытой НЕ переключает тишину Telegram ни в одну сторону; проверять надо `push_state.json` того `event_key`, а не статус Problem.

## Что нужно сделать
Найти корневую причину и записать её (`spa_core.monitoring.problem_store.record_rca(problem_id='com.spa.autopush.log_missing__never_ran', cause=..., fix_ref=..., regression_test=...)`), затем починить так, чтобы условие перестало наблюдаться.

## Как понять, что готово
Проба `problem_absent:com.spa.autopush.log_missing__never_ran` отвечает `satisfied`: RCA записан И условие не наблюдалось 2 прогона(ов) подряд (`data/problems.json → problems["com.spa.autopush|log_missing_(never_ran?)"]`).
