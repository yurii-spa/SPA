---
trackerStatus:
  type: inbox
title: Включённый ночью source_discovery падает через раз, а манифест архитектуры красит main
status: done
source: nimbalyst
created: 2026-08-26
claimed_by: cycle-36918
claimed_at: 2026-08-27T00:13:36Z
status_trail:
  - "2026-08-27T00:39:30.450307+00:00 new -> done · queue.set_status · cycle-36918"
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

---

## Исполнено циклом #390 (2026-08-27)

### 1. Механизм падения `source_discovery` — ИЗМЕРЕН, и он не случайный

Чередование запусков объясняется не недетерминизмом, а гонкой правки с синхронизацией.
Хронология (UTC), все три отметки взяты из фактов, а не восстановлены:

| время | что было |
|---|---|
| 22:13–22:17:51 | падения — в дереве нет `export PYTHONPATH` |
| 22:18:05, 22:18:10 | успехи — правка есть, но ТОЛЬКО в прод-дереве, не на origin |
| ~22:21:51 | `code_sync_from_origin.sh` (метка обновилась: `age=80s` в 22:23:11) стёр правку |
| 22:23:11 | падение — правки снова нет |
| 22:25:01 | коммит `ab2892aa1` — правка ушла НА ORIGIN |

То есть комментарий в самой обёртке («правка обязана жить НА ORIGIN: локальную копию
синхронизация затирает») написан по этому же событию. Дефект статический, а выглядел
плавающим ровно из-за окна между локальной правкой и пушем.

**Замер в дочернем процессе с окружением launchd, обе стороны:**

```
env -i HOME=… PATH=…                python3 …/find_defillama_sources.py --help
  → ModuleNotFoundError: No module named 'spa_core'
env -i HOME=… PATH=… PYTHONPATH=…   python3 …/find_defillama_sources.py --help
  → usage: find_defillama_sources.py …
```

Причина: launchd зовёт СКРИПТ ПО ПУТИ, `sys.path[0]` = каталог скрипта, рабочий каталог
в путь не попадает — сколько бы обёртка ни делала `cd`. Починка (уже на origin) верна.

### 2. Манифест архитектуры — перегенерирован, `main` больше не краснеет

`scripts/build_architecture_manifest.py --write`: 5 дрейфов закрыто (4 из карточки +
`com.spa.orchestrator2`, появившийся по ADR-145). Повторный прогон — `OK: манифест
соответствует фактам (95 агентов)`. `test_architecture_manifest.py` +
`test_architecture_conformance.py` — **104 passed**.

`com.spa.orchestrator2` **курирован вручную**, а не оставлен `intent: unresolved`:
ратчет ADR-066 Фазы 4 требует, чтобы новый агент рождался с решённым intent, и его база
(`architecture/unresolved_baseline.json`) пуста — она может только уменьшаться.

### 3. Оба агента перемерены

`launchctl list`: `tracker_status_sentinel` — 0. `source_discovery` — всё ещё 1, и это
**отметка о запуске 22:23:11, то есть ДО починки**; такт агента `StartInterval 604800`,
поэтому цифра простоит неделю. Запускать его руками я не стал — это область владельца.
Что починка работает, показано пробой (см. ниже), а не надеждой.

### 4. СВЕРХ карточки: почему это вообще не заметил ни один сторож — ADR-148

`deployment_acceptance` в ту же минуту отвечал `OK: 85 entrypoints executable, 6 modules
import` — по букве верно и по существу мимо: он судит ОБЁРТКУ и ШЕСТЬ чужих модулей, а не
цель этого агента. Пер-агентный `agent_static_probe.sh` на том же скрипте сказал
`✅ STATIC PROBE PASSED` — скриптовой цели он даёт только `py_compile`.

Доставлена четвёртая проверка приёмки (`entrypoint_import_probe`, ADR-148): 72 агента
импортируют свою цель, 0 не импортируют, 13 вне разбора (собственные сценарии — названы
поимённо и вердикт не красят), 6 с на 85 точек входа. 19 тестов, 6 мутаций.

Дыра пер-агентного гейта заведена отдельно: `inbox-geit-pered-ustanovkoi-agenta-kompiliruet`.

### 5. Отдельно: `com.spa.novel_edge_rnd` exit=1 — НЕ дефект кода

`/tmp/spa_novel_edge_rnd.log`: `You've hit your weekly limit · resets 11am`. Внешняя квота,
лечится сама. Карточку не завожу, но и молча оставлять красную строку в брифинге нельзя.

Порождено: **ADR-148**, карточка `inbox-geit-pered-ustanovkoi-agenta-kompiliruet`,
карточка владельцу `owner-decision-vtoroi-tsikl-orkestratora-ne-perezhivet`.
