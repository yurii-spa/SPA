---
trackerStatus:
  type: inbox
title: scripts/system_health_check.py заменён монитором два месяца назад, но остался в дереве
status: new
source: nimbalyst
created: 2026-08-25
---

## Что случилось

`scripts/system_health_check.py` (269 строк, 15 проверок, `tests/test_system_health_check.py`)
**заменён** модулем `spa_core.monitoring.system_health_monitor`. Обёртки агентов говорят это
прямым текстом:

> `scripts/agent_system_health_morning.sh:9` — «The old target scripts/system_health_check.py only
> PRINTED PASS/WARN/FAIL and never wrote data/system_health.json → the file went days stale while
> this agent kept exiting 0 (the cry-wolf staleness bug)»

и обе (`morning` / `evening`) экзекают `spa_core.monitoring.system_health_monitor --run`.

**Карточка `inbox-hrapovik-nepodklyuchennyh-skriptov-schit-3` (замер #375) утверждала обратное** —
что у скрипта «вызывающие ЕСТЬ и настоящие: agent_system_health_morning.sh / evening.sh». Замер
цикла #379 это опроверг: имя стоит у обёрток в `#`-КОММЕНТАРИИ, а комментарии сканер снимает с
цикла #227. Единственное, что держало скрипт «подключённым», — груз пуша
`scripts/run_cpa_wave9_pushes.sh:42`. После починки детектора имя честно числится в
`revealed_by_stricter_detector`.

## Что нужно сделать

Дать скрипту поштучный вердикт и исполнить его:

- **вывести в `attic/`** (рекомендация: замена названа и работает, дублирующий страж, который
  никто не зовёт, — это ровно тот мёртвый код, ради которого заведён храповик), либо
- назвать причину, по которой он остаётся в `scripts/`.

Вывод в `attic/` тянет за собой: `tests/test_system_health_check.py` (24 теста) и упоминание в
`scripts/run_cpa_wave9_pushes.sh` / `CURRENT_STATE.md`. Удаление файла на origin — только через
`scripts/github_delete.py` (пушер удалять не умеет). Поэтому отдельной задачей, а не попутно.

## Как понять, что готово

`system_health_check` ушёл из `revealed_by_stricter_detector` (а не переехал в другой раздел),
тесты зелёные, `data/system_health.json` по-прежнему пишет монитор.

## Ссылка на источник

Цикл #379, карточка `inbox-hrapovik-nepodklyuchennyh-skriptov-schit-3`.
