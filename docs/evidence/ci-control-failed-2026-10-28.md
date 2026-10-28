# Упавшие на `main` поимённо — замер контрольного прогона 28.10

> **Это ЗАМЕР с адресом, а не список из головы.** Источник: артефакт `ci-control-report`
> прогона **40693235752** (`SPA CI control (sharded full suite)`, schedule, 2026-10-28T13:05Z),
> мерянный коммит **25eccb3a5**. Вердикт читателя (`scripts/ci_control_verdict.py`, ADR-845):
> **RED** · `failed=72` · `shards=12/12` · `not_obtained=0` · `collect_errors=0` ·
> `population=136933` · `passed=136142` · `skipped=719` · окружение python 3.11.17 /
> pytest 9.1.1 / `SPA_ENV=ci` / `PYTHONHASHSEED=0`.
>
> **У `SPA CI` на `main` этого спрашивать нельзя** (ADR-844): его вердикт уничтожает
> следующий пуш. Список обновлять ТОЛЬКО перечитав артефакт, а не правкой текста.
>
> Замер прошлой головы давал **57** (G845/G846); на `25eccb3a5` их **72**. Класс РОС,
> и это видно только отсюда.

## По файлам (46 файлов, 72 имён)

### `spa_core/tests/test_no_regression_producer_wiring.py` — 5
- `TactIsDecidedByTheFile::test_inside_the_tact_no_tree_is_built_at_all` · failed
- `TheProbeMeasuresTheOutcome::test_green_on_a_whole_contour` · failed
- `TheProbeMeasuresTheOutcome::test_red_when_the_live_artifact_is_older_than_its_own_slo` · failed
- `TheProbeMeasuresTheOutcome::test_the_probe_refuses_an_argument_instead_of_ignoring_it` · failed
- `TheProbeMeasuresTheOutcome::test_unmeasured_when_the_live_artifact_has_no_readable_stamp` · failed

### `spa_core/tests/test_document_field_reader.py` — 4
- `test_blind_spots_name_the_one_sidedness_aloud` · failed
- `test_live_measurement_answers_with_a_pair_of_numbers` · failed
- `test_live_measurement_reports_both_liveness_numbers` · failed
- `test_report_prints_the_pair_and_the_refusal_names` · failed

### `spa_core/tests/test_python_git_ref_provenance.py` — 4
- `RegistryGovernance::test_an_intact_baseline_passes` · failed
- `RegistryReactsToTheCensus::test_removing_an_unresolved_identity_reduces_the_debt` · failed
- `RegistryReactsToTheCensus::test_the_unchanged_census_is_green` · failed
- `TestRatchet::test_real_tree_matches_the_frozen_baseline` · failed

### `scripts/tests/test_check_concurrent_pytest.py` — 3
- `TestOpenFilesParsesRealLsof::test_a_live_process_holding_a_written_file_reads_READABLE` · failed
- `TestOpenFilesParsesRealLsof::test_a_live_process_whose_only_write_target_is_unlinked_reads_UNREADABLE` · failed
- `TestOpenFilesParsesRealLsof::test_a_real_file_open_for_writing_is_parsed_with_its_mode_and_inode` · failed

### `spa_core/tests/test_absent_observation_ratchet.py` — 3
- `test_baseline_and_tree_agree_member_for_member` · failed
- `test_ceiling_is_reanchoring_not_growth` · failed
- `test_tree_introduces_no_new_member` · failed

### `spa_core/tests/test_fixture_schema_gap_ratchet.py` — 3
- `test_every_outcome_matches_its_declared_addend` · failed
- `test_no_key_carries_more_unfed_paths_than_the_baseline` · failed
- `test_the_door_sites_still_add_up_to_the_same_operand` · failed

### `spa_core/tests/test_shadow_tvl_provenance.py` — 3
- `TestAcceptanceProbe::test_probe_is_satisfied_on_this_tree` · failed
- `TestAcceptanceProbe::test_probe_refuses_when_a_number_rides_without_its_rod` · failed
- `TestAcceptanceProbe::test_probe_refuses_when_a_tvl_literal_still_reaches_the_number` · failed

### `spa_core/tests/test_tail_value_divergence.py` — 3
- `AbsentReachIsNotAnOutcome::test_the_second_name_for_reach_is_gone_from_the_code` · failed
- `WholeContourTest::test_reach_is_measured_for_every_costed_read` · failed
- `WiringTest::test_measure_binds_the_step_and_returns_that_binding` · failed

### `scripts/tests/test_shell_git_cd_target_census.py` — 2
- `RatchetOnTheRealTree::test_real_tree_subject_is_within_the_baseline` · failed
- `RatchetOnTheRealTree::test_the_ratchet_is_able_to_fail` · failed

### `spa_core/tests/test_adapter_status_writer_census.py` — 2
- `TestCensusRegressions::test_live_tree_is_green_at_its_declared_ceilings` · failed
- `TestProbe::test_green_on_the_whole_contour` · failed

### `spa_core/tests/test_office_absent_block_producer_aware.py` — 2
- `CensusRatchet::test_the_allowlist_keys_match_the_live_producer_exactly` · failed
- `CensusRatchet::test_the_exemption_covers_no_MORE_sites_than_it_names` · failed

### `spa_core/tests/test_run_identity_key_price.py` — 2
- `BatteryHoleTests::test_the_guard_is_lowered_again_after_a_sweep` · failed
- `BatteryHoleTests::test_the_instrument_excludes_itself_by_naming_the_reason` · failed

### `spa_core/tests/test_shell_git_cd_repo_identity.py` — 2
- `GuardOnTheGuard::test_empty_baseline_makes_the_real_tree_run_red_by_name` · failed
- `GuardOnTheGuard::test_shipped_baseline_is_green_and_covers_the_measured_subject` · failed

