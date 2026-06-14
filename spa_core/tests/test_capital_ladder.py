#!/usr/bin/env python3
"""Tests for spa_core/governance/capital_ladder.py (MP-505).

unittest (НЕ pytest), без сети, вся персистентность — tempdir.
"""
from __future__ import annotations

import json
import os
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from spa_core.governance.capital_ladder import (
    ATTESTATIONS_FILENAME,
    CLIMB_GATES,
    EQUITY_FILENAME,
    GOLIVE_STATUS_FILENAME,
    HISTORY_MAX,
    INCIDENT_THRESHOLD_PCT,
    LADDER,
    MAX_LEVEL,
    PT_STATUS_FILENAME,
    STATUS_FILENAME,
    CapitalLadder,
    apply_auto_demotions,
    days_since_last_incident,
    detect_incidents,
    evaluate_climb,
    load_state,
    main,
)

NOW = datetime(2026, 6, 11, 12, 0, 0, tzinfo=timezone.utc)


def _bar(date: str, ret: float = 0.0, open_e: float = 100000.0,
         low_e: float | None = None) -> dict:
    return {
        "date": date,
        "daily_return_pct": ret,
        "open_equity": open_e,
        "low_equity": low_e if low_e is not None else open_e,
        "close_equity": open_e,
    }


def _write(data_dir: Path, name: str, doc) -> None:
    (data_dir / name).write_text(
        json.dumps(doc, ensure_ascii=False), encoding="utf-8"
    )


def _seed_healthy(data_dir: Path, days: int = 30, golive_ready: bool = True) -> None:
    daily = [_bar(f"2026-05-{d:02d}", ret=0.01) for d in range(1, min(days, 28) + 1)]
    _write(data_dir, EQUITY_FILENAME, {"is_demo": False, "daily": daily})
    _write(data_dir, PT_STATUS_FILENAME,
           {"is_demo": False, "days_running": days, "current_equity": 100017.3})
    _write(data_dir, GOLIVE_STATUS_FILENAME, {"ready": golive_ready})


class LadderDeclarationTest(unittest.TestCase):
    def test_ladder_has_six_levels_l0_to_l5(self):
        self.assertEqual(len(LADDER), 6)
        self.assertEqual([l.code for l in LADDER],
                         ["L0", "L1", "L2", "L3", "L4", "L5"])
        self.assertEqual(MAX_LEVEL, 5)

    def test_ladder_levels_match_architecture_v2_s8(self):
        self.assertEqual(LADDER[0].name, "paper")
        self.assertEqual(LADDER[0].aum_cap_usd, 100_000.0)
        self.assertEqual(LADDER[1].name, "pilot")
        self.assertEqual(LADDER[5].name, "institutional")
        self.assertEqual(LADDER[5].aum_cap_usd, 100_000_000.0)

    def test_every_climb_target_has_gates(self):
        self.assertEqual(sorted(CLIMB_GATES.keys()), [1, 2, 3, 4, 5])
        for gates in CLIMB_GATES.values():
            self.assertTrue(gates)


