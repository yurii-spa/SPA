"""
Tests for MP-1149: DeFiProtocolEmergencyWithdrawalPauseRiskAnalyzer
Run: python3 -m unittest spa_core.tests.test_defi_protocol_emergency_withdrawal_pause_risk_analyzer -v
"""

import json
import math
import os
import sys
import unittest
import tempfile

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from spa_core.analytics.defi_protocol_emergency_withdrawal_pause_risk_analyzer import (
    DeFiProtocolEmergencyWithdrawalPauseRiskAnalyzer,
    _f,
    _clamp,
    _mean,
    _multisig_strength,
    _build_default_cfg,
    _grade_from_safety,
    CONTROLLER_SAFETY,
    DEFAULT_CONTROLLER_SAFETY,
    PAUSE_LONG_DAYS,
    PAUSE_SEVERE_DAYS,
    PROB_HIGH_PCT,
    PROB_MODERATE_PCT,
    DEFAULT_TRAPPED_APY_PCT,
    LOG_PATH,
    LOG_CAP,
)


# ── fixtures ──────────────────────────────────────────────────────────────────

def make_pos(
    protocol="Vault",
    position_usd=100_000.0,
    has_pausable_withdrawals=True,
    pause_controller_type="MULTISIG",
    multisig_threshold_m=3,
    multisig_total_n=5,
    unpause_timelock_hours=24.0,
    historical_max_pause_days=2.0,
    annual_pause_probability_pct=3.0,
    emergency_exit_available=False,
    assumed_apy_pct=6.0,
):
    return {
        "protocol": protocol,
        "position_usd": position_usd,
        "has_pausable_withdrawals": has_pausable_withdrawals,
        "pause_controller_type": pause_controller_type,
        "multisig_threshold_m": multisig_threshold_m,
        "multisig_total_n": multisig_total_n,
        "unpause_timelock_hours": unpause_timelock_hours,
        "historical_max_pause_days": historical_max_pause_days,
        "annual_pause_probability_pct": annual_pause_probability_pct,
        "emergency_exit_available": emergency_exit_available,
        "assumed_apy_pct": assumed_apy_pct,
    }


def B():
    return DeFiProtocolEmergencyWithdrawalPauseRiskAnalyzer()


# ── helper-function tests ─────────────────────────────────────────────────────

class TestHelpers(unittest.TestCase):
    def test_f_valid(self):
        self.assertEqual(_f("4.5"), 4.5)

    def test_f_none(self):
        self.assertEqual(_f(None), 0.0)
        self.assertEqual(_f(None, 6.0), 6.0)

    def test_f_bad(self):
        self.assertEqual(_f("xx", 2.0), 2.0)

    def test_clamp(self):
        self.assertEqual(_clamp(5, 0, 1), 1)
        self.assertEqual(_clamp(-1, 0, 1), 0)
        self.assertEqual(_clamp(0.5, 0, 1), 0.5)

    def test_mean_empty(self):
        self.assertEqual(_mean([]), 0.0)

    def test_mean(self):
        self.assertAlmostEqual(_mean([10, 20, 30]), 20.0)

    def test_multisig_strength_zero_when_single(self):
        self.assertEqual(_multisig_strength(1, 1), 0.0)
        self.assertEqual(_multisig_strength(0, 5), 0.0)

    def test_multisig_strength_increases_with_threshold(self):
        low = _multisig_strength(2, 5)
        high = _multisig_strength(4, 5)
        self.assertGreater(high, low)

    def test_multisig_strength_bounded(self):
        s = _multisig_strength(9, 9)
        self.assertLessEqual(s, 1.0)
        self.assertGreaterEqual(s, 0.0)

    def test_multisig_strength_large_setup(self):
        s = _multisig_strength(5, 9)
        self.assertGreater(s, 0.4)

    def test_build_cfg_defaults(self):
        cfg = _build_default_cfg()
        self.assertEqual(cfg["log_path"], LOG_PATH)
        self.assertEqual(cfg["log_cap"], LOG_CAP)

    def test_build_cfg_override(self):
        cfg = _build_default_cfg({"log_cap": 7})
        self.assertEqual(cfg["log_cap"], 7)

    def test_grade_bands(self):
        self.assertEqual(_grade_from_safety(90), "A")
        self.assertEqual(_grade_from_safety(72), "B")
        self.assertEqual(_grade_from_safety(60), "C")
        self.assertEqual(_grade_from_safety(45), "D")
        self.assertEqual(_grade_from_safety(10), "F")

    def test_controller_safety_ordering(self):
        self.assertLess(CONTROLLER_SAFETY["EOA"], CONTROLLER_SAFETY["MULTISIG"])
        self.assertLess(CONTROLLER_SAFETY["MULTISIG"], CONTROLLER_SAFETY["TIMELOCK"])
        self.assertLess(CONTROLLER_SAFETY["TIMELOCK"], CONTROLLER_SAFETY["DAO"])
        self.assertLess(CONTROLLER_SAFETY["DAO"], CONTROLLER_SAFETY["NONE"])


