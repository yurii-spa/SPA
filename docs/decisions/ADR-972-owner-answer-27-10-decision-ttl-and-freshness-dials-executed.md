# ADR-972 — Ответ владельца 27.10 (вариант А) исполнен: срок годности решения 600 с и допуск свежести входа 60/15 с — две ручки `TriggerParams` v1.2, и читатель колонки берёт их значения

- **Статус:** принято (исполнение ответа владельца; money-path `spa_core/allocator/`, пороги RiskPolicy не тронуты)
- **Дата:** 2026-11-10
- **Цикл:** #1090 (`cycle-62456`), заказ G960 п. 1 карточки приказа `inbox-task-portfolio-cio-dynamic-capital-alloc`
- **Карточка-исполнитель:** `inbox-ispolnit-otvet-vladeltsa-27-10-srok-godn` (проба `decision_expiry_answer_executed`
  объявлена ДО работы циклом #1089; этой сессией НЕ правилась — `.claude/rules/acceptance.md` п. 2)
- **Ответ владельца:** `owner-decision-pereproverka-pered-sdelkoi-nazovi-dva-ch` (27.09 → 27.10, вариант А),
  реестр ADR-836 (строка карточки) · форма записи ADR-839 R1
- **Продолжает:** ADR-971 (§28, замер «ответ не исполнен 13 дней») · ADR-970 (§27) · ADR-487 (§49, читатель колонки)
  · ADR-357 (предыдущая смена версии контракта, v1.1) · ADR-060 §3 (мандат)
- **Батарея:** `spa_core/tests/test_trigger_params_owner_answer_2026_10_27.py` (новая) + правки шести файлов тестов,
  чьё УТВЕРЖДЕНИЕ сменилось ответом владельца (инв. #16, обоснование в каждом — ниже)

## Решение (что сделано)

Владелец 27.10 назвал два числа (ADR-836, вариант А): **допуск свежести входа 60 с на бумаге / 15 с
вживую; срок годности решения 10 мин.** Замер ADR-971 (цикл #1089) нашёл ответ не исполненным 13 дней:
в колонке владельца `TriggerParams` v1.1 (15 ручек) ручки срока не было, а читатель колонки
(`pre_trade_recheck_census.load_owner_tolerance`, ADR-487) брал ИМЯ ручки, не ЗНАЧЕНИЕ (`tolerance_s`
— литерал `None`). Это решение — исполнение, не новый вопрос (ADR-285: ответ есть, спросить дважды =
дефект очереди).

| правило до (v1.1, ADR-357) | после (v1.2, этот ADR) | ответ владельца | проверка |
|---|---|---|---|
| ручки допуска свежести входа в колонке нет | `input_freshness_tolerance_s = 60.0` (paper) · `15.0` (pilot) | «60 с на бумаге, 15 с вживую» | `test_both_columns_carry_the_owner_numbers_verbatim[paper/pilot]`, паритет с `decision_expiry_census.OWNER_FRESHNESS_S` |
| ручки срока годности решения нет | `decision_ttl_s = 600.0` в ОБЕИХ колонках | «10 минут» (одно число) | тот же тест; `test_pilot_is_stricter_on_every_dial_that_differs` закрепляет равенство намеренным |
| `version = "v1.1"`, `version_date = "2026-09-12"` | `"v1.2"`, `"2026-10-27"` (дата ОТВЕТА владельца) | ADR-060 §3: смена порогов = новая версия | `test_contract_version_is_bumped_and_dated_by_the_owner_answer` + три теста-носителя версии (ниже) |
| читатель: `tolerance_s = None` (литерал), `ttl_dial = tolerance_dial = hits[0]` | `tolerance_s`/`ttl_s` = ЧИСЛА ручек; два предмета разведены подсказками `_FRESHNESS_HINTS` / `_TTL_HINTS` | — (половина исполнения, названная ADR-971) | `test_the_column_reader_sees_both_dials_by_its_own_hints_and_reads_their_values`; `…does_not_pass_the_ttl_off_as_the_freshness_tolerance`; `…refuses_a_non_numeric_dial_value` |
| прибор §28: `executed = ttl_dial is not None` | + паритет ЧИСЕЛ колонки с ответом (`column_matches_answer`: matches · differs · unmeasured); чужое число ⇒ CRITICAL `owner_answer_misexecuted`; колонка — ВХОД `run(params=)` | — | `test_a_mutated_dial_is_reported_as_misexecution_not_absence`; `test_run_on_a_column_with_a_foreign_number_reports_misexecution` |
| пороги RiskPolicy v1.0 | **не тронуты** | владелец: «пороги RiskPolicy ни в одном из вариантов не трогаются» | `test_risk_policy_thresholds_are_not_touched_by_the_answer`; `pre_cutover_gate` 17/17 defenses, inert |

**Два предмета — две ручки, и число одного НЕ подставляется за другое.** TTL 600 с, принятый за допуск
свежести, спрятал бы любой устаревший вход; поэтому читатель раскладывает подсказки ADR-487 по двум
предметам (`_FRESHNESS_HINTS` · `_TTL_HINTS`), а сцена с ОДНОЙ ручкой `decision_ttl_s` даёт
`ttl_s=600`, `tolerance_s=None` — не 600.

**Чего это НЕ делает (и почему).** Ворота принуждения у двери исполнения («нельзя исполнять без нового
расчёта») сюда не входят: на бумаге окно «решение → исполнение» ≤ 1,961 с против 600 с (ADR-971 ось E),
исполнять нечего до реального исполнения (инв. #6 — бумажный код исполнительный слой не импортирует).
Две проверки §27 без наблюдателя (`simulate_withdraw`/`simulate_deposit`) владельцу не задавались и
здесь не строятся (money-path, предмет №1; G960 п. 4).

## Что сменилось в тестах — и почему это не ослабление (инв. #16)

Ни один тест не удалён, не скипнут и не сужен. У шести тестов сменилось ЧИСЛО или ИСХОД при том же предмете;
каждый несёт пометку «ИЗМЕНЕНО НАМЕРЕННО (ADR-972, инв. #16)», и у каждого прежний исход остался ДОСТИЖИМЫМ сценой:

| файл · тест | было | стало | прежний исход достижим |
|---|---|---|---|
| `test_capital_mode_thresholds::test_both_columns_carry_the_same_accepted_policy_version` | `v1.1` / `2026-09-12` | `v1.2` / `2026-10-27` | — (смена версии и есть предмет) |
| `test_shadow_trigger_eval` (строка истории), `test_allocation_rationale_shadow` (params записи) | `policy_version == "v1.1"` | `"v1.2"` | — |
| `test_pre_trade_recheck_census::test_link_no_owner_tolerance_is_a_third_outcome_not_clean` | читал ЖИВУЮ колонку | колонка без ручки подаётся сценой | да — тот же тест; живая колонка проверяется новым `…live_column_makes_freshness_judgeable_by_the_owner_number` (0,6 с < 60 с — OK; 61 с — CRITICAL) |
| `test_pre_trade_recheck_census::test_owner_column_is_read_and_carries_no_freshness_dial` | «ручки нет» | «ручки ЕСТЬ, значения прочитаны» (переименован `…carries_the_owner_dials`) | да — `…without_a_dial_still_names_absence_not_zero` |
| `test_decision_expiry_census::test_axis_b_live_column_has_no_ttl_dial_and_the_reader_names_only` | `ttl_dial is None`, `names_dial_only` | обе ручки, `reads_value`, `matches` | да — `…names_dial_only_is_still_reachable_through_a_reader_that_drops_the_value` |
| `test_decision_expiry_census::test_run_on_scene_data_is_critical_with_the_unexecuted_answer_first` | живая колонка ⇒ `owner_answer_unexecuted` | колонка v1.1 подаётся входом `run(params=)` | да — тот же тест; живая форма — `…with_the_live_column_has_the_answer_executed` |
| `test_decision_expiry_census::test_probe_on_the_live_tree_is_not_satisfied…` | `not_satisfied` | `satisfied` (проба не правилась — сменился исход дерева) | да — `test_probe_three_outcomes_are_distinct` (все три исхода на подменённой колонке) |
| `test_pre_trade_check_census::test_axis_b_imports_the_verdict_and_keeps_its_window` | `freshness_judgeable is False` | `True`, причина `None` | да — через `run_census(params=)` у соседа |
| `test_pre_trade_safety_probe::…follows_the_owner_dial_not_a_literal_of_the_probe` | «НЕ ИЗМЕРЕН» на живой колонке | «старше объявленного владельцем допуска 0»; «НЕ ИЗМЕРЕН» — на подменённой колонке без ручки | да — внутри того же теста |

## Проверка

- Целевая батарея (44 файла, всё, что импортирует `TriggerParams` / читателя / приборы §27–§28 + новый файл):
  **1581 passed, 3 failed** на первом прогоне — три падения и были тремя тестами, чьё утверждение сменилось
  (таблица выше); после правки шесть файлов — **227 passed**.
- `pre_cutover_gate --json-only --no-save`: `defenses_passed 17/17`, `all_defenses_fired=True`, `is_inert=True`,
  `live_data_untouched=True`, `would_cutover=False`.
- Проба `decision_expiry_answer_executed` на дереве доставки: `satisfied` («ручка 'decision_ttl_s' в колонке v1.2,
  читатель берёт значение tolerance_s=60.0»). Прибор §28 на живой колонке: `loader=reads_value`,
  `column_matches_answer=matches`.
- Мутации (прибор `delta_mutation_run.py`, отдельное дерево `/private/tmp/spa_mut_1090`, 17 якорей проверены ДО
  прогона — по одному вхождению каждый): **17/17 убиты в ОДИН проход**, выживших 0, `unmeasured_reason=None`, окно прибора снято (дерево сверено ПОБАЙТОВО со снимком ДО, `--window-check` → код 0). Предметы: 6 мутаций чисел/версии колонки (M01–M06: подмена 60→600, TTL 300, пилот не строже, версия и дата не сменены, пилотный TTL чужой) · 6 у читателя (M07–M12: значение сброшено в `None` — состояние ADR-971, TTL подставлен за допуск, подсказка `fresh` потеряна, bool принят за секунды, причина «судить нечем» перестала выводиться из колонки) · 5 у прибора §28 (M13–M17: паритет захардкожен, допуск паритета ×10⁹, пилот судится числом бумаги, `misexecuted` недостижим, `run()` игнорирует вход). Батарея прибора: 8 файлов тестов, ≈5 мин на мутацию, 90 мин всего.
- Храповики/сторожа (`-k "ratchet or guard"`, отдельное дерево `/private/tmp/spa_ratchet_1090`): `-k "ratchet or guard"`: **8 failed, 2652 passed, 9 skipped** (51 мин 50 с, лог стоял 36 мин в одном тихом тесте). Дифференциально на чистом `origin/main` e5d021014 (отдельное дерево `/private/tmp/spa_base_1090`): **7 из 8 красны там же** — `test_cio_architecture_constraints` ×2 (guard blindness), `test_decision_journal_coverage` (население читателей), `test_inbox_acceptance_ratchet`, `test_python_git_ref_provenance`, `test_script_path_launch_imports`, `test_unwired_scripts_ratchet` — пред-существующие, не этого цикла (два из них названы G960 п. 23 и #1089). **1 моё:** `test_frozen_date_ratchet` на новом файле `test_trigger_params_owner_answer_2026_10_27.py` — литерал `2026-10-27` рядом с понятием свежести; дата здесь САМА предмет (version_date контракта = дата ответа владельца), сравнений с часами в файле нет ⇒ пометка `# FROZEN-DATE-OK: <причина>` (решение на протоколе, п. 3 правила), НЕ запись в базу; после пометки 34 passed.
- Шаг 1г `import_time_anchor_bombs.py --repo-root /private/tmp/spa_anchor_1090`: код 0 — «Бомб нет: при задержке 95 мин ни один вердикт не изменился»; дерево НАЗВАНО входом.

## Что уезжает этим же пушем, не по предмету

`spa_core/analytics/_protocol_blindness.py`, `spa_core/analytics/_untiered_census.py` — шаг 1в
(`cycle_analytics_audit.py`, код 1: аудит не мерили 32,4 ч при такте 30 ч; на диске 774 публичных модуля
против 759, разница с реестром тиров 103). Правило шага: доставлять тем же пушем.

## Последствия

- `pre_trade_recheck_census` (ADR-487) судит старость входа ЧИСЛОМ владельца: `freshness_judgeable=True`,
  `CRITICAL` достижим на живой форме (окно > 60 с без второго наблюдения). На живом треке окна ≤ 1,96 с —
  красного от этого не будет; это свойство бумаги, а не отсутствие сторожа.
- `decision_expiry_census` (§28): `owner_answer_unexecuted` уходит; остаются `decision_record_has_no_expiry_field`
  (у записи решения нет поля `expiry` — следующий шаг §28, писатель `allocation_rationale.py`),
  `owner_ttl_unreachable_on_paper`, `expiry_needs_now_and_it_is_not_an_input`, `every_ttl_in_tree_ages_something_else`.
- Строка ответа в `inbox-vosemnadtsat-otvetov-vladeltsa-27-10-isp` закрыта ссылкой сюда; у остальных семнадцати
  исполнителя по-прежнему нет у большинства.
