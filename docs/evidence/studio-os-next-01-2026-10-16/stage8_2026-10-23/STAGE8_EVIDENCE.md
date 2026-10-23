# Этап 8 STUDIO-OS-NEXT-01 — доказательства (2026-10-23)

Ветка `integ/studio-os-next-01-stab`. Код этапа — коммит **`3c40ed1377bc535ea88f2ec17b0a2f41485a99c6`**
(база этапа: проверенный код `3f2482d22`, docs-only HEAD `ffafdf1a5`). Всё ниже — о `3c40ed137`,
если не названо иное. Полный CI — `../ci_control_2026-10-23_3c40ed137_run39935715615.md` (§8).

## 1. Workflow — путь вызова для `unwired_guard_modules` (решение ARB п. 1)

**Смысл детектора изменён намеренно (инв. #16).** Прежде: модуль с точкой входа «подключён», если его
имя встречается подстрокой в другом файле `spa_core/ scripts/ launchd/ architecture/` (проза и пути
тестов вырезаны); `.github/` не читался. Теперь дополнительно: «подключён», если его зовёт
**исполняемый шаг** workflow — `python[3[.x]] -m <точный.dotted.путь>` или `python <точный/путь.py>` в
`run:` шага, не отключённого литеральной ложью, в workflow с триггером. Поиск по имени в `.github/` НЕ
добавлен. Разбор — `spa_core/tests/_workflow_calls.py`.

| что | засчитано вызовом? |
|---|---|
| `run: … python -m spa_core.monitoring.x \` (продолжения, `VAR=…`, `set +e`, `\| tee`) | да |
| `run: python3 ./spa_core/monitoring/x.py` | да |
| шаг с `if: always()` / любым непостоянным условием | да (`conditional=True`) |
| комментарий YAML · `name:` · `description` входа · `uses:`/`with:` | нет (не `run:`) |
| `echo "python -m …"` · `echo python -m …` · `ls/cat/git diff -- <путь>` · `pytest -m …` | нет (командное слово не Python) |
| путь к тесту `spa_core/tests/test_x.py` · похожее имя `x_v2` · тот же stem в другом пакете | нет (точное совпадение) |
| `if: false` · `if: ${{ false }}` · джоба с `if: false` · workflow без `on:` | нет (отключено) |
| `python -c "…"` · тело heredoc · `shell: pwsh` · незакрытая кавычка · нечитаемый YAML | нет, и названо в `unclear` с причиной |

Замер на дереве `3c40ed137`: 16 workflow прочитаны все; 58 вызовов Python; 10 неясных (все — `python -c`,
ни один не упоминает модуль-сироту).

**Изменение классификации (до → после):**

| модуль | по имени | вызов workflow | итог |
|---|---|---|---|
| `spa_core/monitoring/live_registry_scene_census.py` | сирота | `live-registry-census.yml` · «Run census …» · `python -m spa_core.monitoring.live_registry_scene_census` | **подключён** (сменил класс) |
| `spa_core/alerts/run_alerts.py` | подключён | `spa_alerts.yml` | без изменений |
| 11 модулей `KNOWN_UNWIRED` | сироты | вызовов нет | без изменений (база не тронута) |

`KNOWN_UNWIRED` не пополнялся, исключений по имени нет.

**Мутации детектора (in-process подмена, дерево не тронуто): 8/8 убиты** — отключение `if: false`,
`python -c` как вызов, любое командное слово как Python (выжила в первом прогоне → добавлен
отрицательный случай «путь — аргумент другой команды», затем убита), без разбора heredoc, любая
оболочка, совпадение по stem, workflow без триггера как исполняемый, `unclear` молча пуст.

## 2. Такт census (п. 2)

- Прогон [39919735880](https://github.com/yurii-spa/SPA/actions/runs/39919735880) о docs-SHA `ffafdf1a5`
  прочитан по артефакту (`census_run39919735880/`): `run.json` sha `ffafdf1a5…`, `exit.json` **1**, шаг прибора
  07:44:42Z → 08:50:56Z (**66,2 мин**). Сверка с 39913695961 (`3f2482d22`) по полям `tests_recorded`,
  `reached_registry`, `counts`, `returncodes`, `collect_errors`, `not_reported`, `registry`: всё совпало;
  `rows` 2 761/2 761 — вердикт каждой строки тот же; `findings` 22/22 те же. Разница файлов — только
  `generated_at` (sha256 `80fbcf3a…` против `90b41a97…`). Заключение `failure` = код 1 прибора, не авария.
  Вывод: docs-push повторил тот же замер за ~66 мин. Результат 39919735880 — о `ffafdf1a5`, за код
  `3f2482d22` не засчитан.
- Решение: `paths-ignore` у push-триггера — РОВНО учётные документы: `docs/evidence/**`, `docs/journal/**`,
  `docs/STATE.md`, `docs/ROADMAP.md`. Любой иной путь (код, тесты, `scripts/`, `architecture/`, `data/`,
  прочие `docs/`, сам workflow) запускает census. Позитивного списка путей нет намеренно (молча пропустил
  бы вход замера). `workflow_dispatch` (ref = эта ветка, вход `sha`) сохранён; расписания и новых веток нет.
  Пропуск = «о том SHA census НЕ ИЗМЕРЕН», результат родителя не переносится. Закреплено
  `test_workflow_calls_wiring.py` (точный список ignore, нет `paths`, нет `schedule`, семантика glob на путях).
- Альтернатива «позитивный список `paths:` (spa_core/scripts/tests…)» отклонена: вход замера, не
  попавший в список, молча оставил бы census о старом коде. Альтернатива «игнорировать весь `docs/`»
  отклонена: часть проб и сторожей читает `docs/` (design-docs, реестр R&D).

## 3. §49 вариант А — отдельный каталог отчёта (п. 3)

- `PROBE_TREE_INPUTS` += `report_dir`; `run_probe(..., report_dir=)`; принимает ТОЛЬКО
  `no_regression_tests_pass` (тест: единственный в реестре). `cio_acceptance_rollup.measure(report_dir=)` /
  `--report-dir`: предлагается только объявившей пробе, без производной от `measure_tree`; `split_tree`
  считается как прежде и печатается; `report_dir` в отчёте и в печати отдельной строкой.
- Пояснение пробы называет раздельно: `код <S>` · `воркфлоу <head_sha>` · `прибор <sha дерева сборки>` ·
  `отчёт <путь> (прогон <id> (<event>))` · `решение о дереве <путь> (<sha>, чистое)` — «утверждение о S, не о
  другом дереве или текущем main».
- Контроли через НАСТОЯЩЕГО вызывающего (`rollup.measure` → `run_probe` → проба; одноразовые сцены):
  верные S и отчёт → `satisfied`, дошли `repo_root, report_dir` · другой SHA дерева решения → `unmeasured`
  «за другую ревизию» · грязный снимок → `unmeasured` «изменено после коммита» · отчёта нет → `unmeasured`
  · отчёт протух → `unmeasured` «старше предела» · отказ получения записи → отчёта нет → `unmeasured` ·
  «боевое» дерево с отчётом о S → `unmeasured`. CLI `--report-dir` печатает источник. Другим критериям
  `report_dir` не предлагается (подменённый реестр входов), `split_tree` с `report_dir` — по-прежнему `True`.
- Производитель `--decide`: решение настоящим `run_probe` о ТОМ ЖЕ чистом снимке S, где считалось население;
  файла не пишет, печатает `[РЕШЕНИЕ §49 О СНИМКЕ]`.
- **Мутации варианта А и п. 4: 8/8 убиты** — закрепление в источнике (`pin_server_ref(live_root)`), подстановка
  кэша при отказе сервера, `--if-due` без проверки возраста, `--if-due` без проверки ревизии, автоматический
  выбор не только расписанного прогона, проба игнорирует `report_dir`, сводка теряет `report_dir`, сводка
  предлагает `report_dir` всем.

## 4. S у сервера без записи в источник (п. 4)

- **Опасность воспроизведена** (положительный контроль): `server_ref.pin_server_ref(<копия боевого>, "origin/main")`
  при отсутствии объекта меняет её `.git` (отпечаток всех файлов `.git` до ≠ после).
- `pin_revision(live_root, ref, work)`: `git clone --bare --shared <источник> work/pin.git` → адрес удалённого
  из источника (`remote get-url`, чтение) → `pin_server_ref(work/pin.git, …)` (существующий механизм; fetch
  недостающего объекта — во временный клон) → снимок S из `pin.git`. Тест: S = вершина сервера; кэш
  `origin/main` источника прежний; объекта S в источнике нет; отпечаток `.git` источника не изменился ни на
  один файл. Сервер недоступен → `RevisionUnpinned` (код `revision_unpinned`), источник цел. Локальная
  ссылка (`HEAD`, `main`) → отказ «S выбирает СЕРВЕР», молчаливой подстановки нет.
- Автоматический выбор прогона — только `event == schedule` (`find_ci_run(scheduled_only=True)`); ручной —
  только явным `--ci-run`, с проверкой `manifest.sha == S`.
- `--if-due`: прежний отчёт засчитывается только при совпадении прогона, S (в `source.sha`, `invoked_by.sha`,
  ревизии дерева населения), чистоте и возрасте записи ≤ предела по `generated_at` (= начало прогона CI).
  Повтор не переписывает файл (байты и `mtime` те же). Протухшая запись → не повтор → получение → отказ
  `record_stale`, прежний отчёт цел. Чужая ревизия в `invoked_by` → не повтор → пересборка.
  **Попутно закрыт дефект:** ветка повтора не задавала `age_reason`/`max_age_h`, и печать `_lines` упала бы
  `KeyError` — теперь печатает «не срок: …» (тест).

## 5. Полный путь подключения на временной копии (п. 5; pytest не запускался)

| запуск | вход | результат |
|---|---|---|
| явная S | `--sha 3f2482d22 --ci-run 39913698521 --decide`, источник — временный клон, `--out-root` — scratchpad | код 1; отчёт **REGRESSION** (население 138: risk 111, security 11, architecture 16; упал `test_office_subject_drift_producer_tick.py`); `[РЕШЕНИЕ §49 О СНИМКЕ] not_satisfied` о снимке `3f2482d22` (чистое), прибор `3c40ed137`, воркфлоу `7bf0dbdef`, прогон 39913698521 (workflow_dispatch) — `s49_from_ci_3f2482d22_run39913698521_decide.txt` |
| S у сервера | `--if-due --decide --ref origin/main` | S = `2530cb1ec` (= `git ls-remote` main в тот момент); завершённого прогона о S нет ⇒ **НЕ ИЗМЕРЕНО** код 2, `record_unavailable`, след `*.refusal.json`; отпечаток `.git` источника до = после — `s49_from_ci_server_pin_main_2530cb1ec.txt` |

Обёртка: патч `../arb_packages_2026-10-23/s49_wrapper_connection.patch` применён на временном клоне
`3c40ed137` — `git apply` чисто, `bash -n` OK, `test_refresh_no_regression_census.py` 78 passed. В дереве
ветки обёртка НЕ изменена.

## 6. basetemp census внутри git-checkout (к B-5 backlog)

| тест | basetemp вне git | basetemp внутри `git init`-каталога |
|---|---|---|
| `test_named_cards_closed_at_origin_probe.py::test_no_repository_is_unmeasured` | passed | **failed** (`'not_satisfied' == 'unmeasured'`) |
| `test_cio_decision_owner_census.py::test_probe_is_green_once_the_line_is_gone` | passed | **failed** («`origin/main` НЕ УСТАНОВЛЕН») |
| `test_green_by_construction_census.py::test_a_linked_stand_…[dir_link,file_link]`, `::test_whole_contour_…` | passed | passed |

## 7. Проверки до полного CI (локально, Mac, `SPA_ENV=ci PYTHONHASHSEED=0 -p no:randomly`)

| набор | итог |
|---|---|
| `test_workflow_calls_wiring.py` + `test_unwired_guard_modules_ratchet.py` + `test_declared_git_environment.py` | зелено (62 + ратчет) |
| §49: `test_no_regression_census*.py`, `test_refresh_no_regression_census.py`, `test_cio_acceptance_rollup.py`, `test_s49_variant_a_connection.py` (23) | зелено |
| ратчеты, сканирующие новые файлы (26 файлов: unused import, frozen date, injected clock, import-time clock, LLM, atomic, stdlib, prescribed run, unwired ×6, absent observation …) | **526 passed** |
| пробы/сводка/офис/census (19 файлов) | **773 passed, 2 failed** — оба известных такта производителя §49 (`producer: null` сохранён намеренно) |

Это НЕ замена полному CI и НЕ «нет регрессий».

## 8. Полный CI кода `3c40ed137`

ci-control [39935715615](https://github.com/yurii-spa/SPA/actions/runs/39935715615) (`workflow_dispatch`, вход
`sha`; `manifest.sha` = `3c40ed137`, версия воркфлоу `2530cb1ec`): **RED, полный 12/12** — 135 651 случай ·
134 929 passed · **3 failed** · 0 error · 719 skipped · не получено 0 · ошибок сборки 0.

| сравнение | новых | прежних | не получено | исправлено |
|---|---|---|---|---|
| база `62fe88b48` (39832458873) → `3c40ed137` | **1** | 2 | 0 | 67 |
| `3f2482d22` (39913698521) → `3c40ed137` | 1 | 2 | 0 | 1 (`unwired_guard_modules_ratchet`) |

Остаток: такт производителя §49 ×2 (не установлен — решение ARB/владельца) и **новый**
`test_investor_report.py::test_audit_trail_from_temp_db` — причина НЕ установлена (backlog B-9: переезд из
шарда 9 в шард 2 при перестройке плана; на Mac тот же порядок зелен). step_time_drift — `unmeasured:no_same_commit_control`.
