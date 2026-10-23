# Пакет подключения §49 «No regression» из записей CI — ДЛЯ ОДНОГО РЕШЕНИЯ ARB/владельца, НЕ УСТАНОВЛЕН

Редакция этапа 8 (2026-10-23), заменяет редакцию этапа 7. Код пакета — коммит **`3c40ed137`** ветки
`integ/studio-os-next-01-stab` (полный CI — `../stage8_2026-10-23/`). Владелец решения — ARB / владелец
(установка агента и производитель в конституции — действие на проде, `.claude/rules/deployment.md` п. 6).

**Не выполнено ничего из раздела «Установка»:** агент `com.spa.no_regression_census` не установлен;
обёртка в дереве прежняя (`--scheduled`); `architecture/manifest.json` — `producer: null`,
`intent: designed`; `PRODUCTION_RUN_BLOCKED` для локального pytest (`--scheduled`) сохранён.

## 0. Решение, которое предлагается принять (одно)

> Подключить производитель §49 `com.spa.no_regression_census` в режиме `--from-ci --if-due --decide`
> (патч обёртки §4), после доставки кода `3c40ed137` (или его наследника на main) в прод-дерево; решение
> §49 выносится о чистом снимке ревизии S (вариант А), и это утверждение о S, а не о боевом дереве.

## 1. Что доказано до установки

| проверка | результат | где |
|---|---|---|
| полный путь на настоящей записи, явная S | `--sha 3f2482d22 --ci-run 39913698521 --decide`: отчёт REGRESSION (138 файлов, 1 упал — такт производителя), решение о снимке `not_satisfied`, предмет назван раздельно | `../stage8_2026-10-23/s49_from_ci_3f2482d22_run39913698521_decide.txt` |
| S у сервера, нет прогона | S = вершина main у сервера (`2530cb1ec`); прогона о ней нет ⇒ НЕ ИЗМЕРЕНО (код 2, `record_unavailable`), след отказа; `.git` источника не изменён | `../stage8_2026-10-23/s49_from_ci_server_pin_main_2530cb1ec.txt` |
| граница записи | `pin_server_ref` пишет в переданный `.git` (воспроизведено); `pin_revision` закрепляет ту же S во временном bare-клоне, источник побайтно цел | `spa_core/tests/test_s49_variant_a_connection.py` |
| вариант А через реального вызывающего | `cio_acceptance_rollup` → `run_probe` → проба: верные S+отчёт · другой SHA · грязный снимок · нет отчёта · протух · отказ получения · боевое дерево | там же |
| `--if-due` | повтор только о том же прогоне, S, свежей записи; не переписывает файл; протухшую не освежает; чужую ревизию не засчитывает | там же |
| порчи записи (этап 7) | `record_inconsistent`, прежний отчёт цел | `spa_core/tests/test_no_regression_census_from_ci.py` |
| мутации | 8/8 (вариант А + п. 4), 8/8 этапа 7 | `../stage8_2026-10-23/STAGE8_EVIDENCE.md` §3 |

## 2. Выбор проверяемой ревизии и прогона

1. **S** = вершина `main` У СЕРВЕРА: `pin_revision(--live-root, "origin/main", <tmp>)` — временный
   `git clone --bare --shared` источника, адрес удалённого из источника, `server_ref.pin_server_ref` в
   клоне (fetch недостающего объекта — только во временный клон). Источник (`~/Documents/SPA_mirror`)
   только читается. Отказ сервера / не remote-ref ⇒ `revision_unpinned` (код 2). Подстановки кэша,
   `rev-parse` или предка нет.
2. **Прогон** = последний ЗАВЕРШЁННЫЙ (`success`/`failure`) прогон `ci-control.yml` с `event == schedule` и
   `head_sha == S` (`find_ci_run(scheduled_only=True)`). Ручной `workflow_dispatch` — только явным
   `--ci-run`, с проверкой `manifest.sha == S`.
