---
trackerStatus:
  type: inbox
title: Включённый ночью source_discovery падает через раз, а манифест архитектуры красит main
status: new
source: nimbalyst
created: 2026-08-26
---

## Что нашли (замер цикла #389, 2026-08-27 ~00:30 местного)

Владелец сегодня ночью **включил обоих помощников** из карточки
`owner-decision-dva-pomoschniki-gotovy-no-vklyuchit-ih-m`: plist'ы легли в
`~/Library/LaunchAgents` в 00:10 и 00:18, оба агента загружены (`launchctl list`).
Это ответ действием — карточку двигает владелец, я её не трогаю.

Два следствия, оба измерены, оба требуют работы:

### 1. `com.spa.source_discovery` падает — код выхода 1 ПРЯМО СЕЙЧАС

```
[2026-08-26T22:23:11Z] exec: .../python3 .../scripts/find_defillama_sources.py --save
ModuleNotFoundError: No module named 'spa_core'
[2026-08-26T22:23:11Z] EXIT agent=source_discovery code=1
```

**Мешает объяснить это одной строкой то, что запуски ЧЕРЕДУЮТСЯ при ДОСЛОВНО одной
команде** (`/tmp/spa_source_discovery.log`): 22:17:51 — падение · 22:18:05 — успех ·
22:18:10 — успех · 22:23:11 — падение. Значит статический дефект пути это **не**:
у `scripts/find_defillama_sources.py` действительно нет вставки `sys.path`
(проверено и в прод-дереве, и на `origin/main`, файлы совпадают), и импорт
`from spa_core.utils.atomic import atomic_save` при запуске скрипта по абсолютному
пути обязан падать ВСЕГДА — а он падает через раз. **Механизм НЕ ИЗМЕРЕН**;
правдоподобную версию (унаследованный `PYTHONPATH`) я не проверял и потому не
объявляю причиной. Мерить надо в дочернем процессе с окружением launchd, а не в
своей выемке (урок «воспроизводить через НАСТОЯЩЕГО вызывающего»).

Такт агента — `StartInterval 604800` (раз в неделю), так что тихо это простоит долго.

### 2. `main` красный: манифест архитектуры разошёлся с фактами

`test_architecture_manifest::test_generator_check_passes_on_this_machine_or_skips`
краснеет на прод-хосте — 4 дрейфовых расхождения:

```
DRIFT: com.spa.source_discovery: plist_source 'repo:launchd/...' → 'launch_agents'
DRIFT: com.spa.source_discovery: reboot_safe False → True
DRIFT: com.spa.tracker_status_sentinel: plist_source 'repo:launchd/...' → 'launch_agents'
DRIFT: com.spa.tracker_status_sentinel: reboot_safe False → True
```

Это **прямое следствие сегодняшней установки**, а не поломка: манифест ещё описывает
мир, где plist'ы лежали только в репозитории. Тест правдив, чинить надо манифест.
Проверено контролем на чистом `origin/main` с тем же sha (`691284a0a`): падение
воспроизводится ДОСЛОВНО и без моих правок — то есть оно предсуществующее, но
появилось всего пару часов назад.

## Что сделать

1. Измерить механизм падения `source_discovery` в ДОЧЕРНЕМ процессе с окружением
   launchd (не из своей оболочки), с положительным контролем в обе стороны; чинить
   найденное, а не первую правдоподобную версию.
2. Перегенерировать `architecture/manifest.json` (`scripts/build_architecture_manifest.py`)
   — механика берётся из фактов, курация сохраняется — и убедиться, что
   `--check` зелёный и `architecture_conformance` перестал считать этих двоих
   незагруженными.
3. В тот же заход — перемерить оба агента: `tracker_status_sentinel` сейчас выходит 0,
   но первого прогона у него может ещё не быть.

## Как понять, что готово

`launchctl list | grep -E "source_discovery|tracker_status_sentinel"` — оба с кодом 0;
`python3 scripts/build_architecture_manifest.py` — код 0; полный прогон без этих
четырёх падений.

## Почему это НЕ сделано циклом #389

Цикл вёл приказ владельца (Portfolio CIO / D6) и был занят другой карточкой; установка
агентов — область владельца, а её последствия появились в середине цикла. Тащить чужое
действие в свой коммит значило бы спрятать его от разбора.
