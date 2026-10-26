# Доставка и откат подготовки записей — ПОДГОТОВЛЕНО, НЕ ВЫПОЛНЕНО (ARB 26.10)

Исполнение и автоматическое назначение `acceptance_probe` в доставку НЕ входят.

## Что включается
| часть | значение |
|---|---|
| хранилище подготовок | `~/studio-os-serve/task_prep/` — вне репозитория и вне `data/` (код-синхронизация его не трогает), рядом с бандлами пульта; создаётся первым `prepare-record` |
| явный вызывающий | человек или агент-сессия одной командой (расписания нет): `python -m spa_core.studio_os.memory prepare-record --card <прод-трекер>/inbox-….md --prep-root ~/studio-os-serve/task_prep --handover <текущая передача> --verified-sha <последний проверенный sha> --provider claude_subscription_cli --config <временная конфигурация: architect 1 попытка, 300 с> --extra-context .claude/rules/acceptance.md --extra-context <состояние CI>` |
| переключатель показа | переменная `SPA_TASK_PREP_ROOT=~/studio-os-serve/task_prep` в окружении сборщика пульта (`com.spa.mission_control`); не задана ⇒ блока нет |
| точки интеграции | `memory.arch_review.prepare_record` / `preparation_state` · `mission_control.cockpit_records(task_prep_root=…)` · `owner_view.my_records` · `mission_ui/app.js` `renderRecordPreparation` |
| зависимости | Claude Code CLI текущего профиля (перед вызовом — условия подписки и выключенное платное продолжение, как в `task_prep_real_20261025T210637Z/launch_conditions.json`); git-ревизия в репозитории; читаемая карточка прод-трекера (только чтение); ФС с `flock` |

## Порядок (каждый шаг — отдельное решение владельца)
1. Доставить код каталогами целиком (`spa_core/`, `scripts/`, `tests/`), `deployment_acceptance` до и после.
2. Перезапустить `mission_server` (долгоживущий — держит старый UI в памяти; действие владельца).
3. Задать `SPA_TASK_PREP_ROOT` сборщику пульта; дождаться сборки (5 мин).
4. Первый явный `prepare-record` по ОДНОЙ записи.

## Проверка после включения (smoke)
- `prepare-record` с `--fixture` на КОПИИ одной карточки во временном каталоге ⇒ `prepared · state current`; повтор ⇒
  `unchanged`; одновременный второй запуск ⇒ `busy`;
- `curl -s http://127.0.0.1:8790/mission.json` ⇒ у записи есть `preparation.head`, в `technical` — каталог;
- запись без подготовки ⇒ «Плана пока нет»; исправить текст записи ⇒ «План устарел»;
- снять `SPA_TASK_PREP_ROOT` ⇒ блок исчезает (обратный контроль).

## Откат
Снять `SPA_TASK_PREP_ROOT` (блок исчезает со следующей сборкой) → при необходимости `git revert` кодовых коммитов
пакета → перезапуск `mission_server`. Каталоги подготовок остаются как evidence; данных трека и трекера правка не пишет.

## Пределы
Нет живой проверки iPhone; нет автоматического вызова; `busy` не ставится в очередь (повторить позже); полномочия —
оценка модели, не проверка прав; подготовка не делает запись исполнимой: проверка результата по `acceptance.md`
объявляется отдельно (следующее решение ARB).