# ── structure ─────────────────────────────────────────────────────────────────

class TestStructure(unittest.TestCase):
    def setUp(self):
        self.r = B().analyze(make_pos())

    def test_keys(self):
        for k in [
            "protocol", "position_usd", "has_pausable_withdrawals",
            "pause_controller_type", "controller_centralization_pct",
            "worst_case_locked_days", "expected_trapped_days_per_year",
            "pausable_exposure_usd", "opportunity_cost_usd",
            "emergency_exit_available", "trap_risk_score", "safety_score",
            "classification", "grade", "flags",
        ]:
            self.assertIn(k, self.r)

    def test_scores_in_range(self):
        self.assertGreaterEqual(self.r["trap_risk_score"], 0.0)
        self.assertLessEqual(self.r["trap_risk_score"], 100.0)
        self.assertGreaterEqual(self.r["safety_score"], 0.0)
        self.assertLessEqual(self.r["safety_score"], 100.0)

    def test_safety_is_inverse_of_risk(self):
        self.assertAlmostEqual(
            self.r["trap_risk_score"] + self.r["safety_score"], 100.0, places=1
        )

    def test_flags_list(self):
        self.assertIsInstance(self.r["flags"], list)
        self.assertIn("PAUSABLE_WITHDRAWALS", self.r["flags"])

    def test_json_serializable(self):
        json.dumps(self.r)

    def test_no_inf_nan(self):
        for v in self.r.values():
            if isinstance(v, float):
                self.assertFalse(math.isinf(v))
                self.assertFalse(math.isnan(v))


# ── no-pause fast path ────────────────────────────────────────────────────────

class TestNoPause(unittest.TestCase):
    def test_no_pause_negligible(self):
        r = B().analyze(make_pos(has_pausable_withdrawals=False))
        self.assertEqual(r["classification"], "NEGLIGIBLE")
        self.assertEqual(r["trap_risk_score"], 0.0)
        self.assertEqual(r["safety_score"], 100.0)
        self.assertEqual(r["grade"], "A")

    def test_no_pause_flag(self):
        r = B().analyze(make_pos(has_pausable_withdrawals=False))
        self.assertIn("NO_PAUSE_RISK", r["flags"])

    def test_no_pause_zero_exposure(self):
        r = B().analyze(make_pos(has_pausable_withdrawals=False))
        self.assertEqual(r["pausable_exposure_usd"], 0.0)
        self.assertEqual(r["opportunity_cost_usd"], 0.0)

    def test_no_pause_controller_none(self):
        r = B().analyze(make_pos(has_pausable_withdrawals=False))
        self.assertEqual(r["pause_controller_type"], "NONE")


# ── insufficient data ─────────────────────────────────────────────────────────

class TestInsufficient(unittest.TestCase):
    def test_zero_position(self):
        r = B().analyze(make_pos(position_usd=0.0))
        self.assertEqual(r["classification"], "INSUFFICIENT_DATA")
        self.assertIn("INSUFFICIENT_DATA", r["flags"])

    def test_negative_position(self):
        r = B().analyze(make_pos(position_usd=-5.0))
        self.assertEqual(r["classification"], "INSUFFICIENT_DATA")

    def test_empty_dict(self):
        r = B().analyze({})
        self.assertEqual(r["classification"], "INSUFFICIENT_DATA")
        self.assertEqual(r["protocol"], "UNKNOWN")

    def test_insufficient_grade_f(self):
        r = B().analyze(make_pos(position_usd=0.0))
        self.assertEqual(r["grade"], "F")


# ── controller centralization ─────────────────────────────────────────────────

