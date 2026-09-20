# Director OS Phase 3 — Источник правды и расхождения

READ-ONLY. Карта не объявляет источником правды ничего сама: она **цитирует правило,
которое это уже сделало**, а где правила нет — ставит `AUTHORITY_UNDEFINED` и победителя
не выбирает. Ничего не удаляется, не синхронизируется и не чинится.

## Модель авторитетности — откуда она взята

| Тип объекта | Авторитет | Чем установлено |
|---|---|---|
| `code_file` | origin/main (коммит) | `scripts/code_sync_from_origin.sh`: «CODE ONLY, whole directories … makes "delivered to origin" == "running in prod"» |
| `instruction_file` | origin/main | ADR-214 «Инструкции — часть доставки» |
| `excluded_path` | прод-дерево | тот же скрипт: «NEVER data/ (live track), docs/, nimbalyst-local/, KANBAN.json» |
| `generated_state` | прод-дерево | поле `source`/`updated_by` внутри самого файла |
| `launchd_agent` | **AUTHORITY_UNDEFINED** | правила «манифест против реестра» в репозитории нет |
| `installed_plist` | **AUTHORITY_UNDEFINED** | `launchd/` вне области синхронизации; установка — отдельное действие владельца (инв. 12) |
| `declared_artifact` | манифест для объявления; содержимое — производящий агент | манифест объявляет `produces` и `slo_hours` |

## Ключевое ограничение, которое карта обязана показывать

`git checkout` **не удаляет**. Файл, удалённый на origin, остаётся в проде, и сам
синхронизатор называет такие файлы в `retired_code`, оставляя их в покое. Поэтому
`result: IN_SYNC` и `files_changed: 0` — правда **о том, что checkout может сойти**, а не
о равенстве дерева коммиту. Отсюда `EXTRA_IN_PRODUCTION` — спроектированный исход
канонического пути, а не поломка.

## Статусы расхождения

`IN_SYNC` · `MODIFIED` · `MISSING_IN_PRODUCTION` · `EXTRA_IN_PRODUCTION` (origin удалил,
checkout не удалит) · `MISSING_IN_ORIGIN` (никогда не доезжал: untracked) ·
`DECLARED_NOT_OBSERVED` · `OBSERVED_NOT_DECLARED` · `STALE` (по ОБЪЯВЛЕННОМУ SLO) ·
`AUTHORITY_UNDEFINED` · `GENERATED` · `IGNORED` · `UNKNOWN`.

Статус без evidence не ставится: сборка отказывает.

Severity фактическая и ссылается на писаное правило: `WARNING` у `MODIFIED` — потому что
первый вопрос `.claude/rules/deployment.md` («это тот код, который мы приняли?») отвечает
НЕТ; `INFO` у `IGNORED`/`GENERATED`/`AUTHORITY_UNDEFINED` — состояние соответствует
объявленной границе или правила просто нет. Бизнес-оценки нет.

## Команды

```bash
cd ~/studio-os-scratch/directoros-phase3
P=/Users/yuriikulieshov/miniconda3/bin/python3; SNAP=~/studio-os-snapshots

# 1. карта авторитетности (read-only; git-чтения, ничего не пишет в прод)
$P scripts/cartographer/authority_map.py \
   --cartographer $SNAP/<комплект Cartographer> \
   --output       $SNAP/directoros-phase3-auth-$(date +%Y%m%d-%H%M%S)

# 2. портал с разделом 6
$P scripts/cartographer/portal.py \
   --cartographer $SNAP/<комплект Cartographer> \
   --briefing     $SNAP/<комплект Owner Briefing> \
   --authority    $SNAP/<комплект Authority Map> \
   --output       $SNAP/directoros-phase3-$(date +%Y%m%d-%H%M%S)
```

## Цепочка доставки (только чтение)

`worktree → push_to_github.py → origin/main → code_sync_from_origin.sh → прод-дерево →
launchd/runtime`, плюс шаг 4: носителем шага 2 является `agent_template.sh` у любого
просыпающегося агента — отдельной метки launchd у синхронизации нет. У каждого перехода
записаны механизм, направление, роль авторитета, evidence и наблюдаемое состояние. Это
описание, а не workflow-движок: ничто здесь не исполняется и не планируется.

## Чего в фазе НЕТ намеренно

Auto-fix, удаления лишних файлов, изменения code_sync или launchd, второго SSOT, кнопок
Repair / Sync / Delete / Deploy / Restart / «принять расхождение».