### `tests/test_dead_code_resolved.py` — 2
- `TestScannerImprovement::test_15_todo_count_le_15` · failed
- `TestScannerImprovement::test_16_unused_imports_decreased` · failed

### `scripts/tests/test_fill_agent_passports.py` — 1
- `TestManifestFormatIsPreserved::test_manifest_on_disk_is_byte_identical_to_a_reserialization` · failed

### `spa_core/tests/test_absent_observation_probe.py` — 1
- `ProbeIsGreenOnTheWholeContour::test_the_live_tree_answers_satisfied_today` · failed

### `spa_core/tests/test_act_day_recovery.py` — 1
- `TestTheHonestBatteryHoles::test_fractional_turnover_keeps_its_cents` · failed

### `spa_core/tests/test_announce_clock_door_census.py` — 1
- `TestSynthForm::test_an_unknown_directive_yields_a_string_and_the_DOOR_refuses_it` · failed

### `spa_core/tests/test_branch_queue_dropped_decision.py` — 1
- `test_the_triage_card_declares_the_three_branch_cards` · failed

### `spa_core/tests/test_card_acceptance.py` — 1
- `TestRegisteredProbesAreReal::test_every_registered_probe_returns_a_known_verdict` · failed

### `spa_core/tests/test_census_stage_root_contract.py` — 1
- `CensusStageRootContract::test_every_stage_census_puts_its_artifact_under_root_data` · failed

### `spa_core/tests/test_child_pytest_rootdir.py` — 1
- `test_every_child_pytest_run_is_anchored` · failed

### `spa_core/tests/test_decision_journal_coverage.py` — 1
- `ReaderPopulationRatchet::test_every_production_reader_is_in_the_population` · failed

### `spa_core/tests/test_door_sites_operand_probe.py` — 1
- `WholeContour::test_the_real_tree_is_satisfied` · failed

### `spa_core/tests/test_edge_boundary_dataflow_census.py` — 1
- `TestTheObserverIsNotPartOfItsOwnPopulation::test_the_census_screens_the_population_100_published` · failed

### `spa_core/tests/test_edge_downside_parity.py` — 1
- `test_downside_denominator_is_exactly_zero_where_volatility_is_not` · failed

### `spa_core/tests/test_edge_tuw_unsmooth.py` — 1
- `test_constant_series_autocorrelation_is_unmeasured_not_zero` · failed

### `spa_core/tests/test_failed_name_survival_census.py` — 1
- `RealTreeAgeAxis::test_real_tree_the_artifact_store_now_has_exactly_one_named_asker` · failed

### `spa_core/tests/test_inbox_acceptance_ratchet.py` — 1
- `test_no_new_card_is_in_work_without_a_criterion` · failed

### `spa_core/tests/test_investor_report.py` — 1
- `test_audit_trail_from_temp_db` · failed

### `spa_core/tests/test_invisible_consumer_scale.py` — 1
- `WiringTest::test_measure_calls_the_coordinate_and_stores_it_under_its_own_key` · failed

### `spa_core/tests/test_no_import_time_clock_in_tests.py` — 1
- `TestNoImportTimeClockInTests::test_no_unreviewed_import_time_clock` · failed

### `spa_core/tests/test_office_declaration_doors.py` — 1
- `TheLiveAnswerOfTheOrder::test_the_default_ts_door_does_not_grow` · failed

### `spa_core/tests/test_postgres_migration.py` — 1
- `TestMigrateCallsites::test_live_codebase_has_zero_raw_connects` · failed

### `spa_core/tests/test_recover_trusted_runtime.py` — 1
- `TestDryRunZeroMutation::test_dry_run_reaches_confirmed_broken_and_mutates_nothing` · failed

### `spa_core/tests/test_research_evidence_tracks.py` — 1
- `test_facts_jsonl_no_fact_lacks_a_citation_from_the_seed_file` · failed

### `spa_core/tests/test_s49_every_criterion_is_bound.py` — 1
- `EveryCriterionIsBound::test_the_subject_of_ADR_811_is_bound_by_name` · failed

### `spa_core/tests/test_script_path_launch_imports.py` — 1
- `TestPathLaunchImportRatchet::test_no_new_script_breaks_when_launched_by_path` · failed

### `spa_core/tests/test_site_snapshot_view_shape.py` — 1
- `TheViewCoversTheSnapshotShape::test_every_snapshot_field_is_covered_or_declared` · failed

### `spa_core/tests/test_slo_report_line_reader.py` — 1
- `SpyRecordsWhatTheDoorAsked::test_the_real_module_is_put_back_after_the_observation` · failed

### `spa_core/tests/test_subject_population_census.py` — 1
- `PopulationCompletenessIsASeparateAssertion::test_the_precise_road_is_a_subset_of_the_recall_road` · failed

### `spa_core/tests/test_truncated_input_census.py` — 1
- `TheJanitorSeesEveryWorktree::test_trees_beyond_the_old_budget_are_still_found` · failed

### `spa_core/tests/test_unwired_guard_modules_ratchet.py` — 1
- `test_no_new_guard_module_is_left_unwired` · failed

### `spa_core/tests/test_unwired_registry_evidence.py` — 1
- `TestTheRuleOnTheRealRepo::test_the_carve_out_did_not_swallow_the_watch` · failed

### `tests/test_no_utcnow.py` — 1
- `test_no_bare_utcnow_in_runtime` · failed

### `tests/test_spaerror_complete.py` — 1
- `test_20_zero_bare_exceptions_in_spa_core` · failed