class TestController(unittest.TestCase):
    def test_eoa_high_centralization(self):
        r = B().analyze(make_pos(pause_controller_type="EOA"))
        self.assertGreaterEqual(r["controller_centralization_pct"], 80.0)

    def test_eoa_flag(self):
        r = B().analyze(make_pos(pause_controller_type="EOA"))
        self.assertIn("EOA_PAUSE_CONTROLLER", r["flags"])

    def test_dao_decentralized_flag(self):
        r = B().analyze(make_pos(pause_controller_type="DAO"))
        self.assertIn("DECENTRALIZED_PAUSE_CONTROL", r["flags"])

    def test_eoa_riskier_than_multisig(self):
        eoa = B().analyze(make_pos(pause_controller_type="EOA"))
        ms = B().analyze(make_pos(pause_controller_type="MULTISIG"))
        self.assertGreater(eoa["trap_risk_score"], ms["trap_risk_score"])

    def test_unknown_controller_uses_default(self):
        r = B().analyze(make_pos(pause_controller_type="WEIRD"))
        expected = round((1.0 - DEFAULT_CONTROLLER_SAFETY) * 100.0, 2)
        self.assertAlmostEqual(r["controller_centralization_pct"], expected)

    def test_multisig_threshold_affects_centralization(self):
        weak = B().analyze(make_pos(
            pause_controller_type="MULTISIG",
            multisig_threshold_m=2, multisig_total_n=3,
        ))
        strong = B().analyze(make_pos(
            pause_controller_type="MULTISIG",
            multisig_threshold_m=6, multisig_total_n=9,
        ))
        self.assertGreater(
            weak["controller_centralization_pct"],
            strong["controller_centralization_pct"],
        )

    def test_timelock_safer_than_multisig_same_config(self):
        tl = B().analyze(make_pos(
            pause_controller_type="TIMELOCK",
            multisig_threshold_m=3, multisig_total_n=5,
        ))
        ms = B().analyze(make_pos(
            pause_controller_type="MULTISIG",
            multisig_threshold_m=3, multisig_total_n=5,
        ))
        self.assertLess(
            tl["controller_centralization_pct"], ms["controller_centralization_pct"]
        )


# ── lockup duration ───────────────────────────────────────────────────────────

class TestLockup(unittest.TestCase):
    def test_worst_case_includes_timelock(self):
        r = B().analyze(make_pos(
            historical_max_pause_days=5.0, unpause_timelock_hours=48.0,
        ))
        self.assertAlmostEqual(r["worst_case_locked_days"], 7.0)

    def test_expected_trapped_days(self):
        r = B().analyze(make_pos(
            historical_max_pause_days=10.0, unpause_timelock_hours=0.0,
            annual_pause_probability_pct=20.0,
        ))
        # 0.20 * 10 = 2.0
        self.assertAlmostEqual(r["expected_trapped_days_per_year"], 2.0)

    def test_long_pause_flag(self):
        r = B().analyze(make_pos(historical_max_pause_days=10.0,
                                 unpause_timelock_hours=0.0))
        self.assertIn("LONG_HISTORICAL_PAUSE", r["flags"])

    def test_severe_pause_flag(self):
        r = B().analyze(make_pos(historical_max_pause_days=40.0,
                                 unpause_timelock_hours=0.0))
        self.assertIn("SEVERE_LOCKUP_DURATION", r["flags"])

    def test_longer_lockup_higher_risk(self):
        short = B().analyze(make_pos(historical_max_pause_days=1.0))
        long = B().analyze(make_pos(historical_max_pause_days=30.0))
        self.assertGreater(long["trap_risk_score"], short["trap_risk_score"])

    def test_negative_pause_days_clamped(self):
        r = B().analyze(make_pos(historical_max_pause_days=-5.0,
                                 unpause_timelock_hours=0.0))
        self.assertEqual(r["worst_case_locked_days"], 0.0)


# ── probability & exposure ────────────────────────────────────────────────────