3. **Нет такого прогона** ⇒ `record_unavailable` ⇒ НЕ ИЗМЕРЕНО до следующего расписанного прогона о
   текущей вершине. **Последствие, названное заранее:** расписание ci-control — каждые 6 ч, `main`
   движется чаще; доля запусков, где о текущей S есть завершённый расписанный прогон, НЕ ИЗМЕРЕНА —
   §49 в проде может большую часть времени отвечать «не измерено». Это прямое следствие правила ARB
   (предок не засчитывается), а не дефект.
4. В отчёте раздельно: `source.sha` (код S) · `source.workflow_head_sha` (версия воркфлоу) ·
   `invoked_by.instrument` (дерево и sha прибора, чистота) · `invoked_by.revision` (как выбрана S) ·
   `source.run_id/event/run_url` (источник). Проба засчитывает только `source.sha`.

## 3. Где выносится решение — вариант А (разрешён ARB 23.10)

- Решение о прохождении тестов выносится для **чистого снимка S** с отчётом о той же S: производитель
  `--decide` зовёт `card_acceptance.run_probe("no_regression_tests_pass", repo_root=<снимок S>,
  report_dir=<out-root>/data)` — тот же снимок, на котором считалось население; печать
  `[РЕШЕНИЕ §49 О СНИМКЕ]`; файла не пишет.
- То же решение воспроизводимо вручную через сводку: `scripts/cio_acceptance_rollup.py --measure-tree
  <снимок S> --report-dir <out-root>/data` (решение §49 — о снимке; остальные критерии CIO в этом вызове
  судятся о `--measure-tree`, как и прежде; `report_dir` им не предлагается; `split_tree` печатается).
- **Чего это НЕ утверждает:** что работающее `~/Documents/SPA_Claude`, дерево-приёмка, другой checkout или
  текущий main проходят тесты, если их ревизия ≠ S. Проба в боевом дереве (`card_acceptance.audit` шага
  0-офис) по-прежнему даёт `unmeasured` «за другую ревизию» — честно и намеренно.

## 4. Diff обёртки (готов, НЕ применён) — `s49_wrapper_connection.patch`

```diff
-export MODULE_ARGS="--scheduled --live-root /Users/yuriikulieshov/Documents/SPA_Claude --ref origin/main --max-age-h 120 --timeout-s 3600"
+export MODULE_ARGS="--from-ci --if-due --decide --live-root /Users/yuriikulieshov/Documents/SPA_mirror --ref origin/main --out-root /Users/yuriikulieshov/Documents/SPA_Claude"
```

Патч несёт также шапку обёртки и правку теста обёртки (`test_refresh_no_regression_census.py`: вместо
`--scheduled` — `--from-ci`, `--if-due`, `--decide`, `--out-root`, `--live-root …SPA_mirror`; инв. #16 —
ожидание меняется вместе с обёрткой, одной доставкой). Проверено на временном клоне `3c40ed137`:
`git apply` чисто · `bash -n` OK · `test_refresh_no_regression_census.py` 78 passed.

## 5. Права записи и чтения

| что | право |
|---|---|
| пишет | `<out-root>/data/no_regression_census.json` (атомарно, только при успехе) · `<out-root>/data/records/no_regression/*.refusal.json` (отказ) · временный каталог (`tempfile`: `pin.git`, `record/`, `tree/`; удаляется) |
| не пишет | `.git` и рабочее дерево `--live-root` (тест границы); `data/` вне двух путей; трек; трекер |
| читает | конфиг и объекты `--live-root` · `git ls-remote` сервера · GitHub API: прогоны, артефакты (токен Keychain `GITHUB_PAT_SPA`; на подписанный адрес хранилища токен не уходит) |
| сеть | `github.com` (ls-remote, fetch во временный клон), `api.github.com`, хранилище артефактов; ничего не публикует |

## 6. Отказы

