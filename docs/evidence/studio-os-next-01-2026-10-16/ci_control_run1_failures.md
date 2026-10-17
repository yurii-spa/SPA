# Контрольный прогон CI №1 — упавшие и ошибки по файлам

- SHA: `f0f1ce803ffbaf17c0e286b4c0dd8776a9259760`
- Прогон: 39003158532 (https://github.com/yurii-spa/SPA/actions/runs/39003158532), событие `schedule`
- Вердикт: **INCOMPLETE** (шард 2 оборван INTERNALERROR pytest, 4320 тестов без исхода)
- Окружение: python 3.11.17 · pytest 9.1.1 · ubuntu24 · SPA_ENV=ci · PYTHONHASHSEED=0
- Счёт: население 134720 · passed 129559 · failed 108 · error 19 · skipped 714 · не получено 4320 · шардов полных 11/12

> Не классифицированы как базовые или новые до сравнения с прогоном на другой версии в том же окружении
> (`python3 scripts/ci_control.py compare base/report.json head/report.json` — порядок в docstring
> `scripts/ci_control.py`). Список ниже — замер одного прогона, а не вердикт «сломано этой правкой».

Первая строка — из короткой сводки pytest в логе джобы шарда (`FAILED/ERROR <nodeid> - <сообщение>`);
где сводки нет (шард 2 оборван до неё) — первая строка отчёта из потоковой записи.

Всего: 127 в 54 файлах.

## `spa_core/tests/test_tail_value_divergence.py` (16)

| nodeid | исход | шард | первая строка |
|---|---|---|---|
| `AggregateTest::test_a_reachable_divergence_changes_the_verdict` | failed | 1 | KeyError: 'verdict' |
| `AggregateTest::test_agreement_everywhere_is_its_own_verdict` | failed | 1 | KeyError: 'verdict' |
| `AggregateTest::test_blindness_is_stated_not_implied` | failed | 1 | KeyError: 'blind' |
| `AggregateTest::test_counts_cover_every_read` | failed | 1 | KeyError: 'costed_total' |
| `AggregateTest::test_divergence_nobody_can_see_is_not_called_harmless` | failed | 1 | KeyError: 'verdict' |
| `AggregateTest::test_documents_are_counted_not_reads` | failed | 1 | KeyError: 'documents_costing' |
| `AggregateTest::test_kind_conflicts_are_counted_separately` | failed | 1 | KeyError: 'kinds_differ' |
| `AggregateTest::test_text_only_divergence_is_not_counted_as_divergence` | failed | 1 | KeyError: 'diverging' |
| `WiringTest::test_measure_binds_the_step_and_returns_that_binding` | failed | 1 | AssertionError: False is not true : результат шага не уехал в документ переписи |
| `ReportTest::test_measured_step_prints_both_numbers` | failed | 1 | AssertionError: 'divergence_real_but_no_verdict_can_see_it' not found in '[РАСХОЖДЕНИЕ ЗНАЧЕНИЙ] НЕ ИЗМЕРЕНО: у 2 стоящ(их) чтений достижимость названа классом вне объявленных (spa_core/tests/test_x.py:7=isolated_from… |
| `WholeContourTest::test_reach_is_measured_for_every_costed_read` | failed | 1 | AssertionError: 'isolated_from_the_live_document_by_the_harness' not found in ('split_is_reachable_the_writer_admits_the_unknown_class', 'split_is_unreachable_the_writer_raises_before_the_reader', 'reachability_of_the… |
| `WholeContourTest::test_the_aggregate_reads_this_contour_end_to_end` | failed | 1 | AssertionError: 'UNMEASURED' != 'MEASURED' |
| `AbsentReachIsNotAnOutcome::test_a_known_reach_still_measures` | failed | 1 | AssertionError: 'UNMEASURED' != 'MEASURED' |
| `AbsentReachIsNotAnOutcome::test_an_unmeasured_reach_is_not_read_as_not_reaching` | failed | 1 | AssertionError: 'UNMEASURED' != 'MEASURED' |
| `AbsentReachIsNotAnOutcome::test_kind_conflicts_are_still_counted_with_reach_present` | failed | 1 | KeyError: 'kinds_differ' |
| `AbsentReachIsNotAnOutcome::test_the_second_name_for_reach_is_gone_from_the_code` | failed | 1 | AssertionError: 'reach_outcome' unexpectedly found in '"""Одно правило — две копии: перепись пар «исполнитель × сторож».\n\nЗаказ **G41, п. 1** приказа владельца «Portfolio CIO» (хвост ADR-416).\n\n\nADR-416 закрыл ОД… |

## `spa_core/tests/test_safe_terminate_ownership.py` (13)

| nodeid | исход | шард | первая строка |
|---|---|---|---|
| `OwnedIsOwnedAndForeignIsNot::test_a_child_without_our_stamp_is_NOT_OWNED` | failed | 10 | AssertionError: 'OWNERSHIP_UNKNOWN' != 'NOT_OWNED' |
| `OwnedIsOwnedAndForeignIsNot::test_a_process_with_a_DIFFERENT_run_id_is_NOT_OWNED` | failed | 10 | AssertionError: 'OWNERSHIP_UNKNOWN' != 'NOT_OWNED' |
| `OwnedIsOwnedAndForeignIsNot::test_our_own_stamped_child_is_OWNED` | failed | 10 | AssertionError: 'OWNERSHIP_UNKNOWN' != 'OWNED' |
| `OwnedIsOwnedAndForeignIsNot::test_the_same_command_in_the_expected_cwd_is_OWNED` | failed | 10 | AssertionError: 'OWNERSHIP_UNKNOWN' != 'OWNED' |
| `IdentityIsNotJustThePid::test_a_pinned_identity_that_no_longer_matches_is_IDENTITY_MISMATCH` | failed | 10 | KeyError: 'identity' |
| `IdentityIsNotJustThePid::test_the_matching_identity_is_OWNED` | failed | 10 | KeyError: 'identity' |
| `GoneIsIdempotentSuccess::test_an_already_exited_process_is_PROCESS_GONE` | failed | 10 | AssertionError: 'OWNERSHIP_UNKNOWN' != 'PROCESS_GONE' |
| `GoneIsIdempotentSuccess::test_terminating_a_gone_process_is_a_no_op_success` | failed | 10 | AssertionError: 'REFUSED' != 'ALREADY_GONE' |
| `GoneIsIdempotentSuccess::test_the_call_is_idempotent` | failed | 10 | AssertionError: False is not true : {'pid': 4845, 'run_id': 'test-safe-term-2458', 'signals': [], 'refusals': ['OWNERSHIP_UNKNOWN'], 'before': {'pid': 4845, 'run_id': 'test-safe-term-2458', 'checked_at': '2026-10-17 0… |
| `TerminationItself::test_a_sigterm_ignoring_owned_process_needs_KILL` | failed | 10 | AssertionError: Lists differ: [] != ['SIGTERM', 'SIGKILL'] |
| `TerminationItself::test_an_owned_process_is_terminated_by_TERM` | failed | 10 | AssertionError: 'REFUSED' != 'TERMINATED_BY_TERM' |
| `TerminationItself::test_identity_change_between_TERM_and_KILL_blocks_the_KILL` | failed | 10 | KeyError: 'identity' |
| `NoSecretReachesTheEvidence::test_the_identity_tuple_carries_a_hash_not_the_command` | failed | 10 | KeyError: 'identity' |

## `spa_core/tests/test_table_form_census.py` (9)

| nodeid | исход | шард | первая строка |
|---|---|---|---|
| `Wiring::test_a_coordinate_without_channels_says_unmeasured` | error | 9 | Failed: Timeout (>180.0s) from pytest-timeout. |
| `Wiring::test_a_coordinate_without_shares_says_unmeasured` | error | 9 | Failed: Timeout (>180.0s) from pytest-timeout. |
| `Wiring::test_a_report_without_the_key_says_unmeasured` | error | 9 | Failed: Timeout (>180.0s) from pytest-timeout. |
| `Wiring::test_a_single_missing_channel_is_named_not_skipped` | error | 9 | Failed: Timeout (>180.0s) from pytest-timeout. |
| `Wiring::test_measure_calls_the_coordinate` | error | 9 | Failed: Timeout (>180.0s) from pytest-timeout. |
| `Wiring::test_report_renders_the_section` | error | 9 | Failed: Timeout (>180.0s) from pytest-timeout. |
| `Wiring::test_the_coordinate_does_not_widen_the_declared_surfaces` | error | 9 | Failed: Timeout (>180.0s) from pytest-timeout. |
| `Wiring::test_the_coordinate_is_serialisable` | error | 9 | Failed: Timeout (>180.0s) from pytest-timeout. |
| `Wiring::test_the_live_tree_answers_the_order` | error | 9 | Failed: Timeout (>180.0s) from pytest-timeout. |

## `spa_core/tests/test_repair_phantom_intake_cards.py` (7)

| nodeid | исход | шард | первая строка |
|---|---|---|---|
| `test_phantom_closed_and_source_reopened` | failed | 3 | spa_core.owner_queue.queue.LifecycleRefused: owner-decision-90752154.md: an owner decision is closed only on the owner's recorded answer (owner_choice / owner_answer_via / owner_answered_at in the card, or status owne… |
| `test_close_note_explains_it_was_not_the_owner` | failed | 3 | spa_core.owner_queue.queue.LifecycleRefused: owner-decision-60651903.md: an owner decision is closed only on the owner's recorded answer (owner_choice / owner_answer_via / owner_answered_at in the card, or status owne… |
| `test_empty_output_signature_also_recognised` | failed | 3 | spa_core.owner_queue.queue.LifecycleRefused: owner-decision-73628572.md: an owner decision is closed only on the owner's recorded answer (owner_choice / owner_answer_via / owner_answered_at in the card, or status owne… |
| `test_mass_case_all_of_them` | failed | 3 | spa_core.owner_queue.queue.LifecycleRefused: owner-decision-11353435.md: an owner decision is closed only on the owner's recorded answer (owner_choice / owner_answer_via / owner_answered_at in the card, or status owne… |
| `test_source_still_open_is_not_disturbed` | failed | 3 | spa_core.owner_queue.queue.LifecycleRefused: owner-decision-60651903.md: an owner decision is closed only on the owner's recorded answer (owner_choice / owner_answer_via / owner_answered_at in the card, or status owne… |
| `test_missing_source_is_reported_not_silently_dropped` | failed | 3 | spa_core.owner_queue.queue.LifecycleRefused: owner-decision-51989711.md: an owner decision is closed only on the owner's recorded answer (owner_choice / owner_answer_via / owner_answered_at in the card, or status owne… |
| `test_rerun_is_idempotent` | failed | 3 | spa_core.owner_queue.queue.LifecycleRefused: owner-decision-60651903.md: an owner decision is closed only on the owner's recorded answer (owner_choice / owner_answer_via / owner_answered_at in the card, or status owne… |

## `spa_core/tests/test_claude_run_timeout_ownership.py` (6)

| nodeid | исход | шард | первая строка |
|---|---|---|---|
| `OwnershipAtTimeout::test_10_normal_exit_does_not_kill_the_detached_child` | failed | 9 | AssertionError: 'ANOMALY-EVIDENCE' not found in "[2026-10-17 04:45:08 UTC] ⏱ RUN canary-2429-c3df750b0bda4127b27c5385ac301bea: срок 30s, grace 1s, команда: /opt/hostedtoolcache/Python/3.11.17/x64/bin/python\n[2026-10-… |
| `OwnershipAtTimeout::test_2_3_4_6_timeout_kills_only_what_is_proven_ours` | failed | 9 | AssertionError: 125 != 124 : ожидался 124, получен 125. Лог: |
| `OwnershipAtTimeout::test_7_unresolved_ownership_returns_125_and_names_survivors` | failed | 9 | AssertionError: 'ВЛАДЕНИЕ НЕ ЗАКРЫТО' not found in "[2026-10-17 04:45:17 UTC] ⏱ RUN canary-2429-4d6effd4f89d42ed9327d2a398b34ba2: срок 3s, grace 1s, команда: /opt/hostedtoolcache/Python/3.11.17/x64/bin/python\n[2026-1… |
| `OwnershipAtTimeout::test_9_evidence_is_written_before_the_first_kill` | failed | 9 | AssertionError: 'TIMEOUT-EVIDENCE' not found in "[2026-10-17 04:45:25 UTC] ⏱ RUN canary-2429-d4e4ac153fa6410d9417ebf034721eb3: срок 4s, grace 2s, команда: /opt/hostedtoolcache/Python/3.11.17/x64/bin/python\n[2026-10-1… |
| `TheInstrumentsAreNotOrnaments::test_with_run_id_the_same_scene_closes` | failed | 9 | AssertionError: 125 != 124 |
| `SigtermIgnoredThenSigkill::test_sigterm_ignoring_tree_is_closed_by_sigkill_with_rc_124` | failed | 9 | AssertionError: 125 != 124 : ожидался 124, получен 125. Лог: |

## `spa_core/tests/test_constitution_right_to_fix.py` (4)

| nodeid | исход | шард | первая строка |
|---|---|---|---|
| `LiveControlOnTheRealTree::test_every_form_of_every_pair_is_a_declared_class` | error | 11 | Failed: Timeout (>180.0s) from pytest-timeout. |
| `LiveControlOnTheRealTree::test_the_first_axis_shift_rests_on_a_named_pair` | error | 11 | Failed: Timeout (>180.0s) from pytest-timeout. |
| `LiveControlOnTheRealTree::test_the_peer_axis_really_shifted` | error | 11 | Failed: Timeout (>180.0s) from pytest-timeout. |
| `LiveControlOnTheRealTree::test_the_shelf_is_readable_here_so_nothing_is_unmeasured` | error | 11 | Failed: Timeout (>180.0s) from pytest-timeout. |

## `spa_core/tests/test_document_field_reader.py` (4)

| nodeid | исход | шард | первая строка |
|---|---|---|---|
| `test_live_measurement_reports_both_liveness_numbers` | failed | 5 | AssertionError: свой обход нашёл 41 счётчик(ов), уехавш(их) в документ, сосед — 26: разбор по имени поля по ДРУГОМУ населению отвечал бы на другой вопрос |
| `test_live_measurement_answers_with_a_pair_of_numbers` | failed | 5 | KeyError: 'resolved_by_document_step' |
| `test_blind_spots_name_the_one_sidedness_aloud` | failed | 5 | KeyError: 'blind' |
| `test_report_prints_the_pair_and_the_refusal_names` | failed | 5 | AssertionError: assert ('no_reader_of_that_field_anywhere_in_this_file' in 'одно правило — две копии (заказ G41 п. 1): None · две копии None · сторож достаёт исполнителя None · значения разные ...ня; общее ли происхож… |

## `spa_core/tests/test_python_git_ref_provenance.py` (4)

| nodeid | исход | шард | первая строка |
|---|---|---|---|
| `TestRatchet::test_real_tree_matches_the_frozen_baseline` | failed | 3 | AssertionError: 0 != 3 : |
| `RegistryGovernance::test_an_intact_baseline_passes` | failed | 3 | AssertionError: 0 != 3 |
| `RegistryReactsToTheCensus::test_removing_an_unresolved_identity_reduces_the_debt` | failed | 3 | AssertionError: 0 != 3 |
| `RegistryReactsToTheCensus::test_the_unchanged_census_is_green` | failed | 3 | AssertionError: 0 != 3 |

## `scripts/tests/test_check_concurrent_pytest.py` (3)

| nodeid | исход | шард | первая строка |
|---|---|---|---|
| `TestOpenFilesParsesRealLsof::test_a_live_process_holding_a_written_file_reads_READABLE` | failed | 4 | AssertionError: 'unmeasured' != 'READABLE' |
| `TestOpenFilesParsesRealLsof::test_a_live_process_whose_only_write_target_is_unlinked_reads_UNREADABLE` | failed | 4 | AssertionError: [] is not true : разбор не увидел отвязанный файл, открытый на запись |
| `TestOpenFilesParsesRealLsof::test_a_real_file_open_for_writing_is_parsed_with_its_mode_and_inode` | failed | 4 | AssertionError: [] is not true : разбор не нашёл собственный открытый файл /tmp/tmpe9zxekrx.ccp-probe |

## `spa_core/tests/test_absent_observation_ratchet.py` (3)

| nodeid | исход | шард | первая строка |
|---|---|---|---|
| `test_tree_introduces_no_new_member` | failed | 7 | AssertionError: сигнал or_falsy: НОВЫЕ места класса «отсутствие наблюдения = благополучие» (1): ['spa_core/monitoring/ledger_day_unit_census.py:1013:b0bfd9393e7a#0']. Инвариант #17: отсутствие наблюдения обязано быть … |
| `test_ceiling_is_reanchoring_not_growth` | failed | 7 | AssertionError: сигнал or_falsy: координат 142 при потолке 141. Это НОВОЕ место класса на новой строке, а не эффект переякорения — чинить писателя (инвариант #17), а не число здесь. |
| `test_baseline_and_tree_agree_member_for_member` | failed | 7 | AssertionError: сигнал or_falsy: в дереве 147, в базе 146; только в дереве: ['spa_core/monitoring/ledger_day_unit_census.py:b0bfd9393e7a#0']; только в базе: [] |

## `spa_core/tests/test_decision_surface_census.py` (3)

| nodeid | исход | шард | первая строка |
|---|---|---|---|
| `LiveControlOnTheRealTree::test_the_measure_bites_here` | error | 10 | Failed: Timeout (>180.0s) from pytest-timeout. |
| `LiveControlOnTheRealTree::test_the_population_is_declared_and_non_empty` | error | 10 | Failed: Timeout (>180.0s) from pytest-timeout. |
| `LiveControlOnTheRealTree::test_the_senior_surface_is_asked_but_not_declared` | error | 10 | Failed: Timeout (>180.0s) from pytest-timeout. |

## `spa_core/tests/test_rule_second_copy_census.py` (3)

| nodeid | исход | шард | первая строка |
|---|---|---|---|
| `LiveControlOnTheRealTree::test_accounting_identity_holds_on_the_real_tree` | error | 11 | Failed: Timeout (>180.0s) from pytest-timeout. |
| `LiveControlOnTheRealTree::test_every_printed_row_survives_an_independent_recheck` | error | 11 | Failed: Timeout (>180.0s) from pytest-timeout. |
| `LiveControlOnTheRealTree::test_the_real_tree_is_measured_at_all` | error | 11 | Failed: Timeout (>180.0s) from pytest-timeout. |

## `spa_core/tests/test_shadow_tvl_provenance.py` (3)

| nodeid | исход | шард | первая строка |
|---|---|---|---|
| `TestAcceptanceProbe::test_probe_is_satisfied_on_this_tree` | failed | 0 | AssertionError: 'unmeasured' != 'satisfied' |
| `TestAcceptanceProbe::test_probe_refuses_when_a_number_rides_without_its_rod` | failed | 0 | AssertionError: 'unmeasured' != 'not_satisfied' |
| `TestAcceptanceProbe::test_probe_refuses_when_a_tvl_literal_still_reaches_the_number` | failed | 0 | AssertionError: 'unmeasured' != 'not_satisfied' |

## `scripts/tests/test_shell_git_cd_target_census.py` (2)

| nodeid | исход | шард | первая строка |
|---|---|---|---|
| `RatchetOnTheRealTree::test_real_tree_subject_is_within_the_baseline` | failed | 7 | AssertionError: 2 != 0 : талоги ('/tmp/cdtarget-nj1d3bl2/c2/homeA/Documents/SPA_Claude' ≠ '/tmp/cdtarget-nj1d3bl2/c2/ext/SPA_SYNC_REPO') |
| `RatchetOnTheRealTree::test_the_ratchet_is_able_to_fail` | failed | 7 | AssertionError: 2 != 3 |

## `spa_core/tests/test_adapter_status_writer_census.py` (2)

| nodeid | исход | шард | первая строка |
|---|---|---|---|
| `TestCensusRegressions::test_live_tree_is_green_at_its_declared_ceilings` | failed | 5 | AssertionError: 2 != 0 : ['НЕ ИЗМЕРЕНО (цель приходит от вызывающего) 27 > потолок 26', '  [от вызывающего] scripts/archive/fix_adapter_tiers.py:86', '  [от вызывающего] scripts/preflight_day1.py:51', '  [от вызывающе… |
| `TestProbe::test_green_on_the_whole_contour` | failed | 5 | AssertionError: 'unmeasured' != 'satisfied' |

## `spa_core/tests/test_autonomy_mandate.py` (2)

| nodeid | исход | шард | первая строка |
|---|---|---|---|
| `TestWiredIntoTheMandatoryStep::test_mandate_line_survives_an_unmeasurable_office` | failed | 4 | Failed: Timeout (>180.0s) from pytest-timeout. |
| `TestWiredIntoTheMandatoryStep::test_office_step_prints_the_mandate_judgement` | failed | 4 | Failed: Timeout (>180.0s) from pytest-timeout. |

## `spa_core/tests/test_list_identity_census.py` (2)

| nodeid | исход | шард | первая строка |
|---|---|---|---|
| `MeasureRefusesInsteadOfGuessing::test_a_measured_population_with_a_candidate_outside_is_a_finding` | failed | 2 | spa_core/tests/test_list_identity_census.py:422: in test_a_measured_population_with_a_candidate_outside_is_a_finding |
| `MeasureRefusesInsteadOfGuessing::test_a_measured_population_without_findings_is_clean` | failed | 2 | spa_core/tests/test_list_identity_census.py:417: in test_a_measured_population_without_findings_is_clean |

## `spa_core/tests/test_rule_second_copy_census_wiring.py` (2)

| nodeid | исход | шард | первая строка |
|---|---|---|---|
| `OfficeReadsTheNumberNotJustTheFile::test_declared_shape_is_the_shape_the_producer_actually_writes` | failed | 8 | Failed: Timeout (>180.0s) from pytest-timeout. |
| `TheGuardsOfThisInstrumentDoNotBecomeItsOwnFinding::test_own_test_files_are_not_rows` | failed | 8 | Failed: Timeout (>180.0s) from pytest-timeout. |

## `spa_core/tests/test_run_identity_key_price.py` (2)

| nodeid | исход | шард | первая строка |
|---|---|---|---|
| `BatteryHoleTests::test_the_guard_is_lowered_again_after_a_sweep` | failed | 7 | Failed: Timeout (>180.0s) from pytest-timeout. |
| `BatteryHoleTests::test_the_instrument_excludes_itself_by_naming_the_reason` | failed | 7 | Failed: Timeout (>180.0s) from pytest-timeout. |

## `spa_core/tests/test_shell_git_cd_repo_identity.py` (2)

| nodeid | исход | шард | первая строка |
|---|---|---|---|
| `GuardOnTheGuard::test_empty_baseline_makes_the_real_tree_run_red_by_name` | failed | 8 | AssertionError: 2 != 3 : ЛИЧНОСТЬ репозитория, куда ведёт `cd` — мерено из '/home/runner/work/SPA/SPA' |
| `GuardOnTheGuard::test_shipped_baseline_is_green_and_covers_the_measured_subject` | failed | 8 | AssertionError: 2 not found in (0,) : ЛИЧНОСТЬ репозитория, куда ведёт `cd` — мерено из '/home/runner/work/SPA/SPA' |

## `spa_core/tests/test_unwired_guard_modules_ratchet.py` (2)

| nodeid | исход | шард | первая строка |
|---|---|---|---|
| `test_no_new_guard_module_is_left_unwired` | failed | 7 | AssertionError: новый сторож с точкой входа, которого никто не зовёт: ['spa_core/monitoring/step_time_drift.py']. Написать проверку и не позвать её — то же, что не написать: apy_spike_monitor так пропустил всплеск 9.2… |
| `test_fixed_modules_leave_the_census` | failed | 7 | AssertionError: эти модули больше не сироты: ['spa_core/alerts/adaptive_monitor.py', 'spa_core/governance/cpa_governance_watcher.py', 'spa_core/monitoring/data_freshness_monitor.py', 'spa_core/monitoring/unified_gas_m… |

## `scripts/tests/test_fill_agent_passports.py` (1)

| nodeid | исход | шард | первая строка |
|---|---|---|---|
| `TestManifestFormatIsPreserved::test_manifest_on_disk_is_byte_identical_to_a_reserialization` | failed | 6 | AssertionError: '{\n  "schema_version": 1,\n  "adr": "ADR-066"[420965 chars]n}\n' != '{\n "schema_version": 1,\n "adr": "ADR-066",\[403653 chars]n}\n' : манифест на диске записан не каноническим сериализатором |

## `spa_core/tests/test_absent_observation_probe.py` (1)

| nodeid | исход | шард | первая строка |
|---|---|---|---|
| `ProbeIsGreenOnTheWholeContour::test_the_live_tree_answers_satisfied_today` | failed | 4 | AssertionError: 'not_satisfied' != 'satisfied' |

## `spa_core/tests/test_act_day_recovery.py` (1)

| nodeid | исход | шард | первая строка |
|---|---|---|---|
| `TestTheHonestBatteryHoles::test_fractional_turnover_keeps_its_cents` | failed | 6 | AssertionError: 20000.0 != 20000.01 |

## `spa_core/tests/test_announce_clock_door_census.py` (1)

| nodeid | исход | шард | первая строка |
|---|---|---|---|
| `TestSynthForm::test_an_unknown_directive_yields_a_string_and_the_DOOR_refuses_it` | failed | 6 | AssertionError: '%Q' != 'Q' |

## `spa_core/tests/test_build_loop_governance.py` (1)

| nodeid | исход | шард | первая строка |
|---|---|---|---|
| `TestScenarioDPressure::test_reserve_is_released_at_critical_and_rebuilt_when_healthy` | failed | 10 | AssertionError: assert 'error' == 'released' |

## `spa_core/tests/test_census_stage_root_contract.py` (1)

| nodeid | исход | шард | первая строка |
|---|---|---|---|
| `CensusStageRootContract::test_every_stage_census_puts_its_artifact_under_root_data` | failed | 5 | ModuleNotFoundError: No module named 'spa_core.monitoring._atc' |

## `spa_core/tests/test_cockpit_dispatch.py` (1)

| nodeid | исход | шард | первая строка |
|---|---|---|---|
| `test_wrapper_puts_taken_record_first_and_settles_it_after_the_session` | failed | 11 | AssertionError: ЗАПИСИ ПУЛЬТА: выбор исполнителя НЕ ИЗМЕРЕН (код 1) — это НЕ «записей нет». Посмотри принятые записи пульта (source: cockpit*, status new, intake_seen) руками перед выбором задачи. Ты — оркестратор SP |

## `spa_core/tests/test_cockpit_loop.py` (1)

| nodeid | исход | шард | первая строка |
|---|---|---|---|
| `test_intake_is_not_execution_close_refuses_a_card_nobody_took` | failed | 4 | AssertionError: assert ('new' == 'accepted' |

## `spa_core/tests/test_decision_journal_coverage.py` (1)

| nodeid | исход | шард | первая строка |
|---|---|---|---|
| `ReaderPopulationRatchet::test_every_production_reader_is_in_the_population` | failed | 3 | AssertionError: Lists differ: ['spa_core.monitoring.keep_dominance_census'] != [] |

## `spa_core/tests/test_declared_git_environment.py` (1)

| nodeid | исход | шард | первая строка |
|---|---|---|---|
| `TheSuiteDeclaresItsCloneDepth::test_every_pytest_job_declares_full_history` | failed | 7 | AssertionError: ['ci-lite.yml:syntax-and-import — fetch-depth не объявлена (умолчание 1)'] is not false : Джоба гоняет pytest, а историю репозитория ей не положили. |

## `spa_core/tests/test_edge_boundary_dataflow_census.py` (1)

| nodeid | исход | шард | первая строка |
|---|---|---|---|
| `TestTheObserverIsNotPartOfItsOwnPopulation::test_the_census_screens_the_population_100_published` | failed | 6 | AssertionError: 39 != 35 |

## `spa_core/tests/test_edge_downside_parity.py` (1)

| nodeid | исход | шард | первая строка |
|---|---|---|---|
| `test_downside_denominator_is_exactly_zero_where_volatility_is_not` | failed | 9 | assert 2.8571235909641123e-20 == 0.0 |

## `spa_core/tests/test_finding_address_price.py` (1)

| nodeid | исход | шард | первая строка |
|---|---|---|---|
| `WiredIntoTheCensus::test_with_a_tree_both_are_measured` | failed | 6 | Failed: Timeout (>180.0s) from pytest-timeout. |

## `spa_core/tests/test_fixture_schema_gap_ratchet.py` (1)

| nodeid | исход | шард | первая строка |
|---|---|---|---|
| `test_the_door_sites_still_add_up_to_the_same_operand` | failed | 5 | AssertionError: сумма исходов двери 123 против объявленных 121: площадка либо появилась, либо ПРОПАЛА — второе молчанием быть не вправе |

## `spa_core/tests/test_frozen_date_ratchet.py` (1)

| nodeid | исход | шард | первая строка |
|---|---|---|---|
| `test_no_new_file_joins_the_frozen_date_class` | failed | 6 | AssertionError: New test file(s) pin a literal date next to a freshness concept: |

## `spa_core/tests/test_invisible_consumer_scale.py` (1)

| nodeid | исход | шард | первая строка |
|---|---|---|---|
| `WiringTest::test_measure_calls_the_coordinate_and_stores_it_under_its_own_key` | failed | 7 | StopIteration |

## `spa_core/tests/test_live_registry_scene_census.py` (1)

| nodeid | исход | шард | первая строка |
|---|---|---|---|
| `TheDifferentialRunsOnADisposableSceneAndTellsTheKindsApart::test_a_file_that_dies_at_collection_under_substitution_is_breaks` | failed | 5 | AssertionError: 'tests/test_dies_at_collection.py' not found in ['tmpsgl_92hf/tests/test_dies_at_collection.py'] |

## `spa_core/tests/test_no_import_time_clock_in_tests.py` (1)

| nodeid | исход | шард | первая строка |
|---|---|---|---|
| `TestNoImportTimeClockInTests::test_no_unreviewed_import_time_clock` | failed | 9 | AssertionError: Lists differ: [] != [_Capture(file='test_cockpit_dispatch.py',[736 chars]()')] |

## `spa_core/tests/test_office_declaration_doors.py` (1)

| nodeid | исход | шард | первая строка |
|---|---|---|---|
| `TheLiveAnswerOfTheOrder::test_every_office_artifact_has_a_measurable_producer_tick` | failed | 0 | AssertionError: Tuples differ: (('data/no_regression_census.json', 'no_re[95 chars]ь'),) != () |

## `spa_core/tests/test_office_subject_drift_producer_tick.py` (1)

| nodeid | исход | шард | первая строка |
|---|---|---|---|
| `test_the_live_office_can_measure_the_tick_of_every_artifact_it_reads` | failed | 7 | AssertionError: такт НЕ ИЗМЕРИМ у 1 из 136 артефактов офиса: [('data/no_regression_census.json', 'у data/no_regression_census.json в конституции не объявлен производитель')] |

## `spa_core/tests/test_postgres_migration.py` (1)

| nodeid | исход | шард | первая строка |
|---|---|---|---|
| `TestMigrateCallsites::test_live_codebase_has_zero_raw_connects` | failed | 10 | AssertionError: Found 10 raw sqlite3.connect() call(s) — Phase 2 incomplete: |

## `spa_core/tests/test_recover_trusted_runtime.py` (1)

| nodeid | исход | шард | первая строка |
|---|---|---|---|
| `TestDryRunZeroMutation::test_dry_run_reaches_confirmed_broken_and_mutates_nothing` | failed | 6 | AssertionError: 127 != 0 : dry-run failed: |

## `spa_core/tests/test_research_evidence_tracks.py` (1)

| nodeid | исход | шард | первая строка |
|---|---|---|---|
| `test_facts_jsonl_no_fact_lacks_a_citation_from_the_seed_file` | failed | 11 | FileNotFoundError: [Errno 2] No such file or directory: '/private/tmp/claude-501/-Users-yuriikulieshov-Documents-SPA-Claude/77953ab2-8e9a-4d56-8ecb-16448ad02813/scratchpad/ev/phase0_citations.md' |

## `spa_core/tests/test_site_snapshot_view_shape.py` (1)

| nodeid | исход | шард | первая строка |
|---|---|---|---|
| `TheViewCoversTheSnapshotShape::test_every_snapshot_field_is_covered_or_declared` | failed | 5 | AssertionError: Lists differ: ['/anchor_equity', '/book_exposure', '/boo[1949 chars]pct'] != [] |

## `spa_core/tests/test_slo_keepability.py` (1)

| nodeid | исход | шард | первая строка |
|---|---|---|---|
| `ExitCodesSeparateThreeOutcomes::test_everything_keepable_exits_zero` | failed | 7 | AssertionError: 1 != 0 |

## `spa_core/tests/test_subject_population_census.py` (1)

| nodeid | исход | шард | первая строка |
|---|---|---|---|
| `PopulationCompletenessIsASeparateAssertion::test_the_precise_road_is_a_subset_of_the_recall_road` | failed | 10 | AssertionError: Lists differ: [] != ['spa_core/tests/test_mission_ui_design_v3.py:21'] |

## `spa_core/tests/test_timeseries_lane_modules.py` (1)

| nodeid | исход | шард | первая строка |
|---|---|---|---|
| `test_falling_apy_riskier_than_rising[apy_tracker]` | failed | 5 | assert (None is not None) |

## `spa_core/tests/test_truncated_input_census.py` (1)

| nodeid | исход | шард | первая строка |
|---|---|---|---|
| `TheJanitorSeesEveryWorktree::test_trees_beyond_the_old_budget_are_still_found` | failed | 11 | AssertionError: 1955 not greater than 2000 : сцена обязана перерасти бюджет — иначе она верна по построению и ничего не доказывает |

## `spa_core/tests/test_unwired_registry_evidence.py` (1)

| nodeid | исход | шард | первая строка |
|---|---|---|---|
| `TestTheRuleOnTheRealRepo::test_the_carve_out_did_not_swallow_the_watch` | failed | 4 | AssertionError: 69 not less than 67.5 : вычет забрал 69 из 135 — это уже не класс «ручной R&D», а отключение сторожа |

## `spa_core/tests/test_unwired_scripts_ratchet.py` (1)

| nodeid | исход | шард | первая строка |
|---|---|---|---|
| `TestRatchet::test_no_NEW_unwired_script_appears` | failed | 6 | AssertionError: Lists differ: ['edge_rkaw_running_calmar_weighting', 're[45 chars]sus'] != [] |

## `tests/cartographer/test_owner_briefing.py` (1)

| nodeid | исход | шард | первая строка |
|---|---|---|---|
| `ManifestTellsTheTruthPerStage::test_the_manifest_never_stores_a_remote_url_or_a_raw_response` | failed | 5 | AssertionError: 'token' unexpectedly found in '{"schema_version": "cartographer.run_manifest/0.1", "run_started_at": "2026-10-17T04:40:39.762563+00:00", "page_generated_at": "2026-10-17T04:40:39.763355+00:00", "volati… |

## `tests/test_no_utcnow.py` (1)

| nodeid | исход | шард | первая строка |
|---|---|---|---|
| `test_no_bare_utcnow_in_runtime` | failed | 10 | AssertionError: Bare datetime.utcnow() found — use spa_core.utils.clock.utcnow() (naive-preserving, deprecation-free): |

## `tests/test_spaerror_complete.py` (1)

| nodeid | исход | шард | первая строка |
|---|---|---|---|
| `test_20_zero_bare_exceptions_in_spa_core` | failed | 10 | AssertionError: Found 15 bare Exception/RuntimeError in spa_core/ (non-test, non-stdlib). Migrate to SPAError: |
