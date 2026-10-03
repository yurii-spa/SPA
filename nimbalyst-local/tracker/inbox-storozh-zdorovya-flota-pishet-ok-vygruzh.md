---
trackerStatus:
  type: inbox
title: Сторож здоровья флота пишет OK выгруженному дневному циклу — узнаёт о пропуске только через сутки
status: new
source: nimbalyst
created: 2026-09-29
---

## Что нашли (ежедневный аудит 90 %, 2026-09-29 08:10Z)

`data/agent_health.json` (07:19Z) сообщает о `com.spa.daily_cycle`:
`status: OK, loaded: False, log_age_min: 1518`. Агента в `launchctl list` НЕТ
(`launchctl print gui/501/com.spa.daily_cycle` → «Could not find service»),
дневной цикл 29.09 в 08:00 local НЕ запускался, `cycle_gap_state` — 26,1 ч без цикла.
Тем временем `com.spa.mission_tick` в том же положении (не загружен) — CRITICAL.

## Почему так

`spa_core/monitoring/agent_health_monitor.py:171-181, 725-732`: у календарных агентов
(CAT_DAILY/WEEKLY) отсутствие в `launchctl list` считается нормальным простоем между
запусками («correctly EXIT between scheduled runs and need not be resident»). На этом хосте
посылка ОПРОВЕРГНУТА замером: загруженные календарные агенты висят в списке и между
запусками (`- 0 com.spa.digest_daily`, `- 0 com.spa.daily_backup`, `- 0 com.spa.monthly_statement`,
`- 1 com.spa.weekly_backup`). Отсутствие в списке = агент ВЫГРУЖЕН и больше не запустится.
Сторож узнаёт об этом только по возрасту лога: 26 ч → WARNING, т.е. через сутки после
первого пропущенного цикла, и понижённым голосом.

Поймал выгрузку другой сторож — `architecture_conformance` (находка `B1:dead:com.spa.daily_cycle`,
карточка `owner-decision-kritichnaya-nahodka-petli-com-spa-daily.md`, владелец принял 29.09 06:48Z).
Этот дефект — отдельный: сторож здоровья флота fail-OPEN на самом важном агенте.

## Что сделать

Не «загружен ли сейчас процесс», а «есть ли служба в домене launchd»: календарный агент,
отсутствующий в `launchctl list`, — CRITICAL `not loaded in launchctl` (как у resident-категорий).
Прежний ложный CRITICAL, ради которого вводилось исключение, перемерить дифференциально на
хосте (какие календарные агенты сегодня отсутствуют в списке и почему) — не ослаблять молча.
Положительный контроль: воспроизведение 29.09 (daily, loaded False, лог 25 ч) ⇒ CRITICAL.
