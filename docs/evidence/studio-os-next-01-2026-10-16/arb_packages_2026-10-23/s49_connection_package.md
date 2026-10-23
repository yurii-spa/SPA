# Пакет подключения §49 «No regression» из записей CI — ДЛЯ РЕШЕНИЯ ARB, НЕ УСТАНОВЛЕН

Подготовлен 2026-10-23 (этап 7 STUDIO-OS-NEXT-01, ROADMAP п. 17). Владелец решения — ARB / владелец
(установка агента и производитель в конституции — действие на проде, `.claude/rules/deployment.md` п. 6).
Ничего из ниже перечисленного не выполнено: агент `com.spa.no_regression_census` не установлен,
`architecture/manifest.json` — `producer: null`, `intent: designed`. `PRODUCTION_RUN_BLOCKED` для
локального pytest (`--scheduled`) сохраняется без изменений.

## 1. Что уже доказано (на временных копиях)

| проверка | результат | где |
|---|---|---|
| полный путь `refresh_no_regression_census.py --from-ci` на настоящей записи | запись принята: 135 562 случая, **все** подтверждены поимённо по JUnit (`record_integrity`), доигрываний 0; вердикт §49 = **REGRESSION** (1 член населения architecture: `test_office_subject_drift_producer_tick.py`) | `s49_from_ci_0026e0fe9_run39889880442.TEMP_BUILD.json` (сборка во временный `--out-root`) |
| порчи записи ARB (обмен name/classname; второй экземпляр теста) | отказ `record_inconsistent`, прежний отчёт байт-в-байт цел, след `*.refusal.json` | `spa_core/tests/test_no_regression_census_from_ci.py` |
| отчёт о старом SHA у нового коммита / незакоммиченная правка | проба `no_regression_tests_pass` → `unmeasured` с причиной | там же, раздел «привязка отчёта к ревизии» |

## 2. Способ выбора проверяемой ревизии и номера прогона

**Правило (решение ARB 23.10):** отчёт отвечает только о ЯВНО названной ревизии кода. «Последний
проверенный предок main» допустим как историческое свидетельство и НЕ засчитывается за текущую ревизию.

1. **Ревизия** `S` = вершина `main` У СЕРВЕРА (`spa_core.utils.server_ref.pin_server_ref(<дерево>,
   "origin/main")`, `git ls-remote`), а не remote-tracking ссылка дерева (она дрейфует, ADR-152).
   Сегодня `from_ci` берёт `rev-parse origin/main` дерева `--live-root` — это **правка №1** пакета
   (п. 4): в зеркале `~/Documents/SPA_mirror` ссылка обновляется раз в 30 мин, в боевом дереве —
   отстаёт на сотни коммитов.
2. **Прогон** = последний ЗАВЕРШЁННЫЙ (`success`/`failure`) прогон `ci-control.yml` с событием
   `schedule` и `head_sha == S` (`find_ci_run` уже предпочитает `schedule`). У расписанного прогона
   проверяемый код = `github.sha` = `S` (вход `sha` пуст). Ручной `workflow_dispatch` закрепляет код
   входом, а `head_sha` у него — версия ВОРКФЛОУ (`main`); такой прогон допустим только с явным
   `--ci-run` и подтверждается `manifest.sha == S` (иначе `sha_mismatch`).
3. **Нет прогона о `S`** (main ушёл вперёд после последнего расписания, ≤ 6 ч) ⇒ `record_unavailable`
   → НЕ ИЗМЕРЕНО до следующего расписанного прогона. Подстановки предка нет.
4. Две SHA в отчёте разведены: `source.sha` — проверяемый код, `source.workflow_head_sha` — версия
   воркфлоу; проба засчитывает только первую (тест `test_workflow_sha_is_not_the_checked_revision`).

## 3. Где принимается конечное решение — БЛОКЕР, названный до установки

Проба §49 теперь сверяет ревизию отчёта с ревизией СУДИМОГО дерева (`git rev-parse HEAD` +
`git status --porcelain --untracked-files=all`). Ни одно из сегодняшних деревьев этому не отвечает:

| дерево | что даст проба | почему |
|---|---|---|
| боевое `~/Documents/SPA_Claude` (умолчание `card_acceptance.REPO_ROOT`) | `unmeasured` | HEAD `aeaab8bdc` отстаёт от origin (ADR-152), дерево изменено |
| дерево-приёмка `~/Documents/SPA_acceptance` (ADR-509/762) | `unmeasured` | не git-дерево: ревизия названа только декларацией `.acceptance_tree.json` (`commit 167667598`, 15.10) |
| снимок `git clone --shared` точного `S` (как у `from_ci`) | вердикт по существу | чистое git-дерево ревизии `S` |

Варианты (рекомендация — **А**):
- **А.** Решение §49 выносится в снимке `S`: `cio_acceptance_rollup.py --measure-tree <снимок S>`, отчёт
  подаётся пробе из `--out-root` (нужна правка №2: вход `data_dir`/`report` пробы §49 в
  `probe_tree_inputs`, сегодня — только `repo_root`). Плюс: решение и отчёт об одной ревизии по
  построению. Минус: ещё один снимок на прогон (≈30 с, замер 23.10).
- **Б.** Дерево-приёмку пересобирать git-клоном (`scripts/build_acceptance_tree.py`). Плюс: одно место
  решения. Минус: меняется предмет ADR-509 (read-only копия с `data`-ссылкой) — отдельный ADR.
- **В.** Оставить как есть: §49 в проде — `unmeasured` честно и постоянно. Это НЕ ошибка, а отказ
  засчитать отчёт не о той ревизии.

