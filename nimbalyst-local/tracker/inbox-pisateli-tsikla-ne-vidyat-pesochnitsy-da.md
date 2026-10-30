---
trackerStatus:
  type: inbox
title: Писатели цикла не видят песочницы data_dir — прогон тестов меняет git-tracked data/ (пять модулей, четыре файла)
status: new
source: nimbalyst
created: 2026-10-28
priority: medium
finding_adr: ADR-850
intake_kind: task
---

## Что случилось и почему это важно

Прогон тестов меняет ЖИВОЕ состояние `data/`, которое лежит в git. Замер цикла #969
(дерево на чистом `origin/main 39fb2db91`): ПЯТЬ модулей набора трогают одни и те же
четыре отслеживаемых файла —

```
spa_core/tests/test_cio_trial_grant.py        data/adapter_status.json
spa_core/tests/test_cycle_runner.py           data/apy_milestone_log.json
spa_core/tests/test_cycle_runner_policy_gate.py   data/gap_monitor.json
spa_core/tests/test_risk_policy_gate.py       data/risk_alerts.json
spa_core/tests/test_cycle_derisk_e2e.py
```

Строка заказа G848 п. 5 числила в этом классе ОДИН модуль (`test_cio_trial_grant`) —
класс шире замера, которым его описали.

Причина одна и она не в тестах: три писателя держат путь КОНСТАНТОЙ модуля и
песочницу `data_dir` не видят вовсе —
`spa_core/paper_trading/gap_monitor.py` (`GAP_STATUS_FILE`/`RISK_ALERTS_FILE` от
`DATA_DIR`), `spa_core/analytics/apy_milestone_tracker.py` (`OUTPUT_PATH =
"data/apy_milestone_log.json"`), `spa_core/monitoring/adapter_status_generator.py`
(`run_and_write()` без каталога). Цикл зовёт их на `write=True`, и песочница
`run_cycle(data_dir=…)` до них не доходит.

В прод-дереве это ЖИВОЕ состояние; в рабочем — «чистое дерево» перестаёт быть
сигналом, а сторож `tracked_write_guard` краснеет на каждом прогоне этих модулей.

## Что от тебя нужно

1. Провести каталог данных ДО писателя: `gap_monitor.check_gaps(data_dir=…)`,
   `ApyMilestoneTracker(data_dir=…)`, `adapter_status_generator.run_and_write(ddir=…)`
   — умолчание прежнее (прод-`data/`), цикл передаёт свой `ddir`.
2. Половина инъекции — та же бомба (`.claude/rules/deployment.md`): провести ВСЕ
   двери писателя, а не одну, и проверить, что при переданном каталоге живой файл
   НЕ меняется (сравнение `stat` до/после, как у самого сторожа).
3. База `spa_core/tests/tracked_write_baseline.json` НЕ дописывается (инв. #16) —
   после починки она УМЕНЬШАЕТСЯ.

## Как понять, что готово

`SPA_ENV=ci python3 -m pytest spa_core/tests/test_cio_trial_grant.py
spa_core/tests/test_cycle_runner.py spa_core/tests/test_cycle_runner_policy_gate.py
spa_core/tests/test_risk_policy_gate.py spa_core/tests/test_cycle_derisk_e2e.py -q`
не печатает раздела «tests changed git-tracked state» ни одной строкой, и
`git status --short data/` после прогона пуст.

## Что будет после

Красный сторож перестаёт быть фоном, и «чистое дерево» снова становится сигналом —
в том числе для сверки байтов доставки (ADR-774) и для шага 0a.
