# RM-TRUTH-01 Failure-Injection Census

Worktree: `/tmp/spa_rmt_fi` (detached at `origin/main` 688f2c4b9), no push, no prod/mirror writes.
Run: `TMPDIR=$(mktemp -d) SPA_ENV=ci PYTHONHASHSEED=0 python3 -m pytest -q -p no:randomly <node ids>` → **99 passed in 4.48s** (0 failed).

| # | Scenario | Test node id(s) | Result | Safe & visible? | Notes |
|---|---|---|---|---|---|
| 1 | sandbox tries to resolve prod data | `spa_core/tests/test_sandbox_prod_leak_inc1.py` | PASS | yes — refuses/redirects, named reason | INC-1 replay |
| 2 | fake future clock | `spa_core/tests/test_future_stamp_detector.py` | PASS | yes — flagged CORRUPT, not silently accepted | |
| 3 | old paper history missing | `spa_core/tests/test_paper_apy_staleness.py` | PASS | yes — stale, not served as fresh | |
| 4 | duplicate experiment id | `test_investment_cio_guards.py::test_idempotent_rerun_leaves_no_orphan_snapshot` | PASS | yes — same-date rerun produces no duplicate/orphan snapshot, ledger stays len 1 | finding #21 |
| 5 | forward-start mutation | `test_trading_research.py::test_reregistering_a_candidate_cannot_silently_change_its_forward_start` | PASS | yes — re-registration cannot move `forward_start` | ADR-590 |
| 6 | backfill pretending forward | `test_trading_research.py::test_backfill_bars_before_registration_are_never_counted_as_forward_observations` | PASS | yes — backfilled bars excluded from forward count | ADR-590 fix A |
| 7 | site stale | `spa_core/tests/test_site_freshness_c12_origin_operand.py` | PASS | yes | |
| 8 | site number differs from canonical | `scripts/tests/test_site_number_provenance.py` (FourOutcomes) | PASS | yes — 4 distinct outcomes: sourced/declared/UNDECLARED/unmeasured; 16 agreeing literals = 16 findings, not 0 | ADR-312, the "~3.3% vs 5.3%" incident |
| 9 | TARGET displayed as PAPER | **NEW**: `spa_core/tests/test_target_as_paper_new.py` (not committed) | PASS | yes — `TypeViolation` raised | Existing suite exercises BACKTEST→REALIZED_PAPER and TARGET→OBSERVED on the same guard line (`typed_numbers.py` L78), but no test exercised the TARGET→REALIZED_PAPER cell itself — wrote the 2 missing lines (+ positive control) |
| 10 | BACKTEST displayed as REALIZED | `test_typed_numbers_contract.py::test_backtest_number_refused_as_realized_paper` | PASS | yes | ADR-580 C2 |
| 11 | immature book gets annualised | `test_trading_research_read_model.py::test_performance_windows_are_not_enough_history_below_maturity` + `::test_performance_window_matures_past_the_threshold` | PASS | yes — below-maturity window refuses, positive control past threshold passes | |
| 12 | owner queue cache missing items | `test_owner_order_starvation_sees_the_other_copy.py::test_tree_only_sees_nothing_this_is_the_incident` | PASS | yes — tree-only view sees nothing; ref copy surfaces the starving order | the actual historical incident replay |
| 13 | prod-only closure | `test_decisions_triage.py::test_prod_only_cards_are_shown_in_their_own_group` | PASS | yes — own named group, not merged/hidden | |
| 14 | divergent owner decision | `test_owner_decision_stale_live_copy.py::test_stale_live_copy_is_refreshed_from_the_ref` | PASS | yes | |
| 15 | button renderer malformed | `test_owner_decisions_inline_lettered_options.py::test_the_real_disk_card_refuses_buttons_for_a_multi_step_section` | PASS | yes — refuses buttons, names the multi-step reason instead of rendering broken buttons | |
| 16 | agent log stale | `test_agent_health_array_calendar.py::test_novel_edge_rnd_still_flags_a_genuinely_missed_run` | PASS | yes — CRITICAL on a genuinely missed run | |
| 17 | agent exits once | `test_problem_store.py::test_first_sighting_alone_does_not_open_a_problem` + `::test_single_critical_in_an_otherwise_green_fleet_is_not_lost` | PASS | yes — no false alarm on one blip, but not lost either | |
| 18 | same agent exits repeatedly | `test_problem_store.py::test_repeated_failure_opens_exactly_one_problem_and_one_card` | PASS | yes — exactly one problem/card, not spammed | |
| 19 | same root cause across 5 agents | `test_problem_store.py::test_seven_degraded_domains_are_ONE_root_cause_not_seven_problems` | PASS | yes — collapses to one root cause | |
| 20 | backup same host | `test_backups_three_facts.py::test_same_host_offsite_is_never_green_even_with_local_and_drill_ok` | PASS | yes — same-host "offsite" never green | |
| 21 | backup missing ledger | `test_dr_ledger_coverage.py::test_every_declared_ledger_is_in_the_archive` | PASS | yes | |
| 22 | derived read model deleted | `test_trading_research_read_model.py::test_view_is_honestly_not_measured_for_an_empty_directory` | PASS | yes — "not measured", not a fabricated zero/healthy view | |
| 23 | Mission Control source stale | `test_mission_control_contract.py::test_stale_mirror_makes_the_owner_queue_and_board_stale` | PASS | yes | |
| 24 | Telegram service stale | `test_telegram_health.py::test_stale_beacon_means_the_loop_is_wedged` | PASS | yes | |
| 25 | OpenClaw token absent | — | **GAP** | — | "OpenClaw" (`ai.openclaw.gateway` / `~/.openclaw` local whisper server) is a third-party macOS app referenced only in `studio_shell/voice_server.py` (`OPENCLAW_STT` URL) and in `docs/rm_truth/O2_telegram.md` / `A5_owner_control.md`. There is no "token" concept for it in code — `_transcribe()` just tries the HTTP call and silently falls through to local whisper CLI on any exception (bare `except: pass`), with no test covering that fallback's visibility. Writing a proper test needs mocking `urllib.request.urlopen` + asserting the fallback still logs/returns an honest engine tag — more than "a few lines" and touches a server module without an isolated-fixture test harness already in place. Flagged as GAP, not written. |
| 26 | legacy web server serves forbidden path | `test_agent_servers_bind_loopback.py::TestAgentServersBindLoopback::test_every_stdlib_server_binds_loopback` | PASS | yes — covers the loopback-bind mitigation for the 2026-08-30 `com.spa.dashboard` incident (repo root incl. `.git` served to the LAN) | No separate test asserts an explicit 403/404 on a forbidden path (e.g. `../`); the only guard on this exact historical incident is the bind-loopback ratchet. Noted as a narrower match than the scenario name implies. |
| 27 | Oracle sees non-eligible candidate | `test_investment_cio_policy.py::test_observe_only_sleeve_never_eligible` | PASS | yes — an OBSERVE_ONLY sleeve never becomes eligible / never gets a weight | |
| 28 | Research Factory count confused with system-wide count | `test_company_truth_unknown.py::test_research_factory_present_is_measured` | PASS | yes — `reviewed_today` is a FLAG (`any(...)`), never a count; `capital_sherlock()["total"]` stays `None` even when the flag is `True`, so a bool can't be printed as «всего» | this is the literal historical defect named in the test's own comment |
| 29 | roadmap stale | `test_memory_architecture.py::test_truth_statuses_from_registry_canon_layer_and_shadow` | PASS | yes — `docs/OLD_ROADMAP.md` status resolves to `SUPERSEDED` | |
| 30 | superseded ADR treated current | same test | PASS | yes — superseded ADR-001 ranks below current ADR-002 that supersedes it | |
| 31 | memory returns old decision | same test | PASS | yes — current decision outranks the superseded one it replaces | |
| 32 | MemPalace index lost | `test_memory_architecture.py::test_index_rebuild_is_atomic_and_reproducible` | PASS | yes — deleting `index.db` and rebuilding is atomic/reproducible, no partial/corrupt state | |
| 33 | current memory index lost | `test_memory_architecture.py::test_missing_index_answers_nothing_rather_than_guessing` | PASS | yes — `search()` on a missing index returns `[]`, never a guess | |
| 34 | two active sources publish one metric | `test_site_content_audit.py::test_metric_divergence_only_hardcoded` | PASS | yes — `METRIC_DIVERGENCE` finding fires | |
| 35 | higher-risk TARGET ladder conflict | `test_typed_numbers_contract.py::test_target_ladder_conflict_is_flagged_when_higher_risk_target_is_lower` | PASS | yes | ADR-548 6a |
| 36 | investment readiness masquerading as overall health | `test_readiness_scopes.py::TestShapeAndNoRollup::test_exactly_six_scopes_no_aggregate` | PASS | yes — exactly 6 named scopes, never collapsed into one "overall" number | ADR-580 §C3 hard rule |
| 37 | one agent failure hidden under aggregate green | `test_problem_store.py::test_single_critical_in_an_otherwise_green_fleet_is_not_lost` | PASS | yes | also see readiness_scopes' no-rollup rule (#36) |
| 38 | Company Truth imported by an agent | `test_company_truth_import_ratchet.py::test_positive_control_a_planted_importer_is_caught_and_named` | PASS | yes — planted importer caught and named | |
| 39 | UI attempts a money action | `test_mission_no_money_action.py::TestUiNeverActs::test_no_form_tags` + `TestServerRefusesWrites::test_every_write_verb_maps_to_the_one_refusal_handler` | PASS | yes — no `<form>`/non-GET fetch in the UI; every write verb maps to a 405 refusal handler | |
| 40 | push over a moved origin (strict mode) | `test_push_expected_base_strict_mode.py::test_strict_mode_head_moved_stops_before_any_write_single_file` | PASS | yes — stops before any write when HEAD moved | |
| 41 | remote file >1 MB unreadable | `test_push_remote_blob_read.py::test_large_file_falls_back_to_blob_api` | PASS | yes — falls back to blob API rather than silently skipping the read | |
| 42 | Blob SHA mismatch | `test_push_remote_blob_read.py::test_blob_sha_mismatch_refuses_named` | PASS | yes — named refusal, not a silent accept | |
| 43 | kill-switch alert suppressed by Problem store | `test_agent_health_problem_push_linkage.py::test_kill_switch_is_outside_the_problem_store_source_set` + `::test_kill_switch_event_key_bypasses_agent_health_monitor_entirely` | PASS | yes — kill-switch alerts are explicitly routed OUTSIDE the problem-store dedup/suppression path | |

