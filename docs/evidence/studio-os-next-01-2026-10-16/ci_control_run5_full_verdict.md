# Контрольный прогон CI №5 — ПЕРВЫЙ ПОЛНЫЙ вердикт (ADR-768)

- SHA: `994ae86f6680fdcb1aa7b3440dca12795017d7f5` · прогон https://github.com/yurii-spa/SPA/actions/runs/39029518761 · окружение: {'python': '3.11.17', 'implementation': 'CPython', 'system': 'Linux', 'runner_os': 'Linux', 'image': 'ubuntu24', 'pytest': '9.1.1', 'SPA_ENV': 'ci', 'PYTHONHASHSEED': '0', 'workflow': 'SPA CI control (sharded full suite)', 'roots': ['tests', 'spa_core/tests', 'scripts/tests', 'spa_core/analytics/gross_of', 'research/cards', 'studio_shell']}
- Вердикт: **RED** · {"population": 134823, "files": 2689, "passed": 133974, "skipped": 719, "failed": 110, "error": 20, "not_obtained": 0, "collect_errors": 0, "shards_planned": 12, "shards_complete": 12}

Классификация (сравнение в одном окружении): #4 (`10314804a`, полный) → #5: новых 5 (все — регрессия дозапуска этой сессии:
вложенный pytest наследовал `SPA_PYTEST_RESUME_ONLY`; исправлено), прежних 125, исправлено 15, не получено 0.
`test_live_paths::test_the_beacon_and_the_journal_agree_on_one_tree` падает только в прогонах с дозапуском шарда (#4, #5) — гипотеза: порядок
импорта в сессии дозапуска; не исправлено. Остальные падения как «базовые» не объявляются — это перечень, а не приговор.

## Падения по файлам (130)

### `scripts/tests/test_check_concurrent_pytest.py` (3)
- `TestOpenFilesParsesRealLsof::test_a_live_process_holding_a_written_file_reads_READABLE` — failed (часть 5)
- `TestOpenFilesParsesRealLsof::test_a_live_process_whose_only_write_target_is_unlinked_reads_UNREADABLE` — failed (часть 5)
- `TestOpenFilesParsesRealLsof::test_a_real_file_open_for_writing_is_parsed_with_its_mode_and_inode` — failed (часть 5)

### `scripts/tests/test_fill_agent_passports.py` (1)
- `TestManifestFormatIsPreserved::test_manifest_on_disk_is_byte_identical_to_a_reserialization` — failed (часть 3)

### `scripts/tests/test_pytest_stream_record.py` (5)
- `test_a_killed_session_still_names_the_failure_and_the_test_it_died_on` — failed (часть 5)
- `test_a_session_that_reaches_the_end_says_so` — failed (часть 5)
- `test_without_the_env_var_the_plugin_writes_nothing_at_all` — failed (часть 5)
- `test_a_case_that_nulls_the_global_recorder_silences_the_rest_of_the_session` — failed (часть 5)
- `test_a_teardown_failure_keeps_the_plugin_counters_balanced` — failed (часть 5)

### `scripts/tests/test_shell_git_cd_target_census.py` (2)
- `RatchetOnTheRealTree::test_real_tree_subject_is_within_the_baseline` — failed (часть 0)
- `RatchetOnTheRealTree::test_the_ratchet_is_able_to_fail` — failed (часть 0)

### `spa_core/tests/test_act_day_recovery.py` (1)
- `TestTheHonestBatteryHoles::test_fractional_turnover_keeps_its_cents` — failed (часть 4)

### `spa_core/tests/test_adapter_status_writer_census.py` (2)
- `TestCensusRegressions::test_live_tree_is_green_at_its_declared_ceilings` — failed (часть 5)
- `TestProbe::test_green_on_the_whole_contour` — failed (часть 5)

### `spa_core/tests/test_announce_clock_door_census.py` (1)
- `TestSynthForm::test_an_unknown_directive_yields_a_string_and_the_DOOR_refuses_it` — failed (часть 5)

### `spa_core/tests/test_autonomy_mandate.py` (2)
- `TestWiredIntoTheMandatoryStep::test_mandate_line_survives_an_unmeasurable_office` — failed (часть 4)
- `TestWiredIntoTheMandatoryStep::test_office_step_prints_the_mandate_judgement` — failed (часть 4)

### `spa_core/tests/test_census_stage_root_contract.py` (1)
- `CensusStageRootContract::test_every_stage_census_puts_its_artifact_under_root_data` — failed (часть 2)

### `spa_core/tests/test_claude_run_timeout_ownership.py` (6)
- `OwnershipAtTimeout::test_10_normal_exit_does_not_kill_the_detached_child` — failed (часть 9)
- `OwnershipAtTimeout::test_2_3_4_6_timeout_kills_only_what_is_proven_ours` — failed (часть 9)
- `OwnershipAtTimeout::test_7_unresolved_ownership_returns_125_and_names_survivors` — failed (часть 9)
- `OwnershipAtTimeout::test_9_evidence_is_written_before_the_first_kill` — failed (часть 9)
- `TheInstrumentsAreNotOrnaments::test_with_run_id_the_same_scene_closes` — failed (часть 9)
- `SigtermIgnoredThenSigkill::test_sigterm_ignoring_tree_is_closed_by_sigkill_with_rc_124` — failed (часть 9)

### `spa_core/tests/test_constitution_right_to_fix.py` (4)
- `LiveControlOnTheRealTree::test_every_form_of_every_pair_is_a_declared_class` — error (часть 11)
- `LiveControlOnTheRealTree::test_the_first_axis_shift_rests_on_a_named_pair` — error (часть 11)
- `LiveControlOnTheRealTree::test_the_peer_axis_really_shifted` — error (часть 11)
- `LiveControlOnTheRealTree::test_the_shelf_is_readable_here_so_nothing_is_unmeasured` — error (часть 11)

### `spa_core/tests/test_decision_journal_coverage.py` (1)
- `ReaderPopulationRatchet::test_every_production_reader_is_in_the_population` — failed (часть 0)

### `spa_core/tests/test_decision_surface_census.py` (3)
- `LiveControlOnTheRealTree::test_the_measure_bites_here` — error (часть 10)
- `LiveControlOnTheRealTree::test_the_population_is_declared_and_non_empty` — error (часть 10)
- `LiveControlOnTheRealTree::test_the_senior_surface_is_asked_but_not_declared` — error (часть 10)

### `spa_core/tests/test_declared_git_environment.py` (1)
- `TheSuiteDeclaresItsCloneDepth::test_every_pytest_job_declares_full_history` — failed (часть 5)

### `spa_core/tests/test_document_field_reader.py` (4)
- `test_live_measurement_reports_both_liveness_numbers` — failed (часть 5)
- `test_live_measurement_answers_with_a_pair_of_numbers` — failed (часть 5)
- `test_blind_spots_name_the_one_sidedness_aloud` — failed (часть 5)
- `test_report_prints_the_pair_and_the_refusal_names` — failed (часть 5)

### `spa_core/tests/test_edge_boundary_dataflow_census.py` (1)
- `TestTheObserverIsNotPartOfItsOwnPopulation::test_the_census_screens_the_population_100_published` — failed (часть 6)

### `spa_core/tests/test_edge_downside_parity.py` (1)
- `test_downside_denominator_is_exactly_zero_where_volatility_is_not` — failed (часть 7)

### `spa_core/tests/test_finding_address_price.py` (1)
- `WiredIntoTheCensus::test_with_a_tree_both_are_measured` — failed (часть 6)

### `spa_core/tests/test_fixture_schema_gap_ratchet.py` (1)
- `test_the_door_sites_still_add_up_to_the_same_operand` — failed (часть 5)

### `spa_core/tests/test_invisible_consumer_scale.py` (1)
- `WiringTest::test_measure_calls_the_coordinate_and_stores_it_under_its_own_key` — failed (часть 9)

### `spa_core/tests/test_ledger_day_unit_census.py` (1)
- `ProbeRefusesAnUnobservedSubject::test_an_unobserved_subject_is_not_a_pass` — failed (часть 1)

### `spa_core/tests/test_list_identity_census.py` (3)
- `MeasureRefusesInsteadOfGuessing::test_a_measured_population_with_a_candidate_outside_is_a_finding` — failed (часть 2)
- `MeasureRefusesInsteadOfGuessing::test_a_measured_population_without_findings_is_clean` — failed (часть 2)
- `MeasureRefusesInsteadOfGuessing::test_all_readers_unmeasured_is_unmeasured_not_clean` — failed (часть 2)

### `spa_core/tests/test_live_paths.py` (1)
- `test_the_beacon_and_the_journal_agree_on_one_tree` — failed (часть 5)

### `spa_core/tests/test_no_import_time_clock_in_tests.py` (1)
- `TestNoImportTimeClockInTests::test_no_unreviewed_import_time_clock` — failed (часть 9)

### `spa_core/tests/test_office_absent_block_producer_aware.py` (2)
- `CensusRatchet::test_the_allowlist_keys_match_the_live_producer_exactly` — failed (часть 11)
- `CensusRatchet::test_the_exemption_covers_no_MORE_sites_than_it_names` — failed (часть 11)

### `spa_core/tests/test_office_declaration_doors.py` (1)
- `TheLiveAnswerOfTheOrder::test_every_office_artifact_has_a_measurable_producer_tick` — failed (часть 0)

### `spa_core/tests/test_office_subject_drift_producer_tick.py` (1)
- `test_the_live_office_can_measure_the_tick_of_every_artifact_it_reads` — failed (часть 7)

### `spa_core/tests/test_postgres_migration.py` (1)
- `TestMigrateCallsites::test_live_codebase_has_zero_raw_connects` — failed (часть 10)

### `spa_core/tests/test_publication_truth.py` (1)
- `BothPushersRunThePublicationGate::test_a_direct_push_of_an_unverified_shelf_is_blocked_by_either_pusher` — failed (часть 9)

### `spa_core/tests/test_python_git_ref_provenance.py` (4)
- `TestRatchet::test_real_tree_matches_the_frozen_baseline` — failed (часть 6)
- `RegistryGovernance::test_an_intact_baseline_passes` — failed (часть 6)
- `RegistryReactsToTheCensus::test_removing_an_unresolved_identity_reduces_the_debt` — failed (часть 6)
- `RegistryReactsToTheCensus::test_the_unchanged_census_is_green` — failed (часть 6)

### `spa_core/tests/test_recover_trusted_runtime.py` (1)
- `TestDryRunZeroMutation::test_dry_run_reaches_confirmed_broken_and_mutates_nothing` — failed (часть 3)

### `spa_core/tests/test_repair_phantom_intake_cards.py` (7)
- `test_phantom_closed_and_source_reopened` — failed (часть 2)
- `test_close_note_explains_it_was_not_the_owner` — failed (часть 2)
- `test_empty_output_signature_also_recognised` — failed (часть 2)
- `test_mass_case_all_of_them` — failed (часть 2)
- `test_source_still_open_is_not_disturbed` — failed (часть 2)
- `test_missing_source_is_reported_not_silently_dropped` — failed (часть 2)
- `test_rerun_is_idempotent` — failed (часть 2)

### `spa_core/tests/test_research_evidence_tracks.py` (1)
- `test_facts_jsonl_no_fact_lacks_a_citation_from_the_seed_file` — failed (часть 11)

### `spa_core/tests/test_rule_second_copy_census.py` (3)
- `LiveControlOnTheRealTree::test_accounting_identity_holds_on_the_real_tree` — error (часть 7)
- `LiveControlOnTheRealTree::test_every_printed_row_survives_an_independent_recheck` — error (часть 7)
- `LiveControlOnTheRealTree::test_the_real_tree_is_measured_at_all` — error (часть 7)

### `spa_core/tests/test_rule_second_copy_census_wiring.py` (2)
- `OfficeReadsTheNumberNotJustTheFile::test_declared_shape_is_the_shape_the_producer_actually_writes` — failed (часть 0)
- `TheGuardsOfThisInstrumentDoNotBecomeItsOwnFinding::test_own_test_files_are_not_rows` — failed (часть 0)

### `spa_core/tests/test_rule_second_copy_peer_axis.py` (1)
- `LiveControlOnTheRealTree::test_the_axis_is_not_empty_on_this_repository` — error (часть 5)

### `spa_core/tests/test_run_identity_key_price.py` (1)
- `BatteryHoleTests::test_the_guard_is_lowered_again_after_a_sweep` — failed (часть 7)

### `spa_core/tests/test_safe_terminate_ownership.py` (13)
- `OwnedIsOwnedAndForeignIsNot::test_a_child_without_our_stamp_is_NOT_OWNED` — failed (часть 9)
- `OwnedIsOwnedAndForeignIsNot::test_a_process_with_a_DIFFERENT_run_id_is_NOT_OWNED` — failed (часть 9)
- `OwnedIsOwnedAndForeignIsNot::test_our_own_stamped_child_is_OWNED` — failed (часть 9)
- `OwnedIsOwnedAndForeignIsNot::test_the_same_command_in_the_expected_cwd_is_OWNED` — failed (часть 9)
- `IdentityIsNotJustThePid::test_a_pinned_identity_that_no_longer_matches_is_IDENTITY_MISMATCH` — failed (часть 9)
- `IdentityIsNotJustThePid::test_the_matching_identity_is_OWNED` — failed (часть 9)
- `GoneIsIdempotentSuccess::test_an_already_exited_process_is_PROCESS_GONE` — failed (часть 9)
- `GoneIsIdempotentSuccess::test_terminating_a_gone_process_is_a_no_op_success` — failed (часть 9)
- `GoneIsIdempotentSuccess::test_the_call_is_idempotent` — failed (часть 9)
- `TerminationItself::test_a_sigterm_ignoring_owned_process_needs_KILL` — failed (часть 9)
- `TerminationItself::test_an_owned_process_is_terminated_by_TERM` — failed (часть 9)
- `TerminationItself::test_identity_change_between_TERM_and_KILL_blocks_the_KILL` — failed (часть 9)
- `NoSecretReachesTheEvidence::test_the_identity_tuple_carries_a_hash_not_the_command` — failed (часть 9)

### `spa_core/tests/test_shadow_tvl_provenance.py` (3)
- `TestAcceptanceProbe::test_probe_is_satisfied_on_this_tree` — failed (часть 5)
- `TestAcceptanceProbe::test_probe_refuses_when_a_number_rides_without_its_rod` — failed (часть 5)
- `TestAcceptanceProbe::test_probe_refuses_when_a_tvl_literal_still_reaches_the_number` — failed (часть 5)

### `spa_core/tests/test_shell_git_cd_repo_identity.py` (2)
- `GuardOnTheGuard::test_empty_baseline_makes_the_real_tree_run_red_by_name` — failed (часть 2)
- `GuardOnTheGuard::test_shipped_baseline_is_green_and_covers_the_measured_subject` — failed (часть 2)

### `spa_core/tests/test_site_snapshot_view_shape.py` (1)
- `TheViewCoversTheSnapshotShape::test_every_snapshot_field_is_covered_or_declared` — failed (часть 10)

### `spa_core/tests/test_slo_keepability.py` (1)
- `ExitCodesSeparateThreeOutcomes::test_everything_keepable_exits_zero` — failed (часть 2)

### `spa_core/tests/test_state_journal_coverage_audit.py` (1)
- `test_live_state_no_longer_carries_uncovered_chronicle` — failed (часть 7)

### `spa_core/tests/test_subject_population_census.py` (1)
- `PopulationCompletenessIsASeparateAssertion::test_the_precise_road_is_a_subset_of_the_recall_road` — failed (часть 0)

### `spa_core/tests/test_table_form_census.py` (9)
- `Wiring::test_a_coordinate_without_channels_says_unmeasured` — error (часть 7)
- `Wiring::test_a_coordinate_without_shares_says_unmeasured` — error (часть 7)
- `Wiring::test_a_report_without_the_key_says_unmeasured` — error (часть 7)
- `Wiring::test_a_single_missing_channel_is_named_not_skipped` — error (часть 7)
- `Wiring::test_measure_calls_the_coordinate` — error (часть 7)
- `Wiring::test_report_renders_the_section` — error (часть 7)
- `Wiring::test_the_coordinate_does_not_widen_the_declared_surfaces` — error (часть 7)
- `Wiring::test_the_coordinate_is_serialisable` — error (часть 7)
- `Wiring::test_the_live_tree_answers_the_order` — error (часть 7)

### `spa_core/tests/test_tail_value_divergence.py` (16)
- `AggregateTest::test_a_reachable_divergence_changes_the_verdict` — failed (часть 6)
- `AggregateTest::test_agreement_everywhere_is_its_own_verdict` — failed (часть 6)
- `AggregateTest::test_blindness_is_stated_not_implied` — failed (часть 6)
- `AggregateTest::test_counts_cover_every_read` — failed (часть 6)
- `AggregateTest::test_divergence_nobody_can_see_is_not_called_harmless` — failed (часть 6)
- `AggregateTest::test_documents_are_counted_not_reads` — failed (часть 6)
- `AggregateTest::test_kind_conflicts_are_counted_separately` — failed (часть 6)
- `AggregateTest::test_text_only_divergence_is_not_counted_as_divergence` — failed (часть 6)
- `WiringTest::test_measure_binds_the_step_and_returns_that_binding` — failed (часть 6)
- `ReportTest::test_measured_step_prints_both_numbers` — failed (часть 6)
- `WholeContourTest::test_reach_is_measured_for_every_costed_read` — failed (часть 6)
- `WholeContourTest::test_the_aggregate_reads_this_contour_end_to_end` — failed (часть 6)
- `AbsentReachIsNotAnOutcome::test_a_known_reach_still_measures` — failed (часть 6)
- `AbsentReachIsNotAnOutcome::test_an_unmeasured_reach_is_not_read_as_not_reaching` — failed (часть 6)
- `AbsentReachIsNotAnOutcome::test_kind_conflicts_are_still_counted_with_reach_present` — failed (часть 6)
- `AbsentReachIsNotAnOutcome::test_the_second_name_for_reach_is_gone_from_the_code` — failed (часть 6)

### `spa_core/tests/test_timeseries_lane_modules.py` (1)
- `test_falling_apy_riskier_than_rising[apy_tracker]` — failed (часть 3)

### `spa_core/tests/test_truncated_input_census.py` (1)
- `TheJanitorSeesEveryWorktree::test_trees_beyond_the_old_budget_are_still_found` — failed (часть 11)

### `spa_core/tests/test_unwired_guard_modules_ratchet.py` (2)
- `test_no_new_guard_module_is_left_unwired` — failed (часть 8)
- `test_fixed_modules_leave_the_census` — failed (часть 8)

### `spa_core/tests/test_unwired_registry_evidence.py` (1)
- `TestTheRuleOnTheRealRepo::test_the_carve_out_did_not_swallow_the_watch` — failed (часть 9)

### `spa_core/tests/test_unwired_scripts_ratchet.py` (1)
- `TestRatchet::test_no_NEW_unwired_script_appears` — failed (часть 2)

### `tests/cartographer/test_owner_briefing.py` (1)
- `ManifestTellsTheTruthPerStage::test_the_manifest_never_stores_a_remote_url_or_a_raw_response` — failed (часть 1)

### `tests/test_no_utcnow.py` (1)
- `test_no_bare_utcnow_in_runtime` — failed (часть 3)

### `tests/test_spaerror_complete.py` (1)
- `test_20_zero_bare_exceptions_in_spa_core` — failed (часть 8)
