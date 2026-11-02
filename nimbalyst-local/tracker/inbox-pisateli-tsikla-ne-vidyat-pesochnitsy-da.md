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

---

## Перемер циклами #1014/#1015 (2026-11-02, ADR-903): класс ПОДТВЕРЖДЁН вторым независимым замером, половина его ЗАКРЫТА

**Эта карточка и была адресом находки.** Цикл #1014 нашёл то же самое заново и завёл
отдельную карточку (`inbox-pobochnye-pisateli-dnevnogo-tsikla-ne-po`); цикл #1015 при
разборе доски увидел совпадение предмета и **дубль снял**, а замер дописал СЮДА. Сторож
близнецов (`twin_key`, ADR-866) этого не поймал по построению: он сравнивает КЛЮЧ
содержимого, а два разных текста об одном предмете дают разные ключи. Поймала алфавитная
доска, то есть глаз, а не прибор — это названная граница, не упрёк.

### Что добавляет замер к записи 28.10

Зонд по трём дверям ФС (`os.replace` · `os.rename` · `builtins.open`/`io.open`) на живом
прогоне `test_cycle_write_interlock.py` снял СТЕК каждой записи. Все четыре записи
пришли из ОДНОГО теста — `test_flagged_run_writes_canonical_equity`, то есть из прогона
цикла с `allow_live_write=True`:

| файл `data/` | кадр записи |
|---|---|
| `adapter_status.json` | `cycle_runner.py:1103 run_cycle` → `monitoring/adapter_status_generator.py:1435 run_and_write` → `:1408 write` |
| `gap_monitor.json` | `cycle_runner.py:2805` → `cycle_reporting.py:750 run_post_cycle_advisory` → `gap_monitor.py:331 check_gaps` → `:335 _write` |
| `risk_alerts.json` | тот же путь → `gap_monitor.py:444 _upsert_gap_alert` → `:404 _save_alerts_doc` |
| `apy_milestone_log.json` | `cycle_runner.py:2805` → `cycle_reporting.py:569 _record_apy_milestone` → `analytics/apy_milestone_tracker.py:285 _save` |

**Поправка к диагнозу 28.10 в одной детали.** Запись «три писателя держат путь КОНСТАНТОЙ
модуля и песочницу не видят вовсе» верна для `apy_milestone_tracker`, но у `gap_monitor.py`
и `adapter_status_generator.py` дверь `SPA_DATA_DIR` (ADR-849 §2) **уже есть** — все
обращения `gap_monitor.py` к обоим своим файлам (строки 335/380/392/404) идут через
`_default_file(...)`. В прогоне они писали в дерево потому, что дверь **снимала фикстура
теста** (`monkeypatch.delenv(DATA_DIR_ENV)` в `fake_canonical`). Это и было проверено
дифференциально: дверь оставили — записей в `data/` дерева **6 → 0**.

### Что ЗАКРЫТО (ADR-903), а что осталось

- **ЗАКРЫТО:** сторона ТЕСТА. Песочница взводится, а не снимается; прогон 68 объявленных
  модулей больше не меняет ни одного git-tracked файла `data/` (код процесса 1 → 0,
  `git status -- data/` пусто против 19 файлов на чистом `origin/main`). Критерий
  «готово» из раздела выше для `test_cycle_write_interlock` ВЫПОЛНЕН.
- **ОСТАЛОСЬ ровно то, что эта карточка и просит (пп. 1–2):** цикл РАЗРЕШИЛ себе каталог
  (`_cycle_io.resolve_data_dir`, интерлок записи P3-2) и получил его, а побочные писатели
  этот разрешённый каталог **не получают вовсе** — каждый разрешает своё умолчание.
  Прогон с явным `--data-dir /somewhere` сегодня всё равно пишет `adapter_status.json`,
  `gap_monitor.json`, `risk_alerts.json` и `apy_milestone_log.json` в канонический
  каталог, МОЛЧА и с кодом возврата 0. Интерлок покрывает `equity` и НЕ покрывает эти
  четыре файла.
- **Население класса — нижняя граница:** четыре писателя суть те, кого видно на ОДНОЙ
  сцене, а не класс. Перемерить тем же зондом.

Правка затрагивает `paper_trading/cycle_runner.py`, `cycle_reporting.py`,
`gap_monitor.py`, `monitoring/adapter_status_generator.py` — **денежный путь**, вне
автономного мандата. Проба приёмки объявляется ДО работы той сессией, которая карточку
возьмёт (`.claude/rules/acceptance.md`).