## Totals

- **COVERED_PASS:** 41
- **COVERED_FAIL:** 0
- **NEW_TEST_WRITTEN:** 1 (scenario 9, `spa_core/tests/test_target_as_paper_new.py` — content embedded in this report, saved in worktree only, **not committed**)
- **GAP:** 1 (scenario 25, OpenClaw token absence — no token concept in code; fallback path untested)

## New test file written (scenario 9), not committed

```python
"""New minimal test (NOT committed) — RM-TRUTH-01 failure-injection census scenario
'TARGET displayed as PAPER'. Exercises the same ADR-580 C2 guard as
test_backtest_number_refused_as_realized_paper / test_target_number_refused_as_observed
in spa_core/tests/test_typed_numbers_contract.py, but for the specific combination
(source_kind=TARGET, metric_type=REALIZED_PAPER) that neither existing test exercises.
"""
import pytest
from spa_core.reporting.typed_numbers import TypeViolation, typed_pct


def test_target_number_refused_as_realized_paper():
    with pytest.raises(TypeViolation):
        typed_pct(12.0, metric_type="REALIZED_PAPER", source="tier_bands.json balanced.band_en",
                  source_kind="TARGET")


def test_target_as_target_is_not_refused_positive_control():
    env = typed_pct(12.0, metric_type="TARGET", source="tier_bands.json balanced.band_en")
    assert env["metric_type"] == "TARGET"
```
