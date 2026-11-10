# ADR-974 — §30 ТЗ «Portfolio CIO»: первое из пяти полей тени отсутствует в записи по порядку шагов; после взвода 11.09 контрольная рука «система ↔ CIO» исчезла — сравнивать нечего

- **Статус:** принято (замер, прибор только ЧИТАЕТ)
- **Дата:** 2026-11-10
- **Цикл:** #1092 (`cycle-19679`), заказ G962 п. 1 (главное) и п. 2 (карточка-исполнитель по ADR-973)
- **Предмет:** §30 приказа владельца `inbox-task-portfolio-cio-dynamic-capital-alloc`
  («Shadow Mode — обязательный этап»)
- **Продолжает:** ADR-965 (§22) · ADR-966 (§23, стартовая политика тени) · ADR-968 (§25, четыре
  носителя записи) · ADR-971/972 (§28) · ADR-973 (§29). **Ввозит, не перемеряет:** ADR-324/328
  (взвод CIO решением владельца 11.09) · ADR-228 («ACT 0 за 30 дней», взвод недостижим гейтами) ·
  ADR-067 (критерии взвода: ≥30 дней · hit-rate ≥ 0,6 · net > 0) · судья тени `shadow_trigger_eval`
  (Step 2g) · §38 `cio_shadow_replay` · сцены и книги §22 (`anti_churn_census`)
- **Прибор:** `spa_core/analytics/shadow_mode_census.py` (артефакт `data/shadow_mode_census.json`)
- **Батарея:** `spa_core/tests/test_shadow_mode_census.py` (**52 passed**) +
  `spa_core/tests/test_probe_snapshot_evidence_ages_out.py` (**6 passed**, проба ADR-975)
- **Проба приёмки:** `shadow_record_carries_the_system_action` (реестр `card_acceptance.PROBES`,
  вход `data_dir`, три исхода, контроль в обе стороны — в батарее; на живом каталоге `not_satisfied`)
- **Мутации:** `docs/mutations/SMC-974-2026-11-10.json`, 22 мутации — итог в § «Приёмка»
- **Касается ли money-path:** нет. Взвод, демпфер, запись решения, судья тени, `cycle_runner` и
  живой трек не правлены ни на символ. Две новые пробы в `card_acceptance.py` — monitoring.
- **Карточка владельцу:** НЕ заведена (§ 8). Карточки-исполнители: по ADR-973 —
  `inbox-ispolnit-29-prikaza-portfolio-cio-avarii` (G962 п. 2); по ответу владельца 10.11 —
  `inbox-ispolnit-otvet-vladeltsa-10-11-variant-1` (ADR-975).

## Дословное требование владельца

> §30 «Shadow Mode — обязательный этап». Не подключать реальный capital execution сразу. После
> реализации Portfolio CIO сначала работает: SHADOW MODE. Он видит реальные данные и портфель, но
> не выполняет транзакции. Каждый cycle сохраняет: what current system did · what Portfolio CIO
> recommended · why · estimated outcome · what happened afterwards.

Требований ЧЕТЫРЕ (A не исполняет · B реальные входы · C пять полей · D оба ответа различимы),
полей **ПЯТЬ** — число снято прибором в паритете с разбором карточки (`OWNER_SAVED_FIELDS_DECLARED`
↔ `owner_section_from_card`), обе границы раздела (`30.` / `31. Counterfactual tracking`) —
константы. Заказ G962 п. 1 процитировал два поля и поставил «…» — сдвиг **3** печатается
(`ORDER_G962_NAMED`), как у §22/§23.

## 1. Паритет — сошёлся; порядок шагов цикла ИЗМЕРЕН текстом

`record_precedes_the_trade`: писатель записи `write_shadow_rationale` — строка **2180** (Step 2f),
дверь взвода `_cio_arming.trade_allowed` — **2290**, решение о сделке `and _cio_gate_ok)` — **2315**
(Step 3). Каждый маркер ровно один раз; ноль или два ⇒ `unmeasured`, не вердикт.

## 2. Ось A — тень РЕШАЕТ перетасовку, и взведена она ДО готовности (WARN + INFO)

Настоящая дверь `cio_arming.trade_allowed` на сцене §22 (книга A → B, `damper_reason="reshuffle"`):
в книге `conservative` HOLD ⇒ ход запрещён, ACT ⇒ разрешён; в невзведённой книге дверь отвечает
`UNARMED` и не вмешивается. Взведены **три книги** (`ARMED_BOOKS`: conservative ADR-324, balanced и
aggressive ADR-328, все 2026-09-11, источник — чат владельца «запусти его … это его работа»).

