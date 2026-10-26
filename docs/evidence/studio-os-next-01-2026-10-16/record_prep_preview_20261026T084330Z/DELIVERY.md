# Доставка и откат подготовки записей — ОДИН конкретный пакет, ПОДГОТОВЛЕН, НЕ ВЫПОЛНЕН (ARB 26.10, вторая редакция)

> Первая редакция этого файла (коммит `e289dcd1c`) была черновиком: в ней «скопировать каталоги кода» и обязательный
> перезапуск `mission_server`. Оба утверждения неверны — см. ниже. Исполнение и `acceptance_probe` не входят.
> Выполнение — с одобрения владельца (deployment.md §6); отдельного решения на каждый обратимый подшаг не нужно.

## 0. Что выяснено измерением (только чтение прода)
- Ветка `integ/studio-os-next-01-stab` и `origin/main` **не имеют общего предка** (`merge-base` пуст): слияние ветки — не
  вариант; доставляется ПАТЧ поверх текущего `origin/main`.
- В `origin/main` и в прод-дереве нет линии MODELS-01 (`memory/arch_review.py`, `memory/role_pack.py`, `model_roles/*`,
  `architecture/model_roles.json`) — подготовка без неё не работает, поэтому она входит в пакет как НОВЫЕ файлы.
- `owner_view.py` и три файла UI в `main` совпадают с базой пакета (`22fe8c8cf`) — заменяются целиком без потерь;
  `mission_control.py` в `main` отличается — переносятся только хунки пакета (`git apply`); `memory/__main__.py` —
  только добавленные команды.
- В прод-дереве в области кода 1763 незакоммиченных изменения (синхронизация без коммитов) ⇒ `--root` = прод-дерево дал
  бы дрейфующую версию кода: подготовка идёт из ЗАКРЕПЛЁННОГО снимка (п. 2).
- Перезапуск `mission_server` НЕ нужен: сервер не импортирует ни одного меняемого модуля (замер: 77 модулей, пересечение
  пусто), а `Serving.refresh` подхватил новый бандл тем же процессом за 3 с (проверено на временном корне).
- Инкремент 3 MODELS-01 (`memory/answer.py`) НЕ входит: им пользуется `owner_remote/gateway` — это изменение живой
  функции вне предмета. Его тест (`test_model_roles_deadline.py`) поэтому тоже не входит.

## 0a. Поправка после CI 40305538365 — действующая версия пакета `release_v2.patch`
- CI нашёл: `code_identity` передавала пути через `*CODE_SCOPE` — перепись происхождения git-ссылок не разрешает такой
  аргумент («не измерено»). Исправлено литералами (`1181addb1`, тест держит их равными `CODE_SCOPE`). Действующие файлы:
  `release_task_prep_20261026T100847Z/release_v2.patch`, `FILES_v2.txt` (те же 22 файла), `build_release_v2.sh.txt`; `release.patch` — прежняя версия,
  сохранена как есть. `release_v2.patch` чисто ложится на `origin/main` `f9282333e`.
- На дереве релиза тест `test_python_git_ref_provenance` (реальное дерево) красный «вырос на 28» — и ТОЧНО ТАК ЖЕ красный
  на ЧИСТОМ `origin/main` `f9282333e` (контрольный прогон): все 28 мест — код самого `main`; пакет мест не добавляет.
  Это существующее состояние `main`, вне предмета; при доставке его нужно учитывать (CI `main` уже такой).

## 1. Пакет (`release_task_prep_*/` → `release_task_prep_20261026T100847Z/`)
- `release.patch` — 22 файла (`FILES.txt`): 7 новых модулей + `architecture/model_roles.json` + 6 новых тестов + 2 новых
  документа (передачи STAGE8 и POST_ARB8) + 6 изменённых (`owner_view`, `mission_control`, UI ×3, `memory/__main__`).
  `data/` исключён. Собран `build_release.sh.txt` из кандидата поверх `origin/main` `f9282333e`; скрипт ОТКАЗЫВАЕТ, если
  новый файл уже есть в `main`, если база заменяемого файла в `main` изменилась, или если `main` содержит строки,
  которые пакет удалил бы. Тесты на дереве релиза — `release_tests_on_main.txt` (1388 passed).