class DetectIncidentsTest(unittest.TestCase):
    def test_no_incidents_on_calm_track(self):
        daily = [_bar("2026-06-01", ret=0.05), _bar("2026-06-02", ret=-0.5)]
        self.assertEqual(detect_incidents(daily), [])

    def test_close_to_close_loss_exactly_1pct_is_incident(self):
        inc = detect_incidents([_bar("2026-06-01", ret=-1.0)])
        self.assertEqual(len(inc), 1)
        self.assertEqual(inc[0]["kind"], "close_to_close")
        self.assertEqual(inc[0]["loss_pct"], 1.0)

    def test_close_to_close_loss_above_1pct_is_incident(self):
        inc = detect_incidents([_bar("2026-06-01", ret=-2.5)])
        self.assertEqual(len(inc), 1)
        self.assertEqual(inc[0]["loss_pct"], 2.5)

    def test_loss_just_below_1pct_is_not_incident(self):
        self.assertEqual(detect_incidents([_bar("2026-06-01", ret=-0.999)]), [])

    def test_intraday_open_to_low_drawdown_is_incident(self):
        # open 100000 → low 98900 = 1.1% intraday, close flat
        inc = detect_incidents([_bar("2026-06-01", ret=0.0,
                                     open_e=100000.0, low_e=98900.0)])
        self.assertEqual(len(inc), 1)
        self.assertEqual(inc[0]["kind"], "intraday")
        self.assertAlmostEqual(inc[0]["loss_pct"], 1.1, places=6)

    def test_intraday_below_threshold_is_not_incident(self):
        inc = detect_incidents([_bar("2026-06-01", ret=0.0,
                                     open_e=100000.0, low_e=99100.0)])
        self.assertEqual(inc, [])

    def test_garbage_bars_skipped_silently(self):
        daily = ["junk", 42, None, {"date": "not-a-date", "daily_return_pct": -5},
                 {"date": "2026-06-01", "daily_return_pct": "NaNish"},
                 _bar("2026-06-02", ret=-1.5)]
        inc = detect_incidents(daily)
        self.assertEqual([i["date"] for i in inc], ["2026-06-02"])

    def test_non_list_input_returns_empty(self):
        self.assertEqual(detect_incidents(None), [])
        self.assertEqual(detect_incidents({"daily": []}), [])

    def test_incidents_sorted_by_date_deterministic(self):
        daily = [_bar("2026-06-03", ret=-1.2), _bar("2026-06-01", ret=-3.0)]
        inc1 = detect_incidents(daily)
        inc2 = detect_incidents(daily)
        self.assertEqual([i["date"] for i in inc1], ["2026-06-01", "2026-06-03"])
        self.assertEqual(inc1, inc2)

    def test_custom_threshold_respected(self):
        daily = [_bar("2026-06-01", ret=-1.5)]
        self.assertEqual(detect_incidents(daily, threshold_pct=2.0), [])
        self.assertEqual(len(detect_incidents(daily, threshold_pct=1.5)), 1)


class AutoDemotionTest(unittest.TestCase):
    def test_single_incident_demotes_one_level(self):
        level, trans = apply_auto_demotions(
            2, [{"date": "2026-06-01", "loss_pct": 1.5, "kind": "close_to_close"}])
        self.assertEqual(level, 1)
        self.assertEqual(len(trans), 1)
        self.assertEqual(trans[0]["from_level"], 2)
        self.assertEqual(trans[0]["to_level"], 1)
        self.assertEqual(trans[0]["kind"], "auto_demotion")

    def test_two_incidents_demote_two_levels(self):
        level, trans = apply_auto_demotions(
            3, [{"date": "2026-06-01", "loss_pct": 1.0, "kind": "intraday"},
                {"date": "2026-06-02", "loss_pct": 2.0, "kind": "intraday"}])
        self.assertEqual(level, 1)
        self.assertEqual([(t["from_level"], t["to_level"]) for t in trans],
                         [(3, 2), (2, 1)])

    def test_demotion_floors_at_l0(self):
        level, trans = apply_auto_demotions(
            0, [{"date": "2026-06-01", "loss_pct": 5.0, "kind": "intraday"}])
        self.assertEqual(level, 0)
        self.assertEqual(trans[0]["kind"], "incident_at_floor")
        self.assertEqual(trans[0]["to_level"], 0)

    def test_no_incidents_keeps_level(self):
        level, trans = apply_auto_demotions(4, [])
        self.assertEqual(level, 4)
        self.assertEqual(trans, [])

    def test_out_of_range_level_clamped(self):
        level, _ = apply_auto_demotions(99, [])
        self.assertEqual(level, MAX_LEVEL)
        level, _ = apply_auto_demotions(-3, [])
        self.assertEqual(level, 0)


class DaysSinceIncidentTest(unittest.TestCase):
    def test_none_when_no_incidents(self):
        self.assertIsNone(days_since_last_incident([], NOW))

    def test_days_counted_from_latest_incident(self):
        inc = [{"date": "2026-06-01"}, {"date": "2026-05-01"}]
        self.assertEqual(days_since_last_incident(inc, NOW), 10)

    def test_garbage_entries_ignored(self):
        self.assertIsNone(days_since_last_incident(
            [{"date": "garbage"}, "x", None], NOW))


