"""
Tests for MP-1015 DeFiProtocolRehypothecationRiskAnalyzer.
Run: python3 -m unittest spa_core.tests.test_defi_protocol_rehypothecation_risk_analyzer -v
"""

import json
import os
import sys
import tempfile
import unittest

_REPO = os.path.normpath(os.path.join(os.path.dirname(__file__), "..", ".."))
if _REPO not in sys.path:
    sys.path.insert(0, _REPO)

from spa_core.analytics.defi_protocol_rehypothecation_risk_analyzer import (
    DeFiProtocolRehypothecationRiskAnalyzer,
    _validate_position,
    _total_exposure,
    _leverage_multiple,
    _total_borrowed,
    _position_ltv_pct,
    _net_leveraged_apy,
    _health_buffer_pct,
    _liquidation_drop_pct,
    _contagion_score,
    _rehypothecation_risk_score,
    _classify,
    _grade,
    _compute_flags,
    _analyze_one,
    _atomic_write,
    _init_log,
    _append_log,
    _iso_now,
    analyze,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

def _make_position(name="Pos", principal_usd=10000.0, loop_ltv_pct=75.0,
                   loops=3, base_apy_pct=6.0, borrow_apy_pct=3.0,
                   liquidation_ltv_pct=85.0):
    return {
        "name": name,
        "principal_usd": principal_usd,
        "loop_ltv_pct": loop_ltv_pct,
        "loops": loops,
        "base_apy_pct": base_apy_pct,
        "borrow_apy_pct": borrow_apy_pct,
        "liquidation_ltv_pct": liquidation_ltv_pct,
    }


def _no_leverage_position():
    return _make_position(name="NoLev", loops=0, loop_ltv_pct=0.0)


def _extreme_position():
    return _make_position(
        name="Extreme", loop_ltv_pct=90.0, loops=12,
        base_apy_pct=4.0, borrow_apy_pct=8.0, liquidation_ltv_pct=92.0,
    )


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------

class TestValidation(unittest.TestCase):
    def test_valid_passes(self):
        _validate_position(_make_position(), 0)

    def test_missing_field_raises(self):
        p = _make_position()
        del p["loops"]
        with self.assertRaises(ValueError):
            _validate_position(p, 0)

    def test_zero_principal_raises(self):
        with self.assertRaises(ValueError):
            _validate_position(_make_position(principal_usd=0), 0)

    def test_loop_ltv_100_raises(self):
        with self.assertRaises(ValueError):
            _validate_position(_make_position(loop_ltv_pct=100.0), 0)

    def test_negative_loops_raises(self):
        with self.assertRaises(ValueError):
            _validate_position(_make_position(loops=-1), 0)

    def test_non_int_loops_raises(self):
        with self.assertRaises(ValueError):
            _validate_position(_make_position(loops=2.5), 0)

    def test_bad_liq_ltv_raises(self):
        with self.assertRaises(ValueError):
            _validate_position(_make_position(liquidation_ltv_pct=0), 0)
        with self.assertRaises(ValueError):
            _validate_position(_make_position(liquidation_ltv_pct=101), 0)

    def test_empty_list_raises(self):
        with self.assertRaises(ValueError):
            DeFiProtocolRehypothecationRiskAnalyzer().analyze([])

    def test_non_list_raises(self):
        with self.assertRaises(ValueError):
            DeFiProtocolRehypothecationRiskAnalyzer().analyze({"x": 1})


# ---------------------------------------------------------------------------
# Exposure / leverage math
# ---------------------------------------------------------------------------

class TestExposureMath(unittest.TestCase):
    def test_no_loops_equals_principal(self):
        self.assertEqual(_total_exposure(10000.0, 75.0, 0), 10000.0)

    def test_zero_ltv_equals_principal(self):
        self.assertEqual(_total_exposure(10000.0, 0.0, 5), 10000.0)

    def test_geometric_sum(self):
        # r=0.5, loops=2 → 1 + 0.5 + 0.25 = 1.75 → 17500
        self.assertAlmostEqual(_total_exposure(10000.0, 50.0, 2), 17500.0, places=2)

    def test_exposure_monotonic_in_loops(self):
        a = _total_exposure(10000.0, 75.0, 2)
        b = _total_exposure(10000.0, 75.0, 5)
        self.assertGreater(b, a)

    def test_exposure_bounded_by_infinite_sum(self):
        # infinite sum at r=0.75 = principal / 0.25 = 4x
        self.assertLess(_total_exposure(10000.0, 75.0, 100), 40000.01)

    def test_leverage_multiple(self):
        self.assertAlmostEqual(_leverage_multiple(10000.0, 17500.0), 1.75, places=4)

    def test_total_borrowed(self):
        self.assertAlmostEqual(_total_borrowed(17500.0, 10000.0), 7500.0, places=2)

    def test_total_borrowed_non_negative(self):
        self.assertEqual(_total_borrowed(9000.0, 10000.0), 0.0)

    def test_position_ltv(self):
        # debt 7500 / collateral 17500 = 42.857%
        self.assertAlmostEqual(_position_ltv_pct(7500.0, 17500.0), 42.8571, places=3)

    def test_position_ltv_zero_exposure(self):
        self.assertEqual(_position_ltv_pct(0.0, 0.0), 0.0)


# ---------------------------------------------------------------------------
# Carry / health / liquidation
# ---------------------------------------------------------------------------

class TestCarryHealth(unittest.TestCase):
    def test_positive_carry(self):
        # base 6, borrow 3, L=2 → 12 - 3 = 9
        self.assertAlmostEqual(_net_leveraged_apy(6.0, 3.0, 2.0), 9.0, places=4)

    def test_negative_carry(self):
        # base 4, borrow 8, L=3 → 12 - 16 = -4
        self.assertAlmostEqual(_net_leveraged_apy(4.0, 8.0, 3.0), -4.0, places=4)

    def test_no_leverage_carry_equals_base(self):
        self.assertAlmostEqual(_net_leveraged_apy(5.0, 3.0, 1.0), 5.0, places=4)

    def test_health_buffer(self):
        self.assertAlmostEqual(_health_buffer_pct(85.0, 43.0), 42.0, places=2)

    def test_health_buffer_negative(self):
        self.assertLess(_health_buffer_pct(80.0, 90.0), 0.0)

    def test_liquidation_drop(self):
        # position 42.857, liq 85 → drop = 1 - 42.857/85 = 49.58%
        d = _liquidation_drop_pct(42.857, 85.0)
        self.assertAlmostEqual(d, 49.58, places=1)

    def test_liquidation_drop_zero_ltv(self):
        self.assertEqual(_liquidation_drop_pct(0.0, 85.0), 100.0)

    def test_liquidation_drop_bounded(self):
        self.assertLessEqual(_liquidation_drop_pct(10.0, 85.0), 100.0)
        self.assertGreaterEqual(_liquidation_drop_pct(84.0, 85.0), 0.0)


# ---------------------------------------------------------------------------
# Scores / classify / grade
# ---------------------------------------------------------------------------

class TestScores(unittest.TestCase):
    def test_contagion_bounded(self):
        self.assertLessEqual(_contagion_score(10.0, 0.0, 20), 100.0)
        self.assertGreaterEqual(_contagion_score(1.0, 50.0, 0), 0.0)

    def test_contagion_higher_leverage(self):
        low = _contagion_score(1.5, 30.0, 2)
        high = _contagion_score(5.0, 30.0, 2)
        self.assertGreater(high, low)

    def test_risk_bounded(self):
        self.assertLessEqual(
            _rehypothecation_risk_score(10.0, -5.0, 0.0, -10.0, 20), 100.0
        )
        self.assertGreaterEqual(
            _rehypothecation_risk_score(1.0, 50.0, 50.0, 10.0, 0), 0.0
        )

    def test_no_leverage_low_risk(self):
        risk = _rehypothecation_risk_score(1.0, 40.0, 60.0, 5.0, 0)
        self.assertLess(risk, 25.0)

    def test_extreme_high_risk(self):
        risk = _rehypothecation_risk_score(8.0, 1.0, 3.0, -4.0, 12)
        self.assertGreater(risk, 75.0)

    def test_classify_thresholds(self):
        self.assertEqual(_classify(85.0), "EXTREME_REHYPOTHECATION")
        self.assertEqual(_classify(65.0), "AGGRESSIVE")
        self.assertEqual(_classify(45.0), "MODERATE")
        self.assertEqual(_classify(25.0), "CONSERVATIVE")
        self.assertEqual(_classify(5.0), "MINIMAL_REHYPOTHECATION")

    def test_grade_scale(self):
        self.assertEqual(_grade(10.0), "A")
        self.assertEqual(_grade(30.0), "B")
        self.assertEqual(_grade(50.0), "C")
        self.assertEqual(_grade(70.0), "D")
        self.assertEqual(_grade(90.0), "F")


# ---------------------------------------------------------------------------
# Flags
# ---------------------------------------------------------------------------

class TestFlags(unittest.TestCase):
    def test_no_leverage_flag(self):
        flags = _compute_flags(0, 1.0, 50.0, 60.0, 5.0, 10.0)
        self.assertIn("NO_LEVERAGE", flags)

    def test_negative_carry_flag(self):
        flags = _compute_flags(5, 3.0, 20.0, 30.0, -2.0, 40.0)
        self.assertIn("NEGATIVE_CARRY", flags)

    def test_thin_buffer_flag(self):
        flags = _compute_flags(4, 3.0, 4.0, 20.0, 5.0, 50.0)
        self.assertIn("THIN_HEALTH_BUFFER", flags)

    def test_negative_buffer_thin(self):
        flags = _compute_flags(4, 3.0, -2.0, 5.0, 5.0, 60.0)
        self.assertIn("THIN_HEALTH_BUFFER", flags)

    def test_high_liquidation_risk_flag(self):
        flags = _compute_flags(4, 3.0, 5.0, 8.0, 5.0, 50.0)
        self.assertIn("HIGH_LIQUIDATION_RISK", flags)

    def test_deep_and_excessive(self):
        flags = _compute_flags(9, 5.0, 5.0, 20.0, 2.0, 70.0)
        self.assertIn("DEEP_REHYPOTHECATION", flags)
        self.assertIn("EXCESSIVE_LOOPING", flags)
        self.assertIn("CONTAGION_RISK", flags)

    def test_sustainable_carry_flag(self):
        flags = _compute_flags(2, 2.0, 30.0, 50.0, 5.0, 20.0)
        self.assertIn("SUSTAINABLE_CARRY", flags)

    def test_no_duplicate_flags(self):
        flags = _compute_flags(4, 3.0, -2.0, 5.0, 5.0, 60.0)
        self.assertEqual(len(flags), len(set(flags)))


# ---------------------------------------------------------------------------
# analyze_one + analyze
# ---------------------------------------------------------------------------

class TestAnalyzeOne(unittest.TestCase):
    def test_keys_present(self):
        r = _analyze_one(_make_position())
        for k in ("name", "leverage_multiple", "position_ltv_pct",
                  "net_leveraged_apy_pct", "health_buffer_pct",
                  "liquidation_drop_pct", "contagion_score",
                  "rehypothecation_risk_score", "grade", "classification", "flags"):
            self.assertIn(k, r)

    def test_no_leverage_minimal(self):
        r = _analyze_one(_no_leverage_position())
        self.assertEqual(r["leverage_multiple"], 1.0)
        self.assertIn("NO_LEVERAGE", r["flags"])
        self.assertEqual(r["classification"], "MINIMAL_REHYPOTHECATION")

    def test_extreme_high(self):
        r = _analyze_one(_extreme_position())
        self.assertGreater(r["rehypothecation_risk_score"], 60.0)
        self.assertIn(r["classification"], ("AGGRESSIVE", "EXTREME_REHYPOTHECATION"))


class TestAnalyze(unittest.TestCase):
    def test_aggregates(self):
        out = analyze([_no_leverage_position(), _extreme_position()])
        self.assertEqual(out["safest_position"], "NoLev")
        self.assertEqual(out["riskiest_position"], "Extreme")
        self.assertIn("avg_rehypothecation_risk", out)
        self.assertIn("avg_leverage_multiple", out)
        self.assertIn("analyzed_at", out)

    def test_avg_bounded(self):
        out = analyze([_make_position(), _make_position(name="P2")])
        self.assertGreaterEqual(out["avg_rehypothecation_risk"], 0.0)
        self.assertLessEqual(out["avg_rehypothecation_risk"], 100.0)

    def test_single_position(self):
        out = analyze([_make_position()])
        self.assertEqual(len(out["positions"]), 1)
        self.assertEqual(out["safest_position"], out["riskiest_position"])


# ---------------------------------------------------------------------------
# Log helpers
# ---------------------------------------------------------------------------

class TestLog(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.log = os.path.join(self.tmp, "sub", "log.json")

    def test_atomic_write_read(self):
        _atomic_write(self.log, [{"a": 1}])
        self.assertEqual(_init_log(self.log), [{"a": 1}])

    def test_init_missing_returns_empty(self):
        self.assertEqual(_init_log(os.path.join(self.tmp, "nope.json")), [])

    def test_init_corrupt_returns_empty(self):
        path = os.path.join(self.tmp, "bad.json")
        with open(path, "w") as f:
            f.write("not json{")
        self.assertEqual(_init_log(path), [])

    def test_append_caps_at_100(self):
        for i in range(125):
            _append_log({"analyzed_at": _iso_now(), "positions": [{}]}, log_path=self.log)
        with open(self.log) as f:
            self.assertEqual(len(json.load(f)), 100)

    def test_append_snapshot_shape(self):
        _append_log(
            {"analyzed_at": "T", "positions": [{}, {}],
             "avg_rehypothecation_risk": 50.0, "avg_leverage_multiple": 2.0,
             "extreme_count": 1, "safest_position": "A", "riskiest_position": "B"},
            log_path=self.log,
        )
        snap = _init_log(self.log)[-1]
        self.assertEqual(snap["position_count"], 2)
        self.assertEqual(snap["riskiest_position"], "B")

    def test_iso_now_format(self):
        self.assertRegex(_iso_now(), r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")


if __name__ == "__main__":
    unittest.main()