Готовность по ADR-067 на живом `shadow_trigger_evaluation.json`: `ready_to_arm=False`,
`observation_days` PASS (97) · `hit_rate` PASS (1,0) · `net_bps_if_followed` **UNCHECKED** («ни один
ACT не оценён»); `arming_blockade` = `UNREACHABLE_UNTIL_CHANGED` (ADR-228). Значит этап §30
«обязательный, ПОТОМ подключать» пройден **приказом владельца, а не замером** —
`armed_before_the_shadow_criteria_passed` (WARN). Это решение владельца: записано, не
переспрашивается (ADR-285). Первая строка §30 цела: реальный capital execution не подключён,
REAL CAPITAL = $0 — тень решает БУМАЖНУЮ книгу (`shadow_verdict_decides_the_reshuffle`, INFO).

## 3. Ось B — запись видит книгу и ставки ТОГО ЖЕ дня (OK)

Последняя запись (2026-11-10): `current_positions` побайтово равна `positions` трека за тот же день
(5 позиций); все ставки `apy_evidenced_pct` несут `apy_as_of` того же дня. Оба входа
`real_same_day`; род `stale`/`absent`/`unmeasured` достижим сценой (батарея).

## 4. Ось C — ГЛАВНОЕ: пять полей, три в записи, два у вторых носителей (WARN)

| поле владельца | род | носитель · покрытие на 188 живых записях |
|---|---|---|
| what current system did | **in_a_second_carrier** | `equity_curve_daily.json` (`turnover_usd`, `positions`) · `trades.json` · `book_commit_packages.jsonl` (`package.action` hold/rebalance) |
| what Portfolio CIO recommended | in_the_record | `verdict` 188 · `legs` 164 · `target_positions` 188 |
| why | in_the_record | `reasons` 188 · `gates` 164 |
| estimated outcome | in_the_record | `gain_pp` 188 · `cost_usd` 188 · `payback_days` 158 · `target_apy_pp` 188 · `book_apy_pp` 188 |
| what happened afterwards | **in_a_second_carrier** | `shadow_trigger_evaluation.json` `per_verdict[]` 188 строк: `hit` 179 · `UNCHECKED` 9 |

Константы прибора сверяются с ПИСАТЕЛЕМ (`build_history_record`): ключ, которого писатель не
объявляет, даёт `unmeasured`, а не ноль покрытия.

**Первое поле отсутствует в записи ПО ПОСТРОЕНИЮ порядка шагов** (§ 1): в момент записи ответ
системы ещё не существует. Он лежит у трёх вторых носителей и склеивается с записью по дате
ЧИТАТЕЛЕМ — «каждый цикл сохраняет пять полей» не исполнено для первого из пяти
(`system_action_absent_from_the_record_by_step_order`, WARN). Пятое поле у судьи тени
пересчитывается каждый цикл по всему окну и перезаписывает артефакт — воспроизводимо, но не
«сохранено циклом» (`afterwards_is_recomputed_not_appended`, INFO).

## 5. Ось D — ГЛАВНОЕ: после взвода расхождений НОЛЬ — контрольная рука исчезла (CRITICAL)