class TestProbabilityExposure(unittest.TestCase):
    def test_high_probability_flag(self):
        r = B().analyze(make_pos(annual_pause_probability_pct=15.0))
        self.assertIn("HIGH_PAUSE_PROBABILITY", r["flags"])

    def test_probability_clamped_to_100(self):
        r = B().analyze(make_pos(annual_pause_probability_pct=500.0))
        # expected trapped days should use clamped 100%
        self.assertLessEqual(
            r["expected_trapped_days_per_year"], r["worst_case_locked_days"] + 1e-6
        )

    def test_emergency_exit_zeroes_exposure(self):
        r = B().analyze(make_pos(emergency_exit_available=True))
        self.assertEqual(r["pausable_exposure_usd"], 0.0)
        self.assertEqual(r["opportunity_cost_usd"], 0.0)

    def test_no_emergency_exit_full_exposure(self):
        r = B().analyze(make_pos(position_usd=100_000.0,
                                 emergency_exit_available=False))
        self.assertEqual(r["pausable_exposure_usd"], 100_000.0)

    def test_emergency_exit_flag(self):
        r = B().analyze(make_pos(emergency_exit_available=True))
        self.assertIn("EMERGENCY_EXIT_AVAILABLE", r["flags"])

    def test_no_emergency_exit_flag(self):
        r = B().analyze(make_pos(emergency_exit_available=False))
        self.assertIn("NO_EMERGENCY_EXIT", r["flags"])

    def test_emergency_exit_lowers_risk(self):
        with_exit = B().analyze(make_pos(emergency_exit_available=True))
        without = B().analyze(make_pos(emergency_exit_available=False))
        self.assertLess(with_exit["trap_risk_score"], without["trap_risk_score"])

    def test_opportunity_cost_positive_when_trapped(self):
        r = B().analyze(make_pos(
            position_usd=1_000_000.0, emergency_exit_available=False,
            historical_max_pause_days=30.0, annual_pause_probability_pct=50.0,
            assumed_apy_pct=10.0,
        ))
        self.assertGreater(r["opportunity_cost_usd"], 0.0)

    def test_default_apy_used_when_missing(self):
        pos = make_pos()
        del pos["assumed_apy_pct"]
        r = B().analyze(pos)
        self.assertIn("opportunity_cost_usd", r)


# ── classification ────────────────────────────────────────────────────────────

class TestClassification(unittest.TestCase):
    def test_severe_case(self):
        r = B().analyze(make_pos(
            pause_controller_type="EOA", historical_max_pause_days=21.0,
            annual_pause_probability_pct=15.0, emergency_exit_available=False,
        ))
        self.assertEqual(r["classification"], "SEVERE")
        self.assertIn("SEVERE_TRAP_RISK", r["flags"])

    def test_low_case_decentralized(self):
        r = B().analyze(make_pos(
            pause_controller_type="TIMELOCK",
            multisig_threshold_m=5, multisig_total_n=9,
            historical_max_pause_days=1.0, unpause_timelock_hours=24.0,
            annual_pause_probability_pct=2.0, emergency_exit_available=True,
        ))
        self.assertIn(r["classification"], {"LOW", "NEGLIGIBLE"})

    def test_classification_known_values(self):
        for ctype in ["EOA", "MULTISIG", "TIMELOCK", "DAO"]:
            r = B().analyze(make_pos(pause_controller_type=ctype))
            self.assertIn(r["classification"], {
                "NEGLIGIBLE", "LOW", "MODERATE", "HIGH", "SEVERE",
            })

    def test_higher_risk_worse_grade(self):
        safe = B().analyze(make_pos(
            pause_controller_type="DAO", historical_max_pause_days=0.0,
            unpause_timelock_hours=0.0, annual_pause_probability_pct=0.0,
            emergency_exit_available=True,
        ))
        risky = B().analyze(make_pos(
            pause_controller_type="EOA", historical_max_pause_days=30.0,
            annual_pause_probability_pct=20.0, emergency_exit_available=False,
        ))
        self.assertGreater(safe["safety_score"], risky["safety_score"])


# ── portfolio ─────────────────────────────────────────────────────────────────