## 4. Точный diff обёртки (НЕ применён)

```diff
--- a/scripts/agent_no_regression_census.sh
+++ b/scripts/agent_no_regression_census.sh
@@
-# §49 «No regression» (заказ G673 п. 1, ADR-770): производитель отчёта
-# data/no_regression_census.json. Прогон населения идёт в СНИМКЕ коммита origin/main
-# (git clone --shared во временный каталог; граница записи — Seatbelt, частичная), не в боевом дереве.
-# РАБОЧИЙ ЗАПУСК ЗАБЛОКИРОВАН В КОДЕ (PRODUCTION_RUN_BLOCKED): полная изоляция не доказана.
-# Такт решает возраст отчёта (--max-age-h 120 < предела пробы 192 ч), а не расписание.
+# §49 «No regression» (ADR-770; решение ARB 23.10): производитель отчёта
+# data/no_regression_census.json ИЗ ЗАПИСЕЙ ЗАВЕРШЁННОГО ci-control.yml. pytest на этом
+# хосте НЕ запускается (PRODUCTION_RUN_BLOCKED относится к --scheduled и остаётся).
+# Ревизия — вершина main у СЕРВЕРА; прогон — последний расписанный о ней; нет прогона —
+# НЕ ИЗМЕРЕНО (код 2), прежний отчёт цел, след *.refusal.json.
@@
-export MODULE_ARGS="--scheduled --live-root /Users/yuriikulieshov/Documents/SPA_Claude --ref origin/main --max-age-h 120 --timeout-s 3600"
+export MODULE_ARGS="--from-ci --if-due --live-root /Users/yuriikulieshov/Documents/SPA_mirror --ref origin/main --out-root /Users/yuriikulieshov/Documents/SPA_Claude"
```

Сопутствующие правки кода (до установки, отдельной доставкой с тестами):
1. `from_ci`: ревизия через `pin_server_ref(live_root, ref)`, а не `rev-parse` (п. 2.1); отказ при
   `sha=None` — `record_unavailable` с причиной.
2. Проба §49: вход отчёта отдельно от дерева решения (вариант А) — `probe_tree_inputs` +
   `cio_acceptance_rollup` `offered`.
3. `architecture/manifest.json`: `producer: "com.spa.no_regression_census"` и `intent: active` —
   ТОЛЬКО после первого отчёта с `invoked_by.env.via = launchd:com.spa.no_regression_census`.

## 5. Права записи и чтения

| что | право |
|---|---|
| пишет | `<out-root>/data/no_regression_census.json` (атомарно, только при успехе) · `<out-root>/data/records/no_regression/*.refusal.json` (отказ) · временный каталог (`tempfile`, удаляется) |
| не пишет | `data/` вне двух путей выше, трек, трекер, `.git` источника (`clone --shared` пишет только в снимок) |
| читает | объекты git `--live-root` (только чтение) · GitHub API: прогон, перечень артефактов, архивы (токен Keychain `GITHUB_PAT_SPA`, Actions read; в заголовок подписанного адреса хранилища токен НЕ уходит) |
| сеть | `api.github.com`, хранилище артефактов GitHub; ничего не публикует |

## 6. Обработка отказов

Любой отказ (`CI_REFUSAL_CODES`: нет записи, битый архив, чужой репозиторий/воркфлоу/прогон, прогон
не завершён, SHA не тот, дерево не то, запись противоречива или неполна, протухла, время не читается,
перепись не измерила) ⇒ код возврата **2**, `*.refusal.json` с кодом и причиной, отчёт `out-root` не
тронут (тест `test_refusal_on_a_corrupted_record_keeps_the_prior_report`). Проба при этом судит
прежний отчёт: он о другой ревизии или старше 192 ч ⇒ `unmeasured`. «Новых падений против базы нет»
в NO_REGRESSION не превращается нигде — сравнения с базой в пути нет.

## 7. Приёмка

До установки (на временных копиях, повторяемо):
1. `refresh_no_regression_census.py --from-ci --live-root <git-дерево> --out-root <tmp> --sha <S>
   --ci-run <run>` → `measured: true`, `source.record_integrity.cases == source.ci_totals.population`,
   `confirmed_by_junit + stream_only_after_crash == cases`.
2. `SPA_ENV=ci PYTHONHASHSEED=0 python3 -m pytest spa_core/tests/test_no_regression_census_from_ci.py
   spa_core/tests/test_no_regression_census.py -q -p no:randomly` — зелено.

После установки (решение ARB/владельца):
3. `scripts/check_agent_before_deploy.sh no_regression_census` → OK; `launchctl bootstrap`.
4. Первый отчёт: `invoked_by.env.via == "launchd:com.spa.no_regression_census"`, `source.sha` ==
   вершина main у сервера в момент запуска, возраст < 192 ч.
5. Проба в дереве решения (вариант А) даёт `satisfied`/`not_satisfied`, а не `unmeasured` по ревизии;
   два теста такта производителя (`test_office_declaration_doors`, `test_office_subject_drift_producer_tick`)
   перемеряются — их закрытие не обещано до реального прогона.
6. `python3 -m spa_core.monitoring.deployment_acceptance` — OK до и после.

## 8. Откат

`launchctl bootout gui/$(id -u)/com.spa.no_regression_census` · вернуть `MODULE_ARGS` прежней строкой ·
`producer: null`, `intent: designed` в манифесте. Отчёт `data/no_regression_census.json` игнорируется
git'ом; удалять его не нужно — проба судит его по ревизии и возрасту и сама перестанет засчитывать.