Окно записи 2026-08-06…2026-11-10: дней трека **97**, с записью **97** (дыр нет), записей 188,
дней с несколькими прогонами 26. Ответ системы за день — `turnover_usd` трека ИЛИ сделка на дату;
ключа оборота нет и сделки нет ⇒ `unmeasured` (отсутствие сделки — не наблюдение удержания,
инв. #17).

| пара «система & CIO» | дней |
|---|---|
| held & HOLD | 61 |
| moved & HOLD (расхождение) | **11** — 08-23…08-31, 09-08, 09-11 |
| unmeasured & HOLD | 25 (у ранних дней трека нет `turnover_usd`) |
| ACT у CIO | 0 (ADR-228) |

До взвода два ответа **различимы** — 11 дней система двигала книгу при HOLD советника. **После
взвода 11.09 — 60 дней трека, расхождений 0, ходов 0.** Во взведённой книге ответ системы о
перетасовке ЕСТЬ ответ CIO: расхождение невозможно по построению, и `hit_rate = 1,0` на одних
HOLD измеряет не советника, а тишину. Этап §30 существует ради сравнения двух ответов, и с
11.09 сравнивать нечего (`control_arm_collapsed_after_arming`, CRITICAL). Контрапункт ADR-228
(«ACT недостижим гейтами») объясняет, почему тишина, но не возвращает контрольную руку.

## 6. Ось D-доп. — 25 дней без ответа системы (WARN)

На 25 ранних днях трека ключа `turnover_usd` нет и сделок нет: удержание подразумевается, а не
наблюдено. Названо (`system_action_unmeasured_on_days`), не додумано.

## 7. Что нашла собственная батарея в приборе до доставки

Прототип оси D считал ход только по `turnover_usd` трека и видел **одно** расхождение (09-11);
сделки `trades.json` на 08-29…09-08 легли на дни, где ключа оборота в треке ещё не было.
Третий исход ответа системы введён после этого замера; мутация M12/M13 держит оба звена.

## 8. Карточка владельцу — НЕ заведена, и почему

Единственное, что мог бы решить владелец, — «вернуть тень в советники» (снять взвод) ради
контрольной руки. Но взвод — его же решение 11.09, принятое дословно «мне не нужно настраивать
параметры, мне нужно, чтобы он начал работать»; возврат контрольной руки без снятия взвода
достижим ИНАЧЕ — вторым, невзведённым бумажным треком той же книги (теневой близнец), и это
работа агента (ADR-285), а не вопрос. Заказ G963 п. 3 называет её. Для первого поля §30
исполнитель тоже агент: дописать запись ПОСЛЕ Step 3 (или склеить `book_commit_packages.package.action`
по `decision_id`) — проба `shadow_record_carries_the_system_action` ждёт `satisfied`.

## 9. Заказ G962 п. 2 — карточка-исполнитель по ADR-973 заведена

`inbox-ispolnit-29-prikaza-portfolio-cio-avarii` (`new`, проба `emergency_exit_outranks_the_breaker`,
`not_satisfied` строки 1856/2043/2268): порядок Step 2b/2c/3 либо выход в словаре EB — money-path;
цена перестановки (EB-05, торговля на испорченных данных) названа в теле.

## Приёмка

- батарея `test_shadow_mode_census.py` **52 passed** · `test_probe_snapshot_evidence_ages_out.py` **6 passed**;
- мутации (`delta_mutation_run.py`, отдельное дерево `/private/tmp/spa_mut_1092`, 22 якоря проверены
  на уникальность ДО прогона): первый проход (`cycle-19679`) **21/22 убиты, M05 выжила** (род двери не сверялся с её ответом — закрыто сверкой рода с ответом и сценой-контролем, выжившая записана в § 7 и журнале); второй проход на ФИНАЛЬНЫХ байтах (`cycle-63852`, цикл #1093, md5 всех четырёх файлов сверены с деревом доставки до и после) **22/22 убиты, выживших 0, не применено 0**, окно прибора снято (`--window-check` → код 0);
- соседи (143 файла, импортирующие `card_acceptance` / `cio_arming`, отдельное дерево
  `/private/tmp/spa_neigh_1092`): **2 failed, 6147 passed, 22 skipped** за 33 мин 38 с (223 файла, финальные байты полного набора ADR-974…977, цикл #1094) — оба падения красны на чистом `origin/main` e2ec97d9f (`/private/tmp/spa_base_1094`, дифференциально): `test_inbox_acceptance_ratchet::test_no_new_card_is_in_work_without_a_criterion` (карточки этого цикла не названы) и `test_tier_curator::test_no_module_consumes_report_to_mutate_tiers` (`cadence_census.py`, чужой долг); своих 0;
- храповики `-k "ratchet or guard"` (отдельное дерево `/private/tmp/spa_ratchet_1092`): **7 failed, 2653 passed, 9 skipped** за 50 мин 54 с (финальные байты полного набора, цикл #1094) — все семь красны на чистом `origin/main` e2ec97d9f (дифференциально, `/private/tmp/spa_base_1094`: 7 failed, 47 passed) и поимённо совпадают с семью пред-существующими #1090/#1091: `test_cio_architecture_constraints` ×2 · `test_decision_journal_coverage` · `test_inbox_acceptance_ratchet` · `test_python_git_ref_provenance` · `test_script_path_launch_imports` · `test_unwired_scripts_ratchet`; своих 0;
- шаг 1г (`import_time_anchor_bombs --repo-root /private/tmp/spa_anchor_1092`, перемерен #1093 на финальных байтах): код 0 — «Бомб нет: при задержке 95 мин ни один вердикт не изменился»;
- живой вердикт прибора §30 на прод-данных: **CRITICAL (critical=1 warn=3 info=2 не измерено=0)**.

## Чего замер НЕ говорит

- Не говорит, что взвод 11.09 был ошибкой: это решение владельца, и прибор его только датирует
  относительно критериев ADR-067.
- Не говорит, что тень «не пишется»: 97 из 97 дней окна записаны; предмет — состав записи и
  различимость ответов.
- Не судит §31 (counterfactual по горизонтам 1h…7d): это следующий раздел, и его носитель
  (`per_verdict`, горизонт 7 дн.) здесь только назван.

## Команда перемера

```bash
SPA_ENV=ci python3 -m spa_core.analytics.shadow_mode_census --data-dir /Users/yuriikulieshov/Documents/SPA_Claude/data --no-write
SPA_ENV=ci PYTHONHASHSEED=0 python3 -m pytest spa_core/tests/test_shadow_mode_census.py spa_core/tests/test_probe_snapshot_evidence_ages_out.py -q -p no:randomly
```
