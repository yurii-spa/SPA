---
trackerStatus:
  type: inbox
title: Предписанный прогон даёт 39 падений против записанной полосы 14 — знаменатели РАЗНЫЕ, и число снято загрязнённым прогоном
status: new
source: nimbalyst
created: 2026-09-21
---

## Что случилось и почему это важно

Полный предписанный прогон (пять каталогов, ровно команда из `CLAUDE.md`) в цикле #658
дал **39 падений на 119 225 пройденных** за 3 ч 04 мин. Прежняя записанная полоса —
**14**, но она мерена по ДРУГОМУ знаменателю: карточка `agent-ci-data-dependent-red-tests`
считала только каталог `tests/`, а предписанная команда гоняет пять каталогов. Сравнивать
39 с 14 напрямую нельзя — это два разных вопроса, и ни на один из них сегодня нет
пришпиленного ответа.

**Что ИЗМЕРЕНО, а не предположено.** Два падения из 39 читают файлы, которые правил цикл
#658 (`docs/STATE.md` и дерево целиком):

- `test_state_journal_coverage_audit.py::test_live_state_no_longer_carries_uncovered_chronicle`
- `test_python_git_ref_provenance.py::TestRatchet::test_real_tree_matches_the_frozen_baseline`

Оба воспроизведены в отдельном дереве на пришпиленном `b2c8f4896` — то есть на состоянии
ДО правки цикла — и падают там ПОБУКВЕННО так же. Ни одно не внесено циклом #658.
Второе прямо называет чужие файлы (`scripts/cartographer/snapshot.py`,
`scripts/check_owner_gate.py`), которых цикл не касался.

**И своя методическая ошибка, без которой число лгало бы.** Пока шёл полный прогон, та же
сессия запускала рядом ещё два набора (потребители изменённого модуля, храповики). В этом
репозитории такое соседство документировано как ФАБРИКАТОР падений: общий временный
каталог и запись в живое состояние делают вердикт функцией соседей. Поэтому **39 есть
ВЕРХНЯЯ ГРАНИЦА, а не полоса**: сколько из них фабриковано соседством — не измерено.

## Что от тебя нужно

Ничего: это задание агенту, не вопрос владельцу.

## Как понять, что готово

Есть пришпиленное число падений предписанной команды (пять каталогов) на чистом
`origin/main`, снятое ОДИНОКИМ прогоном — без единого соседнего набора в том же дереве, —
и набор падений записан поимённо, а не только счётчиком.

## Что будет после

Полоса станет сравнимой между циклами: сегодня «39» и «14» отвечают на разные вопросы, и
цикл, увидевший 39, не может сказать, регрессия это или знаменатель. Поимённый набор даёт
следующему циклу сверку ПО ИМЕНАМ, а не по счёту, — та самая разница, из-за которой
прежние карточки этого класса закрывались сверкой «наборы совпали пофамильно».