class EvaluateClimbTest(unittest.TestCase):
    def test_l0_to_l1_eligible_with_all_gates(self):
        v = evaluate_climb(
            0, golive_ready=True, track_days=30, days_no_incident=None,
            attestations={"e2e_harness_green": True, "safe_configured": True,
                          "owner_approval_adr": True})
        self.assertTrue(v.eligible)
        self.assertEqual(v.to_level, 1)
        self.assertTrue(all(v.gates.values()))
        self.assertEqual(v.blockers, [])

    def test_l0_to_l1_blocked_when_golive_not_ready(self):
        v = evaluate_climb(
            0, golive_ready=False, track_days=30, days_no_incident=None,
            attestations={"e2e_harness_green": True, "safe_configured": True,
                          "owner_approval_adr": True})
        self.assertFalse(v.eligible)
        self.assertFalse(v.gates["golive_ready"])
        self.assertTrue(any("MP-006" in b for b in v.blockers))

    def test_l0_to_l1_blocked_when_track_too_short(self):
        v = evaluate_climb(
            0, golive_ready=True, track_days=29, days_no_incident=None,
            attestations={"e2e_harness_green": True, "safe_configured": True,
                          "owner_approval_adr": True})
        self.assertFalse(v.eligible)
        self.assertFalse(v.gates["track_days_ge_30"])

    def test_owner_approval_always_required(self):
        v = evaluate_climb(
            0, golive_ready=True, track_days=30, days_no_incident=None,
            attestations={"e2e_harness_green": True, "safe_configured": True})
        self.assertFalse(v.eligible)
        self.assertFalse(v.gates["owner_approval_adr"])
        self.assertTrue(any("owner_approval_adr" in b for b in v.blockers))

    def test_l1_to_l2_blocked_by_recent_incident(self):
        att = {"apy_ge_benchmark_plus_1pp": True,
               "kill_switch_drill_passed": True, "owner_approval_adr": True}
        v = evaluate_climb(1, golive_ready=True, track_days=120,
                           days_no_incident=10, attestations=att)
        self.assertFalse(v.eligible)
        self.assertFalse(v.gates["no_incident_days_ge_90"])
        v_ok = evaluate_climb(1, golive_ready=True, track_days=120,
                              days_no_incident=90, attestations=att)
        self.assertTrue(v_ok.gates["no_incident_days_ge_90"])

    def test_l1_to_l2_no_incident_ever_passes_gate(self):
        v = evaluate_climb(1, golive_ready=True, track_days=120,
                           days_no_incident=None, attestations={})
        self.assertTrue(v.gates["no_incident_days_ge_90"])

    def test_l3_to_l4_requires_365_days(self):
        att = {k: True for k in ("audit_2_passed", "bug_bounty_live",
                                 "proof_of_track_onchain", "owner_approval_adr")}
        v = evaluate_climb(3, golive_ready=True, track_days=364,
                           days_no_incident=None, attestations=att)
        self.assertFalse(v.gates["track_days_ge_365"])
        v_ok = evaluate_climb(3, golive_ready=True, track_days=365,
                              days_no_incident=None, attestations=att)
        self.assertTrue(v_ok.eligible)

    def test_l5_has_no_next_level(self):
        v = evaluate_climb(5, golive_ready=True, track_days=10000,
                           days_no_incident=None, attestations={})
        self.assertIsNone(v.to_level)
        self.assertFalse(v.eligible)
        self.assertTrue(any("top level" in b for b in v.blockers))

    def test_attestations_none_treated_as_empty(self):
        v = evaluate_climb(0, golive_ready=True, track_days=30,
                           days_no_incident=None, attestations=None)
        self.assertFalse(v.eligible)

    def test_attestation_must_be_literal_true(self):
        v = evaluate_climb(
            0, golive_ready=True, track_days=30, days_no_incident=None,
            attestations={"e2e_harness_green": "yes", "safe_configured": 1,
                          "owner_approval_adr": True})
        self.assertFalse(v.gates["e2e_harness_green"])
        self.assertFalse(v.gates["safe_configured"])

    def test_climb_verdict_is_advisory(self):
        v = evaluate_climb(0, golive_ready=True, track_days=30,
                           days_no_incident=None, attestations={})
        self.assertIn("advisory", v.to_dict()["note"])

    def test_deterministic_same_inputs_same_verdict(self):
        kw = dict(golive_ready=True, track_days=45, days_no_incident=12,
                  attestations={"owner_approval_adr": True})
        self.assertEqual(evaluate_climb(1, **kw).to_dict(),
                         evaluate_climb(1, **kw).to_dict())


class PersistenceTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.data_dir = Path(self._tmp.name)
        self.addCleanup(self._tmp.cleanup)

    def _run(self, write: bool = True, now: datetime = NOW):
        return CapitalLadder(data_dir=self.data_dir, now=now).run(write=write)

    def test_empty_data_dir_defaults_to_l0_no_crash(self):
        result = self._run()
        self.assertEqual(result.level.code, "L0")
        self.assertTrue(result.notes)  # честные пометки про отсутствующие файлы
        self.assertTrue((self.data_dir / STATUS_FILENAME).exists())

    def test_status_file_schema(self):
        _seed_healthy(self.data_dir)
        self._run()
        doc = json.loads((self.data_dir / STATUS_FILENAME).read_text())
        for key in ("source", "current_level", "level_code", "aum_cap_usd",
                    "climb", "ladder", "history", "processed_incident_dates",
                    "incident_threshold_pct", "is_demo"):
            self.assertIn(key, doc)
        self.assertEqual(doc["source"], "capital_ladder")
        self.assertIs(doc["is_demo"], False)
        self.assertEqual(doc["incident_threshold_pct"], INCIDENT_THRESHOLD_PCT)
        self.assertEqual(len(doc["ladder"]), 6)

    def test_check_mode_does_not_write(self):
        _seed_healthy(self.data_dir)
        self._run(write=False)
        self.assertFalse((self.data_dir / STATUS_FILENAME).exists())

    def test_atomic_write_leaves_no_tmp_files(self):
        _seed_healthy(self.data_dir)
        self._run()
        leftovers = [p for p in self.data_dir.iterdir() if p.suffix == ".tmp"]
        self.assertEqual(leftovers, [])

    def test_corrupt_state_file_tolerated(self):
        (self.data_dir / STATUS_FILENAME).write_text("{not json!!", encoding="utf-8")
        _seed_healthy(self.data_dir)
        result = self._run()
        self.assertEqual(result.level.code, "L0")
        json.loads((self.data_dir / STATUS_FILENAME).read_text())  # перезаписан валидным

    def test_corrupt_equity_and_golive_tolerated(self):
        (self.data_dir / EQUITY_FILENAME).write_text("][", encoding="utf-8")
        (self.data_dir / GOLIVE_STATUS_FILENAME).write_text("xx", encoding="utf-8")
        result = self._run()
        self.assertEqual(result.level.code, "L0")
        self.assertTrue(any(EQUITY_FILENAME in n for n in result.notes))
        self.assertTrue(any(GOLIVE_STATUS_FILENAME in n for n in result.notes))

    def test_incident_demotes_persisted_level(self):
        _seed_healthy(self.data_dir)
        _write(self.data_dir, STATUS_FILENAME,
               {"current_level": 2, "processed_incident_dates": [], "history": []})
        _write(self.data_dir, EQUITY_FILENAME,
               {"is_demo": False, "daily": [_bar("2026-06-10", ret=-1.0)]})
        result = self._run()
        self.assertEqual(result.level.level, 1)
        self.assertEqual(len(result.demotions), 1)
        doc = json.loads((self.data_dir / STATUS_FILENAME).read_text())
        self.assertEqual(doc["current_level"], 1)
        self.assertIn("2026-06-10", doc["processed_incident_dates"])
        self.assertEqual(doc["history"][-1]["kind"], "auto_demotion")

    def test_same_incident_not_processed_twice(self):
        _seed_healthy(self.data_dir)
        _write(self.data_dir, STATUS_FILENAME,
               {"current_level": 3, "processed_incident_dates": [], "history": []})
        _write(self.data_dir, EQUITY_FILENAME,
               {"is_demo": False, "daily": [_bar("2026-06-10", ret=-2.0)]})
        first = self._run()
        self.assertEqual(first.level.level, 2)
        second = self._run()  # тот же инцидент — повторного спуска нет
        self.assertEqual(second.level.level, 2)
        self.assertEqual(second.demotions, [])

    def test_incident_below_threshold_does_not_demote(self):
        _write(self.data_dir, STATUS_FILENAME,
               {"current_level": 2, "processed_incident_dates": [], "history": []})
        _write(self.data_dir, EQUITY_FILENAME,
               {"is_demo": False, "daily": [_bar("2026-06-10", ret=-0.99)]})
        result = self._run()
        self.assertEqual(result.level.level, 2)
        self.assertEqual(result.demotions, [])

    def test_history_rotation_capped_at_500(self):
        old_history = [{"from_level": 1, "to_level": 0, "kind": "auto_demotion",
                        "reason": f"old-{i}"} for i in range(HISTORY_MAX + 50)]
        _write(self.data_dir, STATUS_FILENAME,
               {"current_level": 1, "processed_incident_dates": [],
                "history": old_history})
        _write(self.data_dir, EQUITY_FILENAME,
               {"is_demo": False, "daily": [_bar("2026-06-10", ret=-1.5)]})
        self._run()
        doc = json.loads((self.data_dir / STATUS_FILENAME).read_text())
        self.assertEqual(len(doc["history"]), HISTORY_MAX)
        self.assertEqual(doc["history"][-1]["kind"], "auto_demotion")  # новый — в хвосте

    def test_climb_eligible_l0_to_l1_with_real_shaped_data_and_attestations(self):
        _seed_healthy(self.data_dir, days=30, golive_ready=True)
        _write(self.data_dir, ATTESTATIONS_FILENAME,
               {"e2e_harness_green": True, "safe_configured": True,
                "owner_approval_adr": True})
        result = self._run()
        self.assertEqual(result.level.code, "L0")  # eligible НЕ значит поднялись
        self.assertTrue(result.climb.eligible)
        doc = json.loads((self.data_dir / STATUS_FILENAME).read_text())
        self.assertTrue(doc["climb"]["eligible"])
        self.assertEqual(doc["current_level"], 0)  # подъём только ADR+Owner

    def test_climb_not_eligible_without_attestations(self):
        _seed_healthy(self.data_dir, days=30, golive_ready=True)
        result = self._run()
        self.assertFalse(result.climb.eligible)
        self.assertFalse(result.climb.gates["e2e_harness_green"])

    def test_track_days_fallback_to_equity_bars(self):
        _write(self.data_dir, EQUITY_FILENAME,
               {"is_demo": False,
                "daily": [_bar(f"2026-06-0{d}") for d in range(1, 6)]})
        result = self._run()
        self.assertTrue(any("fallback" in n for n in result.notes))
        doc = json.loads((self.data_dir / STATUS_FILENAME).read_text())
        self.assertEqual(doc["track_days"], 5)

    def test_deterministic_run_same_inputs_same_status(self):
        _seed_healthy(self.data_dir)
        self._run()
        doc1 = json.loads((self.data_dir / STATUS_FILENAME).read_text())
        self._run()
        doc2 = json.loads((self.data_dir / STATUS_FILENAME).read_text())
        self.assertEqual(doc1, doc2)

    def test_load_state_defaults(self):
        state = load_state(self.data_dir)
        self.assertEqual(state["current_level"], 0)
        self.assertEqual(state["processed_incident_dates"], [])
        self.assertEqual(state["history"], [])

    def test_load_state_ignores_out_of_range_level(self):
        _write(self.data_dir, STATUS_FILENAME, {"current_level": 42})
        self.assertEqual(load_state(self.data_dir)["current_level"], 0)
        _write(self.data_dir, STATUS_FILENAME, {"current_level": "L3"})
        self.assertEqual(load_state(self.data_dir)["current_level"], 0)

    def test_summary_renders_without_crash(self):
        _seed_healthy(self.data_dir)
        text = self._run().summary()
        self.assertIn("CAPITAL LADDER", text)
        self.assertIn("L0", text)


class CliTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.data_dir = Path(self._tmp.name)
        self.addCleanup(self._tmp.cleanup)

    def test_cli_check_exit_0_and_no_write(self):
        _seed_healthy(self.data_dir)
        rc = main(["--check", "--data-dir", str(self.data_dir)])
        self.assertEqual(rc, 0)
        self.assertFalse((self.data_dir / STATUS_FILENAME).exists())

    def test_cli_run_exit_0_and_writes_status(self):
        _seed_healthy(self.data_dir)
        rc = main(["--run", "--data-dir", str(self.data_dir)])
        self.assertEqual(rc, 0)
        self.assertTrue((self.data_dir / STATUS_FILENAME).exists())

    def test_cli_run_on_empty_dir_no_traceback(self):
        rc = main(["--run", "--data-dir", str(self.data_dir)])
        self.assertEqual(rc, 0)

    def test_no_llm_sdk_imports_in_module(self):
        import spa_core.governance.capital_ladder as mod
        src = Path(mod.__file__).read_text(encoding="utf-8")
        for forbidden in ("anthropic", "openai", "langchain"):
            self.assertNotIn(f"import {forbidden}", src)


if __name__ == "__main__":
    unittest.main()