class TestPortfolio(unittest.TestCase):
    def setUp(self):
        self.res = B().analyze_portfolio([
            make_pos(protocol="Safe", pause_controller_type="DAO",
                     historical_max_pause_days=0.0, unpause_timelock_hours=0.0,
                     annual_pause_probability_pct=0.0, emergency_exit_available=True),
            make_pos(protocol="Risky", pause_controller_type="EOA",
                     historical_max_pause_days=21.0,
                     annual_pause_probability_pct=15.0,
                     emergency_exit_available=False),
            make_pos(protocol="Immutable", has_pausable_withdrawals=False),
        ])

    def test_structure(self):
        self.assertIn("positions", self.res)
        self.assertIn("aggregate", self.res)
        self.assertEqual(len(self.res["positions"]), 3)

    def test_most_trap_prone_is_highest_risk(self):
        agg = self.res["aggregate"]
        risks = {p["protocol"]: p["trap_risk_score"] for p in self.res["positions"]}
        self.assertEqual(risks[agg["most_trap_prone_position"]], max(risks.values()))

    def test_most_trap_prone_is_risky(self):
        self.assertEqual(self.res["aggregate"]["most_trap_prone_position"], "Risky")

    def test_high_trap_count(self):
        self.assertGreaterEqual(self.res["aggregate"]["high_trap_count"], 1)

    def test_total_pausable_exposure(self):
        # only Risky contributes (no emergency exit)
        self.assertAlmostEqual(
            self.res["aggregate"]["total_pausable_exposure_usd"], 100_000.0
        )

    def test_position_count(self):
        self.assertEqual(self.res["aggregate"]["position_count"], 3)

    def test_avg_risk_in_range(self):
        avg = self.res["aggregate"]["avg_trap_risk_score"]
        self.assertGreaterEqual(avg, 0.0)
        self.assertLessEqual(avg, 100.0)

    def test_empty_portfolio(self):
        res = B().analyze_portfolio([])
        self.assertEqual(res["positions"], [])
        self.assertIsNone(res["aggregate"]["most_trap_prone_position"])

    def test_all_insufficient(self):
        res = B().analyze_portfolio([make_pos(position_usd=0.0)])
        self.assertIsNone(res["aggregate"]["least_trap_prone_position"])
        self.assertEqual(res["aggregate"]["avg_trap_risk_score"], 0.0)


# ── logging ───────────────────────────────────────────────────────────────────

class TestLogging(unittest.TestCase):
    def test_write_creates_file(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "log.json")
            B().analyze(make_pos(), cfg={"log_path": path}, write_log=True)
            self.assertTrue(os.path.exists(path))

    def test_no_write_default(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "log.json")
            B().analyze(make_pos(), cfg={"log_path": path})
            self.assertFalse(os.path.exists(path))

    def test_ring_buffer(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "log.json")
            cfg = {"log_path": path, "log_cap": 2}
            for _ in range(5):
                B().analyze(make_pos(), cfg=cfg, write_log=True)
            with open(path) as fh:
                data = json.load(fh)
            self.assertEqual(len(data), 2)

    def test_corrupt_recovers(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "log.json")
            with open(path, "w") as fh:
                fh.write("garbage")
            B().analyze(make_pos(), cfg={"log_path": path}, write_log=True)
            with open(path) as fh:
                data = json.load(fh)
            self.assertEqual(len(data), 1)

    def test_snapshot_content(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "log.json")
            B().analyze_portfolio([make_pos(), make_pos(protocol="X")],
                                  cfg={"log_path": path}, write_log=True)
            with open(path) as fh:
                data = json.load(fh)
            self.assertEqual(len(data[0]["snapshots"]), 2)


# ── robustness ────────────────────────────────────────────────────────────────

class TestRobustness(unittest.TestCase):
    def test_string_numbers(self):
        r = B().analyze({
            "protocol": "S", "position_usd": "100000",
            "has_pausable_withdrawals": True, "pause_controller_type": "multisig",
            "multisig_threshold_m": "3", "multisig_total_n": "5",
            "historical_max_pause_days": "2", "annual_pause_probability_pct": "3",
        })
        self.assertNotEqual(r["classification"], "INSUFFICIENT_DATA")

    def test_controller_case_insensitive(self):
        lower = B().analyze(make_pos(pause_controller_type="eoa"))
        upper = B().analyze(make_pos(pause_controller_type="EOA"))
        self.assertEqual(lower["trap_risk_score"], upper["trap_risk_score"])

    def test_missing_optional_fields(self):
        r = B().analyze({
            "protocol": "S", "position_usd": 50_000.0,
            "has_pausable_withdrawals": True, "pause_controller_type": "MULTISIG",
        })
        self.assertIn("classification", r)

    def test_large_portfolio(self):
        res = B().analyze_portfolio([make_pos(protocol=f"P{i}") for i in range(200)])
        self.assertEqual(len(res["positions"]), 200)

    def test_portfolio_json_serializable(self):
        res = B().analyze_portfolio([
            make_pos(), make_pos(has_pausable_withdrawals=False),
            make_pos(position_usd=0.0),
        ])
        json.dumps(res)

    def test_multisig_without_n_falls_back(self):
        r = B().analyze(make_pos(
            pause_controller_type="MULTISIG",
            multisig_threshold_m=0, multisig_total_n=0,
        ))
        # n<=0 → use type floor only
        self.assertIn("classification", r)


if __name__ == "__main__":
    unittest.main()
