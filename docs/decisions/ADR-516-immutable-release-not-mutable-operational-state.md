# ADR-516 — Immutable release ≠ mutable operational state; acceptance models interpreter-mediated launch and the fleet interpreter

> **Статус:** accepted · 2026-09-29 · следует за ADR-500 (production activation boundary), ADR-475/ADR-492 (durable/mission state root).

## Контекст

Первая доброкачественная канарейка trusted-bootstrap (2026-09-29) исполнила
`spa_core.monitoring.deployment_acceptance` по цепочке
`/usr/bin/python3 -I <trusted launcher> → recovered 3.13 → approved release` и
завершилась `2 / CRITICAL`. Разбор показал ЧЕТЫРЕ дефекта, из них три — дефекты
самого прибора приёмки, а не флота:

1. **Запись в неизменяемый релиз.** Приёмка клала квитанцию в `releases/<sha>/data`
   (это дерево — `_REPO_ROOT` исполняемого релиза). Релиз root-owned read-only →
   `Errno 13`. Релиз ОТВЕРГ запись правильно; писать туда было неверно.
2. **Ложное «не исполняется» у launcher.** `check_entrypoints` требовал `+x` у
   `.py`-аргумента `ProgramArguments`. Но launchd исполняет `argv[0]`
   (`/usr/bin/python3`), а `.py` python ЧИТАЕТ. Неизменяемый launcher имеет режим
   `0444` намеренно — и приёмка объявляла канарейку мёртвой.
3. **Ложное «нет uvicorn».** Проба импорта цели агента шла `sys.executable` —
   доверенным stdlib-only 3.13, которым исполнялась сама приёмка. Агенты же
   запускаются на miniconda (`agent_template.sh`), где uvicorn 0.49.0 СТОИТ. Прибор
   спросил чужую среду.
4. **Ложное «протухло».** Свежесть артефактов мерилась по `releases/<sha>/data` —
   замёрзшей копии, свежей ПО ПОСТРОЕНИЮ (mtime = момент материализации релиза).

## Решение

**Правило (главное): НЕИЗМЕНЯЕМЫЙ РЕЛИЗ ≠ ИЗМЕНЯЕМОЕ ОПЕРАЦИОННОЕ СОСТОЯНИЕ.**
Код одобренного релиза (`releases/<sha>/`) — content-addressed и read-only. Никакой
рантайм НЕ пишет операционное состояние внутрь него. Признак релиза структурный:
файл `.release_sha` в корне (его кладёт launcher) — `measuring_from_release()`,
брат `measuring_from_worktree()`.

Следствия в `deployment_acceptance`:

- **Квитанция.** Вне релиза — прежняя семантика: в дерево, о котором вердикт
  (`_data_dir_for`). Внутри релиза дерево read-only ⇒ установленный обход —
  `SPA_DATA_DIR` (`own_data_dir`); нет его — писать НЕКУДА, `state_persisted=False`
  + названная причина, без удара в `Errno 13`. Телеметрия опциональна: её отсутствие
  вердикт не искажает. **Второй иерархии состояния не заводим** — только
  установленный `SPA_DATA_DIR`.
- **Артефакты.** Из релиза (как и из worktree) `data/` — не живое состояние ⇒
  `artifacts_unchecked` с причиной, НЕ ложное «протухло». Явный `--data-dir` на живое
  состояние по-прежнему меряется.

**Приёмка моделирует ФАКТИЧЕСКИЙ запуск launchd, а не режим бита у аргумента.**
launchd исполняет `argv[0]`. Если это python-интерпретатор, `.py` — его аргумент:
интерпретатор обязан быть исполним, `.py` — существовать и ЧИТАТЬСЯ (не `+x`). Если
`argv[0]` — оболочка (`/bin/bash foo.sh`) или сам скрипт (прямой запуск), исполняемый
launchd'ом скрипт обязан нести `+x` (правило доставки `deployment.md`, авария
2026-08-04, exit 126) — это НЕ ослаблено.

**Пробы импорта спрашивают интерпретатор ФЛОТА.** `check_imports` и
`check_entrypoint_imports` пробуют цель тем же интерпретатором, что и
`agent_template.sh` (`SPA_AGENT_PYTHON` → miniconda), а не `sys.executable`. В CI
(miniconda нет) — откат к `sys.executable`, несущему `spa_core`.

## Приёмка

- `spa_core/tests/test_acceptance_release_and_launcher.py` — 15 регрессов на все
  четыре дефекта, включая positive-control 2026-08-04 (оболочечная обёртка `0644` →
  мёртв) и канарейку (`python3 -I launcher.py`, `0444` → жив).
- Замер на живом флоте через доверенный 3.13: 84 entrypoints, **0 broken**; цели
  агентов **0 НЕ импортируются** (apiserver/familyfund `ok` по uvicorn);
  `_receipt_target(None, <live release>)` → `None` (в релиз не пишем).

## Детерминированная проводка живого состояния для канарейки (ARB, дополнение)

Будущая форма исполнения — `trusted launcher → trusted runtime → approved release →
deployment_acceptance`. argv launcher ЗАМОРОЖЕН (`-E -s -m …`, без `--data-dir`), значит
единственный рычаг — **`EnvironmentVariables` плиста**. Правило: канарейка получает
`SPA_DATA_DIR = /Users/yuriikulieshov/Documents/SPA_Claude/data` (канонический живой
корень состояния — тот же `REPO_ROOT/data`, что пишут агенты через `agent_template.sh`).
Тогда `_artifact_dir` в режиме релиза мерит ЖИВОЕ состояние (не `unchecked`), а квитанция
ложится туда же — вне неизменяемого релиза. **Никакого ручного `--data-dir`.**

`SPA_DATA_DIR` учитывается для свежести артефактов ТОЛЬКО в режиме релиза: в
worktree/обычном дереве приёмка судит `repo_root/data` (семантика «judges the tree»), а не
изолирующий sandbox тестов. Симуляция будущей канарейки (trusted 3.13, `-E -s -m`,
`.release_sha`, `SPA_DATA_DIR` на копию живого состояния, без `--data-dir`): **exit 0 / OK**,
`artifacts fresh`, квитанция вне релиза, под `releases/<sha>/` не записано ничего.

## Единый источник интерпретатора флота

Путь miniconda больше НЕ дублируется в прикладном коде. Резолвер
`spa_core/utils/fleet_python.py::fleet_python()` (`SPA_AGENT_PYTHON` → miniconda → откат к
`sys.executable` для CI) — единственное место в Python-коде, где записан этот путь; его
используют и `deployment_acceptance`, и `self_heal`. Bash-канон `agent_template.sh`
намеренно зеркалит те же имя переменной и дефолт (два языка — две записи; общий конфиг ради
строки был бы избыточен). Сторож — `test_fleet_python_single_source_no_duplicate_hardcode`.

## Что НЕ тронуто

Доверенный рантайм, launcher, `runtime.json`, `approved_release.json`, порог/логика
risk/капитала, `mission_tick`. Приёмка остаётся read-only и fail-CLOSED: что нельзя
установить — CRITICAL, а не тихий зачёт.