- `enable_switch.patch` — 2 строки `export` в `scripts/agent_mission_control.sh` (только этот агент).

## 2. Согласованные параметры подготовки и сборщика
| что | значение |
|---|---|
| закреплённый снимок (`--root` и `SPA_TASK_PREP_CODE_ROOT`) | `~/studio-os-serve/task_prep_root` — detached-worktree ТОГО коммита `main`, в который доставлен пакет: `git -C ~/Documents/SPA_Claude worktree add --detach ~/studio-os-serve/task_prep_root <sha доставки>`; код и документы снимка согласованы по построению |
| `--verified-sha` | тот же `<sha доставки>` после его полного CI |
| `--handover` | `docs/evidence/studio-os-next-01-2026-10-16/HANDOVER_2026-10-23_POST_ARB8.md` (входит в пакет) |
| `--config` | `~/studio-os-serve/task_prep_config.json` — копия `architecture/model_roles.json` с `architect.max_attempts=1`, `deadline_s=300`; назначения null |
| `--extra-context` | `.claude/rules/acceptance.md` (из снимка) + файл текущего состояния CI рядом с конфигом |
| хранилище (`--prep-root` и `SPA_TASK_PREP_ROOT`) | `~/studio-os-serve/task_prep` — вне репозитория и вне `data/` |
| команда (явная, без расписания) | `cd ~/studio-os-serve/task_prep_root && python3 -m spa_core.studio_os.memory prepare-record --root . --card ~/Documents/SPA_Claude/nimbalyst-local/tracker/<карточка> --prep-root ~/studio-os-serve/task_prep --handover <как выше> --verified-sha <sha> --provider claude_subscription_cli --config ~/studio-os-serve/task_prep_config.json --extra-context .claude/rules/acceptance.md --extra-context ~/studio-os-serve/task_prep_ci_state.md` — карточка только ЧИТАЕТСЯ; перед вызовом — условия подписки текущего профиля и выключенное платное продолжение |

## 3. Порядок выполнения (одно одобрение владельца на весь пакет)
1. **Резерв:** архив `spa_core/ scripts/ architecture/` прод-дерева + `git status --porcelain` + список незакоммиченных файлов
   (deployment.md п. 5); `deployment_acceptance` до.
2. `build_release.sh` заново против ТОГДАШНЕГО `origin/main` (если отказ — остановиться: `main` ушёл вперёд по этим файлам);
   полный CI на получившемся коммите; коммит патча в `main` штатным пушером.
3. Код в прод-дерево приходит ШТАТНОЙ синхронизацией каталогами (не копированием старых каталогов); `deployment_acceptance` после.
4. Снимок `task_prep_root` на коммите доставки; конфиг и файл состояния CI.
5. `enable_switch.patch` → со следующей сборкой (≤5 мин) блок появляется; перезапусков нет.
6. Первый `prepare-record` по ОДНОЙ выбранной записи.

## 4. Проверка после включения
- **Только чтение живого:** `curl -s http://127.0.0.1:8790/mission.json` — сырой `intake.my_records.items[].preparation.state`
  (`none`/`current`/…) и ОТДЕЛЬНО строка представления `owner_view.sections.work.my_records.rows[].preparation.head`
  (у записи без подготовки — «Плана пока нет …»).
- **Только на временных копиях** (живую карточку не править): копия карточки во временный трекер → `prepare-record --fixture`
  ⇒ `prepared`; повтор ⇒ `unchanged`; одновременный второй ⇒ `busy`; правка текста копии ⇒ `stale`; квота фикстуры ⇒
  «Подготовка не удалась».
- Обратный контроль: обратный `enable_switch.patch` ⇒ блок исчезает со следующей сборкой.

## 5. Откат (без удалений и без разрушающих флагов)
Обратный `enable_switch.patch` (блок исчезает, ничего не стирается) → при необходимости `git revert` коммита пакета в
`main` и штатная синхронизация → снимок `task_prep_root` и каталоги подготовок остаются как evidence. Резерв п. 3.1 —
для восстановления прод-дерева, если синхронизация что-то испортит.

## 6. Пределы
Нет живой проверки iPhone; подготовка — только явной командой; `busy` не ставится в очередь; полномочия — оценка модели;
подготовка не делает запись исполнимой: объявление проверки результата до работы — следующее решение ARB.