`revision_unpinned` · `record_unavailable` (нет расписанного прогона о S / API недоступен) · все коды
`CI_REFUSAL_CODES` (битый архив, чужой репозиторий/воркфлоу/прогон, не завершён, SHA/дерево не те, запись
противоречива/неполна/протухла, время не читается, перепись не измерила) ⇒ код 2, `*.refusal.json`,
отчёт `out-root` не тронут. «Новых падений против базы нет» нигде не превращается в NO_REGRESSION.

## 7. Установка — конкретные команды (выполняет владелец/по его решению; НЕ выполнено)

Предпосылка: код `3c40ed137` (или наследник) на `origin/main` и синхронизирован в прод-дерево каталогами
(`deployment.md` п. 2); патч §4 доставлен тем же путём.

```bash
# 0. до: приёмка флота и резерв (deployment.md п. 1, 5)
python3 -m spa_core.monitoring.deployment_acceptance
# 1. сухой прогон производителя руками (НЕ агент): отчёт в одноразовый каталог, боевой data/ не тронут
python3 ~/Documents/SPA_Claude/scripts/refresh_no_regression_census.py --from-ci --if-due --decide \
  --live-root ~/Documents/SPA_mirror --ref origin/main --out-root "$(mktemp -d)"
# 2. гейт деплоя (агент не долгожитель: пробный прогон допустим) и установка
bash ~/Documents/SPA_Claude/scripts/check_agent_before_deploy.sh no_regression_census
# plist в ~/Library/LaunchAgents сегодня НЕТ (проверено 23.10) — копия из repo, как у install_all_agents.sh
cp ~/Documents/SPA_Claude/launchd/com.spa.no_regression_census.plist ~/Library/LaunchAgents/
launchctl bootstrap gui/$(id -u) ~/Library/LaunchAgents/com.spa.no_regression_census.plist
# 3. после: приёмка флота и первый отчёт
python3 -m spa_core.monitoring.deployment_acceptance
python3 -c "import json;d=json.load(open('$HOME/Documents/SPA_Claude/data/no_regression_census.json'));print(d['invoked_by']['env']['via'],d['source']['sha'],d['source']['run_id'],d['source']['event'],d['generated_at'])"
```

Проверяемая ревизия: S = вершина `main` у сервера в момент запуска агента (печатается в отчёте и в логе
`/tmp/spa_no_regression_census.log`).

## 8. Приёмка

1. Первый отчёт агента: `invoked_by.env.via == "launchd:com.spa.no_regression_census"`, `invoked_by.revision.source
   == "server"`, `source.sha == invoked_by.sha`, `source.event == "schedule"`, возраст по `generated_at` < 192 ч,
   `source.record_integrity.cases == source.ci_totals.population`. Либо — названный отказ `*.refusal.json`
   (`record_unavailable`, если прогона о S ещё нет): это НЕ провал приёмки, а третий исход.
2. Лог содержит `[РЕШЕНИЕ §49 О СНИМКЕ]` с деревом-снимком той же S (`чистое=True`).
3. `.git` `~/Documents/SPA_mirror` не изменён агентом (сверка `find .git -type f | md5` до/после первого запуска —
   зеркало само обновляется раз в 30 мин, сверять в окне без его такта).
4. Только ПОСЛЕ п. 1 с `via = launchd:…`: `architecture/manifest.json` — `producer:
   "com.spa.no_regression_census"`, `intent: active` (отдельной доставкой); тогда перемерить
   `test_office_declaration_doors` и `test_office_subject_drift_producer_tick` — их закрытие НЕ обещано до
   реального прогона.
5. `deployment_acceptance` — OK до и после.

## 9. Откат

`launchctl bootout gui/$(id -u)/com.spa.no_regression_census` · обратный патч §4 (`git apply -R`) ·
`producer: null`, `intent: designed`. Отчёт `data/no_regression_census.json` игнорируется git'ом, не удалять:
проба судит его по ревизии и возрасту и сама перестанет засчитывать.
