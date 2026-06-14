"""
Tests for MP-874 AirdropFarmingValueEstimator
≥65 unittest tests — pure stdlib, no third-party dependencies.
"""

import json
import os
import sys
import tempfile
import time
import unittest

# ---------------------------------------------------------------------------
# Path setup
# ---------------------------------------------------------------------------
_HERE = os.path.dirname(__file__)
_ROOT = os.path.abspath(os.path.join(_HERE, "..", ".."))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from spa_core.analytics.airdrop_farming_value_estimator import (
    analyze,
    _user_share,
    _expected_airdrop_usd,
    _annualized_airdrop_yield_pct,
    _opportunity_cost_usd,
    _attractiveness_score,
    _value_label,
    _build_recommendations,
    _atomic_log,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

def _tmp_log() -> str:
    fd, path = tempfile.mkstemp(suffix=".json")
    os.close(fd)
    os.unlink(path)
    return path


def _pos(
    protocol: str = "Proto",
    position_usd: float = 50_000.0,
    points_accrued: float = 10_000.0,
    total_protocol_points: float = 1_000_000.0,
    estimated_fdv_usd: float = 1_000_000_000.0,
    airdrop_supply_pct: float = 10.0,
    probability: float = 0.8,
    days_farming: float = 90.0,
    base_apy_pct: float = 5.0,
) -> dict:
    return {
        "protocol": protocol,
        "position_usd": position_usd,
        "points_accrued": points_accrued,
        "total_protocol_points": total_protocol_points,
        "estimated_fdv_usd": estimated_fdv_usd,
        "airdrop_supply_pct": airdrop_supply_pct,
        "probability": probability,
        "days_farming": days_farming,
        "base_apy_pct": base_apy_pct,
    }


# ===========================================================================
# 1. _user_share
# ===========================================================================

class TestUserShare(unittest.TestCase):
    def test_basic(self):
        self.assertAlmostEqual(_user_share(10_000.0, 1_000_000.0), 0.01)

    def test_zero_total_safe(self):
        self.assertEqual(_user_share(10_000.0, 0.0), 0.0)

    def test_negative_total_safe(self):
        self.assertEqual(_user_share(10_000.0, -5.0), 0.0)

    def test_zero_accrued(self):
        self.assertEqual(_user_share(0.0, 1_000_000.0), 0.0)

    def test_full_share(self):
        self.assertAlmostEqual(_user_share(500.0, 500.0), 1.0)

    def test_monotonic(self):
        self.assertLess(
            _user_share(100.0, 1000.0), _user_share(400.0, 1000.0)
        )


# ===========================================================================
# 2. _expected_airdrop_usd
# ===========================================================================

class TestExpectedAirdropUsd(unittest.TestCase):
    def test_basic(self):
        # share=0.01, supply=10% → 0.1, fdv=1e9, prob=1 → 0.01*0.1*1e9 = 1e6
        v = _expected_airdrop_usd(0.01, 10.0, 1_000_000_000.0, 1.0)
        self.assertAlmostEqual(v, 1_000_000.0)

    def test_probability_scales(self):
        v = _expected_airdrop_usd(0.01, 10.0, 1_000_000_000.0, 0.5)
        self.assertAlmostEqual(v, 500_000.0)

    def test_zero_share(self):
        self.assertEqual(_expected_airdrop_usd(0.0, 10.0, 1e9, 1.0), 0.0)

    def test_zero_fdv(self):
        self.assertEqual(_expected_airdrop_usd(0.01, 10.0, 0.0, 1.0), 0.0)

    def test_zero_probability(self):
        self.assertEqual(_expected_airdrop_usd(0.01, 10.0, 1e9, 0.0), 0.0)

    def test_probability_clamped_above_one(self):
        v_clamp = _expected_airdrop_usd(0.01, 10.0, 1e9, 5.0)
        v_one = _expected_airdrop_usd(0.01, 10.0, 1e9, 1.0)
        self.assertAlmostEqual(v_clamp, v_one)

    def test_probability_clamped_negative(self):
        self.assertEqual(_expected_airdrop_usd(0.01, 10.0, 1e9, -2.0), 0.0)

    def test_negative_fdv_clamped(self):
        self.assertEqual(_expected_airdrop_usd(0.01, 10.0, -5.0, 1.0), 0.0)

    def test_negative_supply_clamped(self):
        self.assertEqual(_expected_airdrop_usd(0.01, -10.0, 1e9, 1.0), 0.0)

    def test_monotonic_in_share(self):
        self.assertLess(
            _expected_airdrop_usd(0.01, 10.0, 1e9, 1.0),
            _expected_airdrop_usd(0.05, 10.0, 1e9, 1.0),
        )


# ===========================================================================
# 3. _annualized_airdrop_yield_pct
# ===========================================================================

class TestAnnualizedYield(unittest.TestCase):
    def test_basic(self):
        # expected=5000, position=50000, days=365 → 5000/50000/365*365*100 = 10%
        y = _annualized_airdrop_yield_pct(5_000.0, 50_000.0, 365.0)
        self.assertAlmostEqual(y, 10.0)

    def test_half_year_doubles_annualized(self):
        # days=182.5 → annualization roughly doubles
        y = _annualized_airdrop_yield_pct(5_000.0, 50_000.0, 182.5)
        self.assertAlmostEqual(y, 20.0)

    def test_zero_position_safe(self):
        self.assertEqual(_annualized_airdrop_yield_pct(5_000.0, 0.0, 90.0), 0.0)

    def test_zero_days_safe(self):
        self.assertEqual(_annualized_airdrop_yield_pct(5_000.0, 50_000.0, 0.0), 0.0)

    def test_negative_position_safe(self):
        self.assertEqual(_annualized_airdrop_yield_pct(5_000.0, -1.0, 90.0), 0.0)

    def test_zero_expected(self):
        self.assertEqual(_annualized_airdrop_yield_pct(0.0, 50_000.0, 90.0), 0.0)

    def test_monotonic_in_expected(self):
        self.assertLess(
            _annualized_airdrop_yield_pct(1_000.0, 50_000.0, 90.0),
            _annualized_airdrop_yield_pct(5_000.0, 50_000.0, 90.0),
        )


# ===========================================================================
# 4. _opportunity_cost_usd
# ===========================================================================

class TestOpportunityCost(unittest.TestCase):
    def test_basic_full_year(self):
        # 50000 * 5% * 365/365 = 2500
        c = _opportunity_cost_usd(50_000.0, 5.0, 365.0)
        self.assertAlmostEqual(c, 2_500.0)

    def test_half_year(self):
        c = _opportunity_cost_usd(50_000.0, 5.0, 182.5)
        self.assertAlmostEqual(c, 1_250.0)

    def test_zero_position_safe(self):
        self.assertEqual(_opportunity_cost_usd(0.0, 5.0, 90.0), 0.0)

    def test_zero_days_safe(self):
        self.assertEqual(_opportunity_cost_usd(50_000.0, 5.0, 0.0), 0.0)

    def test_zero_apy(self):
        self.assertEqual(_opportunity_cost_usd(50_000.0, 0.0, 90.0), 0.0)

    def test_negative_position_safe(self):
        self.assertEqual(_opportunity_cost_usd(-1.0, 5.0, 90.0), 0.0)

    def test_monotonic_in_apy(self):
        self.assertLess(
            _opportunity_cost_usd(50_000.0, 3.0, 90.0),
            _opportunity_cost_usd(50_000.0, 8.0, 90.0),
        )


# ===========================================================================
# 5. _attractiveness_score
# ===========================================================================

class TestAttractivenessScore(unittest.TestCase):
    def test_negative_net_ev_zero(self):
        self.assertEqual(_attractiveness_score(10.0, 5.0, -100.0), 0.0)

    def test_zero_net_ev_zero(self):
        self.assertEqual(_attractiveness_score(10.0, 5.0, 0.0), 0.0)

    def test_ratio_one_is_fifty(self):
        # yield == baseline → ratio 1 → 50
        s = _attractiveness_score(5.0, 5.0, 1_000.0)
        self.assertAlmostEqual(s, 50.0)

    def test_ratio_three_is_seventyfive(self):
        s = _attractiveness_score(15.0, 5.0, 1_000.0)
        self.assertAlmostEqual(s, 75.0)

    def test_zero_baseline_positive_yield(self):
        # base_apy=0, yield>0 → ratio=10 → high score
        s = _attractiveness_score(10.0, 0.0, 1_000.0)
        self.assertGreater(s, 90.0)

    def test_zero_baseline_zero_yield(self):
        s = _attractiveness_score(0.0, 0.0, 1_000.0)
        self.assertEqual(s, 0.0)

    def test_bounded(self):
        s = _attractiveness_score(10_000.0, 1.0, 1_000.0)
        self.assertLessEqual(s, 100.0)
        self.assertGreaterEqual(s, 0.0)

    def test_monotonic_in_yield(self):
        low = _attractiveness_score(6.0, 5.0, 1_000.0)
        high = _attractiveness_score(20.0, 5.0, 1_000.0)
        self.assertLess(low, high)


# ===========================================================================
# 6. _value_label
# ===========================================================================

class TestValueLabel(unittest.TestCase):
    def test_avoid_negative_ev(self):
        self.assertEqual(_value_label(90.0, -100.0), "AVOID")

    def test_avoid_zero_ev(self):
        self.assertEqual(_value_label(90.0, 0.0), "AVOID")

    def test_avoid_low_score(self):
        self.assertEqual(_value_label(20.0, 1_000.0), "AVOID")

    def test_avoid_just_below_25(self):
        self.assertEqual(_value_label(24.99, 1_000.0), "AVOID")

    def test_marginal_at_25(self):
        self.assertEqual(_value_label(25.0, 1_000.0), "MARGINAL")

    def test_marginal_just_below_50(self):
        self.assertEqual(_value_label(49.99, 1_000.0), "MARGINAL")

    def test_attractive_at_50(self):
        self.assertEqual(_value_label(50.0, 1_000.0), "ATTRACTIVE")

    def test_attractive_just_below_75(self):
        self.assertEqual(_value_label(74.99, 1_000.0), "ATTRACTIVE")

    def test_highly_attractive_at_75(self):
        self.assertEqual(_value_label(75.0, 1_000.0), "HIGHLY_ATTRACTIVE")

    def test_highly_attractive_at_100(self):
        self.assertEqual(_value_label(100.0, 1_000.0), "HIGHLY_ATTRACTIVE")


# ===========================================================================
# 7. _build_recommendations
# ===========================================================================

class TestBuildRecommendations(unittest.TestCase):
    def test_avoid_message(self):
        recs = _build_recommendations("AVOID", 2.0, 5.0, -100.0, 0.8)
        self.assertTrue(any("baseline" in r.lower() for r in recs))

    def test_marginal_message(self):
        recs = _build_recommendations("MARGINAL", 6.0, 5.0, 100.0, 0.8)
        self.assertTrue(any("Marginal" in r for r in recs))

    def test_attractive_message(self):
        recs = _build_recommendations("ATTRACTIVE", 12.0, 5.0, 500.0, 0.8)
        self.assertTrue(any("Attractive" in r for r in recs))

    def test_highly_attractive_message(self):
        recs = _build_recommendations("HIGHLY_ATTRACTIVE", 30.0, 5.0, 5_000.0, 0.8)
        self.assertTrue(any("Highly attractive" in r for r in recs))

    def test_low_probability_warning(self):
        recs = _build_recommendations("ATTRACTIVE", 12.0, 5.0, 500.0, 0.3)
        self.assertTrue(any("probability" in r.lower() for r in recs))

    def test_high_probability_no_warning(self):
        recs = _build_recommendations("ATTRACTIVE", 12.0, 5.0, 500.0, 0.9)
        self.assertFalse(any("probability" in r.lower() for r in recs))

    def test_always_nonempty(self):
        for label in ["AVOID", "MARGINAL", "ATTRACTIVE", "HIGHLY_ATTRACTIVE"]:
            recs = _build_recommendations(label, 10.0, 5.0, 100.0, 0.8)
            self.assertGreater(len(recs), 0)


# ===========================================================================
# 8. analyze() — structure
# ===========================================================================

class TestAnalyzeStructure(unittest.TestCase):
    def setUp(self):
        self.r = analyze(_pos(), config={"log_path": _tmp_log()})

    def test_top_level_keys(self):
        expected = {
            "protocol",
            "position_usd",
            "user_share",
            "expected_airdrop_usd",
            "annualized_airdrop_yield_pct",
            "opportunity_cost_usd",
            "net_expected_value_usd",
            "attractiveness_score",
            "label",
            "recommendations",
            "timestamp",
        }
        self.assertEqual(set(self.r.keys()), expected)

    def test_score_float(self):
        self.assertIsInstance(self.r["attractiveness_score"], float)

    def test_label_valid(self):
        self.assertIn(
            self.r["label"],
            {"AVOID", "MARGINAL", "ATTRACTIVE", "HIGHLY_ATTRACTIVE"},
        )

    def test_recommendations_nonempty(self):
        self.assertGreater(len(self.r["recommendations"]), 0)

    def test_timestamp_float(self):
        self.assertIsInstance(self.r["timestamp"], float)


# ===========================================================================
# 9. analyze() — net EV consistency
# ===========================================================================

class TestAnalyzeNetEV(unittest.TestCase):
    def test_net_ev_equals_diff(self):
        r = analyze(_pos(), config={"log_path": _tmp_log()})
        self.assertAlmostEqual(
            r["net_expected_value_usd"],
            r["expected_airdrop_usd"] - r["opportunity_cost_usd"],
        )

    def test_attractive_position(self):
        # high fdv & share → big airdrop, small opportunity cost
        r = analyze(
            _pos(
                points_accrued=50_000.0,
                total_protocol_points=1_000_000.0,
                estimated_fdv_usd=2_000_000_000.0,
                airdrop_supply_pct=20.0,
                probability=0.9,
            ),
            config={"log_path": _tmp_log()},
        )
        self.assertGreater(r["net_expected_value_usd"], 0.0)
        self.assertIn(r["label"], {"ATTRACTIVE", "HIGHLY_ATTRACTIVE"})

    def test_avoid_position(self):
        # tiny share → tiny airdrop, normal opportunity cost
        r = analyze(
            _pos(
                points_accrued=1.0,
                total_protocol_points=1_000_000_000.0,
                estimated_fdv_usd=1_000_000.0,
                airdrop_supply_pct=1.0,
                probability=0.2,
            ),
            config={"log_path": _tmp_log()},
        )
        self.assertLess(r["net_expected_value_usd"], 0.0)
        self.assertEqual(r["label"], "AVOID")


# ===========================================================================
# 10. analyze() — division-by-zero safety
# ===========================================================================

class TestAnalyzeZeroSafety(unittest.TestCase):
    def test_zero_total_points(self):
        r = analyze(
            _pos(total_protocol_points=0.0), config={"log_path": _tmp_log()}
        )
        self.assertEqual(r["user_share"], 0.0)
        self.assertEqual(r["expected_airdrop_usd"], 0.0)

    def test_zero_position(self):
        r = analyze(_pos(position_usd=0.0), config={"log_path": _tmp_log()})
        self.assertEqual(r["annualized_airdrop_yield_pct"], 0.0)
        self.assertEqual(r["opportunity_cost_usd"], 0.0)

    def test_zero_days_farming(self):
        r = analyze(_pos(days_farming=0.0), config={"log_path": _tmp_log()})
        self.assertEqual(r["annualized_airdrop_yield_pct"], 0.0)
        self.assertEqual(r["opportunity_cost_usd"], 0.0)

    def test_all_zero_inputs(self):
        r = analyze({}, config={"log_path": _tmp_log()})
        self.assertEqual(r["net_expected_value_usd"], 0.0)
        self.assertEqual(r["label"], "AVOID")

    def test_empty_dict_protocol(self):
        r = analyze({}, config={"log_path": _tmp_log()})
        self.assertEqual(r["protocol"], "UNKNOWN")


# ===========================================================================
# 11. analyze() — config / defaults
# ===========================================================================

class TestAnalyzeConfig(unittest.TestCase):
    def test_none_config(self):
        r = analyze(_pos())
        self.assertIn("attractiveness_score", r)

    def test_timestamp_recent(self):
        before = time.time()
        r = analyze(_pos(), config={"log_path": _tmp_log()})
        after = time.time()
        self.assertGreaterEqual(r["timestamp"], before)
        self.assertLessEqual(r["timestamp"], after)


# ===========================================================================
# 12. Atomic log
# ===========================================================================

class TestAtomicLog(unittest.TestCase):
    def _make_log_path(self, tmp_dir: str) -> str:
        return os.path.join(tmp_dir, "test_airdrop_log.json")

    def test_creates_file(self):
        with tempfile.TemporaryDirectory() as d:
            path = self._make_log_path(d)
            _atomic_log(path, {"x": 1})
            self.assertTrue(os.path.exists(path))

    def test_appends(self):
        with tempfile.TemporaryDirectory() as d:
            path = self._make_log_path(d)
            _atomic_log(path, {"a": 1})
            _atomic_log(path, {"b": 2})
            with open(path) as f:
                data = json.load(f)
            self.assertEqual(len(data), 2)

    def test_ring_buffer_cap(self):
        with tempfile.TemporaryDirectory() as d:
            path = self._make_log_path(d)
            for i in range(110):
                _atomic_log(path, {"i": i})
            with open(path) as f:
                data = json.load(f)
            self.assertEqual(len(data), 100)

    def test_oldest_dropped(self):
        with tempfile.TemporaryDirectory() as d:
            path = self._make_log_path(d)
            for i in range(105):
                _atomic_log(path, {"i": i})
            with open(path) as f:
                data = json.load(f)
            self.assertEqual(data[0]["i"], 5)

    def test_corrupted_file_reset(self):
        with tempfile.TemporaryDirectory() as d:
            path = self._make_log_path(d)
            with open(path, "w") as f:
                f.write("INVALID JSON <<<")
            _atomic_log(path, {"ok": True})
            with open(path) as f:
                data = json.load(f)
            self.assertEqual(len(data), 1)

    def test_analyze_writes_log(self):
        with tempfile.TemporaryDirectory() as d:
            path = self._make_log_path(d)
            analyze(_pos(), config={"log_path": path})
            self.assertTrue(os.path.exists(path))
            with open(path) as f:
                data = json.load(f)
            self.assertEqual(len(data), 1)


# ===========================================================================
# 13. Edge cases
# ===========================================================================

class TestEdgeCases(unittest.TestCase):
    def test_user_share_full(self):
        r = analyze(
            _pos(points_accrued=1_000_000.0, total_protocol_points=1_000_000.0),
            config={"log_path": _tmp_log()},
        )
        self.assertAlmostEqual(r["user_share"], 1.0)

    def test_probability_clamped(self):
        r_clamp = analyze(_pos(probability=5.0), config={"log_path": _tmp_log()})
        r_one = analyze(_pos(probability=1.0), config={"log_path": _tmp_log()})
        self.assertAlmostEqual(
            r_clamp["expected_airdrop_usd"], r_one["expected_airdrop_usd"]
        )

    def test_score_bounded(self):
        r = analyze(
            _pos(
                points_accrued=900_000.0,
                total_protocol_points=1_000_000.0,
                estimated_fdv_usd=5_000_000_000.0,
                base_apy_pct=0.1,
            ),
            config={"log_path": _tmp_log()},
        )
        self.assertLessEqual(r["attractiveness_score"], 100.0)
        self.assertGreaterEqual(r["attractiveness_score"], 0.0)

    def test_zero_base_apy_no_opportunity_cost(self):
        r = analyze(_pos(base_apy_pct=0.0), config={"log_path": _tmp_log()})
        self.assertEqual(r["opportunity_cost_usd"], 0.0)
        # net EV == expected airdrop
        self.assertAlmostEqual(
            r["net_expected_value_usd"], r["expected_airdrop_usd"]
        )

    def test_recommendations_string_type(self):
        r = analyze(_pos(), config={"log_path": _tmp_log()})
        for rec in r["recommendations"]:
            self.assertIsInstance(rec, str)
            self.assertGreater(len(rec), 0)


if __name__ == "__main__":
    unittest.main()
