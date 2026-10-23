---
trackerStatus:
  type: agent-task
title: "Повторяющийся сбой com.spa.tier1_digest: no_run_since_reboot_(>_)_—_missed_first"
status: backlog
source: problem_store
created: 2026-10-22
acceptance_probe: "problem_absent:com.spa.tier1_digest.no_run_since_reboot_______missed_first"
problem_id: com.spa.tier1_digest.no_run_since_reboot_______missed_first
agent: com.spa.tier1_digest
cause_code: "no_run_since_reboot_(>_)_—_missed_first"
problem_source: agent_health
---

## Что случилось
Условие `no_run_since_reboot_(>_)_—_missed_first` у `com.spa.tier1_digest` повторилось 2+ раз за 7 дн. (источник: `agent_health`). Это Problem C6 (ADR-580 §C6), ключ `com.spa.tier1_digest|no_run_since_reboot_(>_)_—_missed_first` — повторяющаяся причина, не разовый сбой.

## Почему это важно
Раньше повтор просто слал владельцу тот же алерт заново (замер A4_reliability.md: 14+14 CRIT/recovered флапов, 7 «bootstrap failed» за 35 минут). Эта карточка — ОДНА на `(com.spa.tier1_digest, no_run_since_reboot_(>_)_—_missed_first)`: повтор инкрементирует `occurrences` в `data/problems.json`, а не плодит вторую карточку на тот же повод.

**Что это НЕ означает** (F10, ADR-580 §C6 REVIEW_1 amendment — прежняя формулировка здесь была неточной): сама карточка Telegram НЕ глушит, и её `status` на это не влияет. Тишину при повторе ТОЙ ЖЕ причины даёт `push_policy`'s собственный edge-триггер — и только когда зовущий передаёт УСТОЙЧИВЫЙ `dedup_key` (так с F1 устроен `agent_health_critical`: отпечаток строится из кода причины `cause_from_agent_issue`, а не из дрейфующего текста). У источника `agent_health` может быть своя, независимая проводка `push_policy` (другой `event_key`, свой `dedup_key` или вовсе прямой зов без дедупа) — закрыть ЭТУ карточку или оставить её открытой НЕ переключает тишину Telegram ни в одну сторону; проверять надо `push_state.json` того `event_key`, а не статус Problem.

## Что нужно сделать
Найти корневую причину и записать её (`spa_core.monitoring.problem_store.record_rca(problem_id='com.spa.tier1_digest.no_run_since_reboot_______missed_first', cause=..., fix_ref=..., regression_test=...)`), затем починить так, чтобы условие перестало наблюдаться.

## Как понять, что готово
Проба `problem_absent:com.spa.tier1_digest.no_run_since_reboot_______missed_first` отвечает `satisfied`: RCA записан И условие не наблюдалось 2 прогона(ов) подряд (`data/problems.json → problems["com.spa.tier1_digest|no_run_since_reboot_(>_)_—_missed_first"]`).