**Полный набор 39 имён (цикл #658, предписанная команда, `b2c8f4896` + доставка 4206b06c):**

```
spa_core/tests/test_allocator_evidence_source_shape.py::test_the_refusal_names_the_actual_type_it_saw
spa_core/tests/test_architecture_manifest.py::MechanicalMismatchControls::test_control_untampered_manifest_is_clean
spa_core/tests/test_architecture_manifest.py::RealManifest::test_generator_check_passes_on_this_machine_or_skips
spa_core/tests/test_architecture_manifest.py::RealManifest::test_repo_plist_agents_carry_their_mechanical_fields
spa_core/tests/test_architecture_manifest.py::RealManifest::test_repo_plist_mechanical_fields_equal_the_plist
spa_core/tests/test_capital_mode_thresholds.py::test_a_typo_gets_the_STRICT_column_never_the_lenient_one[1]
spa_core/tests/test_capital_mode_thresholds.py::test_a_typo_gets_the_STRICT_column_never_the_lenient_one[pilo]
spa_core/tests/test_capital_mode_thresholds.py::test_a_typo_gets_the_STRICT_column_never_the_lenient_one[piolt]
spa_core/tests/test_capital_mode_thresholds.py::test_a_typo_gets_the_STRICT_column_never_the_lenient_one[prod]
spa_core/tests/test_capital_mode_thresholds.py::test_a_typo_gets_the_STRICT_column_never_the_lenient_one[yes]
spa_core/tests/test_capital_observability_history.py::AccountingIdentity::test_duplicate_and_corrupt_lines_are_NAMED_not_silently_lost
spa_core/tests/test_cio_brief_book_wiring.py::TestLpCycleWritesItsOwnLedger::test_same_day_rerun_is_idempotent_and_shows_no_move
spa_core/tests/test_daily_report.py::test_cycle_runner_report_failure_is_failsafe
spa_core/tests/test_deploy_site_snapshot.py::TestSafeSitePushOverwritePassthrough::test_overwrite_does_not_bypass_the_owner_gate
spa_core/tests/test_edge_boundary_dataflow_census.py::TestTheObserverIsNotPartOfItsOwnPopulation::test_the_census_screens_the_population_100_published
spa_core/tests/test_golive_checker.py::test_cycle_runner_logs_warning_once_per_day
spa_core/tests/test_heir_all_rows_price.py::HeirClassificationControls::test_a_reader_asking_was_there_an_ACT_and_how_the_day_ended_recovers
spa_core/tests/test_heir_all_rows_price.py::HeirClassificationControls::test_a_reader_listing_the_days_rows_is_called_double_counts
spa_core/tests/test_heir_all_rows_price.py::HeirClassificationControls::test_a_reader_that_keeps_only_the_first_row_lands_in_the_same_class
spa_core/tests/test_heir_all_rows_price.py::HeirClassificationControls::test_a_reader_that_sums_rows_is_called_double_counts
spa_core/tests/test_heir_all_rows_price.py::HeirClassificationControls::test_an_honest_integrator_whose_answer_coincides_is_NOT_called_recovers
spa_core/tests/test_heir_all_rows_price.py::TheNullControl::test_every_shape_of_heir_is_unchanged_under_an_identical_patch
spa_core/tests/test_heir_all_rows_price.py::TheNullControl::test_the_same_heirs_do_move_under_the_real_patch
spa_core/tests/test_heir_all_rows_price_survivors.py::MeasureSelectsAndCountsThePopulation::test_measuring_twice_into_the_same_stand_root_is_not_a_crash
spa_core/tests/test_heir_all_rows_price_survivors.py::MeasureSelectsAndCountsThePopulation::test_the_outcome_counter_accumulates_one_per_heir
spa_core/tests/test_heir_all_rows_price_survivors.py::TheRepeatDetectorNeedsBothArms::test_an_heir_saturating_at_two_rows_is_caught_by_the_left_arm
spa_core/tests/test_owner_gate_approval_scope.py::test_no_violations_means_no_scope
spa_core/tests/test_owner_gate_bypass_key.py::test_typo_signature_is_reported_not_swallowed
spa_core/tests/test_price_feeds_phase2.py::TestFetchPriceRpcLive::test_rpc_exception_falls_back_to_none
spa_core/tests/test_protocol_research_agent.py::test_unmeasured_known_set_is_spoken_aloud
spa_core/tests/test_python_git_ref_provenance.py::TestRatchet::test_real_tree_matches_the_frozen_baseline
spa_core/tests/test_state_journal_coverage_audit.py::test_live_state_no_longer_carries_uncovered_chronicle
spa_core/tests/test_telegram_alerts.py::test_alert_manager_fail_safe_on_send_crash
spa_core/tests/test_telegram_alerts.py::test_send_message_false_after_retry_exhausted
spa_core/tests/test_telegram_alerts.py::test_send_message_no_raise_without_credentials
spa_core/tests/test_track_persistence.py::test_persister_exception_does_not_crash_cycle
spa_core/tests/test_track_persistence.py::test_sync_corrupt_json_returns_error_status_without_raising
spa_core/tests/test_ws23_24_durable_golive.py::test_missed_digest_day_is_visible_not_silent
spa_core/tests/test_yield_calculation.py::test_guardrail_logs_when_rejecting
```
