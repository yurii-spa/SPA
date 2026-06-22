"""
Tests for MP-937: ProtocolVeTokenBribeMarketAnalyzer
≥85 tests covering efficiency labels, value capture scores, competitive pressure,
voter yield scores, flags, aggregates, validation, log write, and edge cases.
Run: python3 -m unittest spa_core.tests.test_protocol_vetoken_bribe_market_analyzer
"""

import json
import os
import tempfile
import unittest

from spa_core.analytics.protocol_vetoken_bribe_market_analyzer import (
    ProtocolVeTokenBribeMarketAnalyzer,
    _validate_gauge,
    _efficiency_label,
    _value_capture_score,
    _competitive_pressure,
    _voter_yield_score,
    _compute_flags,
    _analyze_single_gauge,
    _compute_aggregates,
    _atomic_write,
    _append_log,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

def _base_gauge(**kwargs):
    g = {
        "protocol": "Curve",
        "gauge_name": "3pool",
        "weekly_bribe_usd": 10000.0,
        "weekly_emissions_usd": 20000.0,
        "total_votes_vetoken": 1000000.0,
        "bribe_per_vote_usd": 0.01,
        "emissions_per_vote_usd": 0.02,
        "voter_apr_pct": 20.0,
        "briber_roi_pct": 200.0,      # 200% → HIGHLY_EFFICIENT
        "vote_share_pct": 10.0,
        "lock_duration_avg_days": 200.0,
    }
    g.update(kwargs)
    return g


def _highly_efficient_gauge():
    return _base_gauge(briber_roi_pct=250.0, gauge_name="HighEff")

def _efficient_gauge():
    return _base_gauge(briber_roi_pct=150.0, gauge_name="Efficient")

def _neutral_gauge():
    return _base_gauge(briber_roi_pct=110.0, gauge_name="Neutral")

def _inefficient_gauge():
    return _base_gauge(briber_roi_pct=85.0, gauge_name="Inefficient")

def _wasteful_gauge():
    return _base_gauge(briber_roi_pct=50.0, gauge_name="Wasteful")

def _dominant_gauge():
    return _base_gauge(vote_share_pct=40.0, gauge_name="Dominant")

def _high_voter_apr_gauge():
    return _base_gauge(voter_apr_pct=80.0, gauge_name="HighAPR")

def _overbribed_gauge():
    return _base_gauge(briber_roi_pct=80.0, gauge_name="Overbribed")

def _long_lock_gauge():
    return _base_gauge(lock_duration_avg_days=400.0, gauge_name="LongLock")

def _low_comp_gauge():
    return _base_gauge(weekly_bribe_usd=100.0, gauge_name="LowComp")


# ---------------------------------------------------------------------------
# Unit tests: _efficiency_label
# ---------------------------------------------------------------------------

class TestEfficiencyLabel(unittest.TestCase):

    def test_highly_efficient(self):
        self.assertEqual(_efficiency_label(250.0), "HIGHLY_EFFICIENT")

    def test_exactly_200(self):
        self.assertEqual(_efficiency_label(200.0), "HIGHLY_EFFICIENT")

    def test_efficient(self):
        self.assertEqual(_efficiency_label(150.0), "EFFICIENT")

    def test_exactly_130(self):
        self.assertEqual(_efficiency_label(130.0), "EFFICIENT")

    def test_neutral(self):
        self.assertEqual(_efficiency_label(110.0), "NEUTRAL")

    def test_exactly_100(self):
        self.assertEqual(_efficiency_label(100.0), "NEUTRAL")

    def test_inefficient(self):
        self.assertEqual(_efficiency_label(85.0), "INEFFICIENT")

    def test_exactly_70(self):
        self.assertEqual(_efficiency_label(70.0), "INEFFICIENT")

    def test_wasteful(self):
        self.assertEqual(_efficiency_label(50.0), "WASTEFUL")

    def test_zero_roi(self):
        self.assertEqual(_efficiency_label(0.0), "WASTEFUL")

    def test_negative_roi(self):
        self.assertEqual(_efficiency_label(-10.0), "WASTEFUL")

    def test_very_high_roi(self):
        self.assertEqual(_efficiency_label(1000.0), "HIGHLY_EFFICIENT")

    def test_just_below_efficient(self):
        self.assertEqual(_efficiency_label(129.9), "NEUTRAL")

    def test_just_below_highly_efficient(self):
        self.assertEqual(_efficiency_label(199.9), "EFFICIENT")


# ---------------------------------------------------------------------------
# Unit tests: _value_capture_score
# ---------------------------------------------------------------------------

class TestValueCaptureScore(unittest.TestCase):

    def test_score_in_range(self):
        s = _value_capture_score(200.0, 25.0, 20000.0, 10000.0)
        self.assertGreaterEqual(s, 0.0)
        self.assertLessEqual(s, 100.0)

    def test_high_roi_high_score(self):
        s = _value_capture_score(500.0, 40.0, 50000.0, 5000.0)
        self.assertGreater(s, 60.0)

    def test_low_roi_low_score(self):
        s = _value_capture_score(50.0, 5.0, 5000.0, 50000.0)
        self.assertLess(s, 50.0)

    def test_zero_bribes_and_emissions(self):
        s = _value_capture_score(100.0, 10.0, 0.0, 0.0)
        self.assertGreaterEqual(s, 0.0)
        self.assertLessEqual(s, 100.0)

    def test_high_vote_share_increases_score(self):
        low = _value_capture_score(150.0, 5.0, 10000.0, 5000.0)
        high = _value_capture_score(150.0, 50.0, 10000.0, 5000.0)
        self.assertGreater(high, low)

    def test_vote_share_capped_at_50_for_component(self):
        s50 = _value_capture_score(150.0, 50.0, 10000.0, 5000.0)
        s100 = _value_capture_score(150.0, 100.0, 10000.0, 5000.0)
        # Both capped at 100 for vote component
        self.assertAlmostEqual(s50, s100, places=0)

    def test_returns_float(self):
        s = _value_capture_score(150.0, 20.0, 10000.0, 5000.0)
        self.assertIsInstance(s, float)


# ---------------------------------------------------------------------------
# Unit tests: _competitive_pressure
# ---------------------------------------------------------------------------

class TestCompetitivePressure(unittest.TestCase):

    def test_equal_to_avg_is_50(self):
        p = _competitive_pressure(1000.0, 1000.0)
        self.assertAlmostEqual(p, 50.0, places=2)

    def test_zero_avg_returns_zero(self):
        p = _competitive_pressure(1000.0, 0.0)
        self.assertAlmostEqual(p, 0.0, places=2)

    def test_4x_avg_is_100(self):
        p = _competitive_pressure(4000.0, 1000.0)
        self.assertAlmostEqual(p, 100.0, places=1)

    def test_quarter_avg_is_0(self):
        p = _competitive_pressure(250.0, 1000.0)
        self.assertAlmostEqual(p, 0.0, places=1)

    def test_high_bribe_high_pressure(self):
        p = _competitive_pressure(10000.0, 1000.0)
        self.assertGreater(p, 50.0)

    def test_low_bribe_low_pressure(self):
        p = _competitive_pressure(100.0, 10000.0)
        self.assertLess(p, 50.0)

    def test_score_bounded_0_to_100(self):
        for bribe in [0, 100, 1000, 100000]:
            p = _competitive_pressure(float(bribe), 1000.0)
            self.assertGreaterEqual(p, 0.0)
            self.assertLessEqual(p, 100.0)

    def test_zero_bribe(self):
        p = _competitive_pressure(0.0, 1000.0)
        self.assertGreaterEqual(p, 0.0)


# ---------------------------------------------------------------------------
# Unit tests: _voter_yield_score
# ---------------------------------------------------------------------------

class TestVoterYieldScore(unittest.TestCase):

    def test_zero_apr_is_zero_score(self):
        self.assertAlmostEqual(_voter_yield_score(0.0), 0.0, places=2)

    def test_negative_apr_is_zero_score(self):
        self.assertAlmostEqual(_voter_yield_score(-10.0), 0.0, places=2)

    def test_100_apr_is_100_score(self):
        self.assertAlmostEqual(_voter_yield_score(100.0), 100.0, places=2)

    def test_25_apr_is_50_score(self):
        # sqrt(25/100) * 100 = 50
        self.assertAlmostEqual(_voter_yield_score(25.0), 50.0, places=2)

    def test_400_apr_capped_at_100(self):
        self.assertAlmostEqual(_voter_yield_score(400.0), 100.0, places=2)

    def test_score_increases_with_apr(self):
        s1 = _voter_yield_score(10.0)
        s2 = _voter_yield_score(50.0)
        s3 = _voter_yield_score(100.0)
        self.assertLess(s1, s2)
        self.assertLess(s2, s3)

    def test_returns_float(self):
        self.assertIsInstance(_voter_yield_score(20.0), float)


# ---------------------------------------------------------------------------
# Unit tests: _validate_gauge
# ---------------------------------------------------------------------------

class TestValidateGauge(unittest.TestCase):

    def test_valid_gauge(self):
        _validate_gauge(_base_gauge(), 0)  # Should not raise

    def test_missing_protocol(self):
        g = _base_gauge()
        del g["protocol"]
        with self.assertRaises(ValueError):
            _validate_gauge(g, 0)

    def test_missing_gauge_name(self):
        g = _base_gauge()
        del g["gauge_name"]
        with self.assertRaises(ValueError):
            _validate_gauge(g, 0)

    def test_missing_weekly_bribe_usd(self):
        g = _base_gauge()
        del g["weekly_bribe_usd"]
        with self.assertRaises(ValueError):
            _validate_gauge(g, 0)

    def test_negative_bribe(self):
        g = _base_gauge(weekly_bribe_usd=-100.0)
        with self.assertRaises(ValueError):
            _validate_gauge(g, 0)

    def test_negative_emissions(self):
        g = _base_gauge(weekly_emissions_usd=-100.0)
        with self.assertRaises(ValueError):
            _validate_gauge(g, 0)

    def test_negative_votes(self):
        g = _base_gauge(total_votes_vetoken=-1.0)
        with self.assertRaises(ValueError):
            _validate_gauge(g, 0)

    def test_vote_share_above_100(self):
        g = _base_gauge(vote_share_pct=101.0)
        with self.assertRaises(ValueError):
            _validate_gauge(g, 0)

    def test_vote_share_below_0(self):
        g = _base_gauge(vote_share_pct=-1.0)
        with self.assertRaises(ValueError):
            _validate_gauge(g, 0)

    def test_negative_lock_duration(self):
        g = _base_gauge(lock_duration_avg_days=-10.0)
        with self.assertRaises(ValueError):
            _validate_gauge(g, 0)

    def test_missing_briber_roi(self):
        g = _base_gauge()
        del g["briber_roi_pct"]
        with self.assertRaises(ValueError):
            _validate_gauge(g, 0)


# ---------------------------------------------------------------------------
# Unit tests: _compute_flags
# ---------------------------------------------------------------------------

class TestComputeFlags(unittest.TestCase):

    def test_overbribed_when_roi_below_100(self):
        g = _base_gauge(briber_roi_pct=80.0, weekly_bribe_usd=10000.0)
        flags = _compute_flags(g, 10000.0)
        self.assertIn("OVERBRIBED", flags)

    def test_not_overbribed_when_roi_at_100(self):
        g = _base_gauge(briber_roi_pct=100.0, weekly_bribe_usd=10000.0)
        flags = _compute_flags(g, 10000.0)
        self.assertNotIn("OVERBRIBED", flags)

    def test_high_voter_apr_flag(self):
        g = _base_gauge(voter_apr_pct=80.0, weekly_bribe_usd=10000.0)
        flags = _compute_flags(g, 10000.0)
        self.assertIn("HIGH_VOTER_APR", flags)

    def test_not_high_voter_apr_at_50(self):
        g = _base_gauge(voter_apr_pct=50.0, weekly_bribe_usd=10000.0)
        flags = _compute_flags(g, 10000.0)
        self.assertNotIn("HIGH_VOTER_APR", flags)

    def test_dominant_gauge_flag(self):
        g = _base_gauge(vote_share_pct=40.0, weekly_bribe_usd=10000.0)
        flags = _compute_flags(g, 10000.0)
        self.assertIn("DOMINANT_GAUGE", flags)

    def test_not_dominant_at_30(self):
        g = _base_gauge(vote_share_pct=30.0, weekly_bribe_usd=10000.0)
        flags = _compute_flags(g, 10000.0)
        self.assertNotIn("DOMINANT_GAUGE", flags)

    def test_low_competition_flag(self):
        # very small bribe compared to large avg → low competition
        g = _base_gauge(weekly_bribe_usd=10.0)
        flags = _compute_flags(g, 10000.0)
        self.assertIn("LOW_COMPETITION", flags)

    def test_long_lock_flag(self):
        g = _base_gauge(lock_duration_avg_days=400.0, weekly_bribe_usd=10000.0)
        flags = _compute_flags(g, 10000.0)
        self.assertIn("LONG_LOCK", flags)

    def test_not_long_lock_at_365(self):
        g = _base_gauge(lock_duration_avg_days=365.0, weekly_bribe_usd=10000.0)
        flags = _compute_flags(g, 10000.0)
        self.assertNotIn("LONG_LOCK", flags)

    def test_no_flags_normal_gauge(self):
        g = _base_gauge(
            briber_roi_pct=150.0,
            voter_apr_pct=20.0,
            vote_share_pct=10.0,
            lock_duration_avg_days=200.0,
            weekly_bribe_usd=10000.0,
        )
        flags = _compute_flags(g, 10000.0)
        self.assertEqual(len(flags), 0)

    def test_multiple_flags_simultaneously(self):
        g = _base_gauge(
            briber_roi_pct=50.0,
            voter_apr_pct=80.0,
            vote_share_pct=40.0,
            lock_duration_avg_days=400.0,
            weekly_bribe_usd=10.0,
        )
        flags = _compute_flags(g, 10000.0)
        self.assertIn("OVERBRIBED", flags)
        self.assertIn("HIGH_VOTER_APR", flags)
        self.assertIn("DOMINANT_GAUGE", flags)
        self.assertIn("LOW_COMPETITION", flags)
        self.assertIn("LONG_LOCK", flags)


# ---------------------------------------------------------------------------
# Unit tests: _analyze_single_gauge
# ---------------------------------------------------------------------------

class TestAnalyzeSingleGauge(unittest.TestCase):

    def _avg(self):
        return 10000.0

    def test_returns_required_keys(self):
        result = _analyze_single_gauge(_base_gauge(), 0, self._avg())
        required = {
            "protocol", "gauge_name", "efficiency_label", "efficiency_ratio",
            "value_capture_score", "competitive_pressure", "voter_yield_score",
            "briber_roi_pct", "voter_apr_pct", "vote_share_pct",
            "weekly_bribe_usd", "weekly_emissions_usd", "total_votes_vetoken",
            "bribe_per_vote_usd", "emissions_per_vote_usd", "lock_duration_avg_days",
            "flags",
        }
        for k in required:
            self.assertIn(k, result, f"Missing key: {k}")

    def test_highly_efficient_label(self):
        result = _analyze_single_gauge(_highly_efficient_gauge(), 0, self._avg())
        self.assertEqual(result["efficiency_label"], "HIGHLY_EFFICIENT")

    def test_efficient_label(self):
        result = _analyze_single_gauge(_efficient_gauge(), 0, self._avg())
        self.assertEqual(result["efficiency_label"], "EFFICIENT")

    def test_neutral_label(self):
        result = _analyze_single_gauge(_neutral_gauge(), 0, self._avg())
        self.assertEqual(result["efficiency_label"], "NEUTRAL")

    def test_inefficient_label(self):
        result = _analyze_single_gauge(_inefficient_gauge(), 0, self._avg())
        self.assertEqual(result["efficiency_label"], "INEFFICIENT")

    def test_wasteful_label(self):
        result = _analyze_single_gauge(_wasteful_gauge(), 0, self._avg())
        self.assertEqual(result["efficiency_label"], "WASTEFUL")

    def test_efficiency_ratio_calculation(self):
        g = _base_gauge(briber_roi_pct=200.0)
        result = _analyze_single_gauge(g, 0, self._avg())
        self.assertAlmostEqual(result["efficiency_ratio"], 2.0, places=4)

    def test_efficiency_ratio_below_1_is_overbribed(self):
        g = _base_gauge(briber_roi_pct=80.0)
        result = _analyze_single_gauge(g, 0, self._avg())
        self.assertLess(result["efficiency_ratio"], 1.0)
        self.assertIn("OVERBRIBED", result["flags"])

    def test_vcs_in_range(self):
        result = _analyze_single_gauge(_base_gauge(), 0, self._avg())
        self.assertGreaterEqual(result["value_capture_score"], 0.0)
        self.assertLessEqual(result["value_capture_score"], 100.0)

    def test_competitive_pressure_in_range(self):
        result = _analyze_single_gauge(_base_gauge(), 0, self._avg())
        self.assertGreaterEqual(result["competitive_pressure"], 0.0)
        self.assertLessEqual(result["competitive_pressure"], 100.0)

    def test_voter_yield_score_in_range(self):
        result = _analyze_single_gauge(_base_gauge(), 0, self._avg())
        self.assertGreaterEqual(result["voter_yield_score"], 0.0)
        self.assertLessEqual(result["voter_yield_score"], 100.0)

    def test_protocol_preserved(self):
        result = _analyze_single_gauge(_base_gauge(protocol="Balancer"), 0, self._avg())
        self.assertEqual(result["protocol"], "Balancer")

    def test_flags_is_list(self):
        result = _analyze_single_gauge(_base_gauge(), 0, self._avg())
        self.assertIsInstance(result["flags"], list)

    def test_dominant_gauge_flag_set(self):
        result = _analyze_single_gauge(_dominant_gauge(), 0, self._avg())
        self.assertIn("DOMINANT_GAUGE", result["flags"])

    def test_high_voter_apr_flag_set(self):
        result = _analyze_single_gauge(_high_voter_apr_gauge(), 0, self._avg())
        self.assertIn("HIGH_VOTER_APR", result["flags"])

    def test_long_lock_flag_set(self):
        result = _analyze_single_gauge(_long_lock_gauge(), 0, self._avg())
        self.assertIn("LONG_LOCK", result["flags"])

    def test_validation_raises_on_invalid(self):
        g = _base_gauge()
        del g["protocol"]
        with self.assertRaises(ValueError):
            _analyze_single_gauge(g, 0, self._avg())


# ---------------------------------------------------------------------------
# Unit tests: _compute_aggregates
# ---------------------------------------------------------------------------

class TestComputeAggregates(unittest.TestCase):

    def _make_r(self, name, roi, voter_apr, bribe, emissions, flags):
        return {
            "gauge_name": name,
            "briber_roi_pct": roi,
            "voter_apr_pct": voter_apr,
            "weekly_bribe_usd": bribe,
            "weekly_emissions_usd": emissions,
            "value_capture_score": 50.0,
            "flags": flags,
        }

    def test_empty_list(self):
        agg = _compute_aggregates([])
        self.assertIsNone(agg["most_efficient_gauge"])
        self.assertEqual(agg["total_weekly_bribes_usd"], 0.0)

    def test_most_efficient_gauge(self):
        r1 = self._make_r("A", 150.0, 20.0, 5000.0, 10000.0, [])
        r2 = self._make_r("B", 250.0, 30.0, 10000.0, 20000.0, [])
        agg = _compute_aggregates([r1, r2])
        self.assertEqual(agg["most_efficient_gauge"], "B")

    def test_least_efficient_gauge(self):
        r1 = self._make_r("A", 150.0, 20.0, 5000.0, 10000.0, [])
        r2 = self._make_r("B", 50.0, 10.0, 3000.0, 5000.0, [])
        agg = _compute_aggregates([r1, r2])
        self.assertEqual(agg["least_efficient_gauge"], "B")

    def test_total_weekly_bribes(self):
        r1 = self._make_r("A", 150.0, 20.0, 5000.0, 10000.0, [])
        r2 = self._make_r("B", 200.0, 25.0, 3000.0, 8000.0, [])
        agg = _compute_aggregates([r1, r2])
        self.assertAlmostEqual(agg["total_weekly_bribes_usd"], 8000.0, places=2)

    def test_total_weekly_emissions(self):
        r1 = self._make_r("A", 150.0, 20.0, 5000.0, 10000.0, [])
        r2 = self._make_r("B", 200.0, 25.0, 3000.0, 8000.0, [])
        agg = _compute_aggregates([r1, r2])
        self.assertAlmostEqual(agg["total_weekly_emissions_usd"], 18000.0, places=2)

    def test_average_voter_apr(self):
        r1 = self._make_r("A", 150.0, 20.0, 5000.0, 10000.0, [])
        r2 = self._make_r("B", 200.0, 40.0, 3000.0, 8000.0, [])
        agg = _compute_aggregates([r1, r2])
        self.assertAlmostEqual(agg["average_voter_apr"], 30.0, places=2)

    def test_average_briber_roi(self):
        r1 = self._make_r("A", 100.0, 20.0, 5000.0, 10000.0, [])
        r2 = self._make_r("B", 200.0, 25.0, 3000.0, 8000.0, [])
        agg = _compute_aggregates([r1, r2])
        self.assertAlmostEqual(agg["average_briber_roi_pct"], 150.0, places=2)

    def test_overbribed_count(self):
        r1 = self._make_r("A", 80.0, 20.0, 5000.0, 10000.0, ["OVERBRIBED"])
        r2 = self._make_r("B", 200.0, 25.0, 3000.0, 8000.0, [])
        agg = _compute_aggregates([r1, r2])
        self.assertEqual(agg["overbribed_count"], 1)

    def test_dominant_count(self):
        r1 = self._make_r("A", 150.0, 20.0, 5000.0, 10000.0, ["DOMINANT_GAUGE"])
        r2 = self._make_r("B", 200.0, 25.0, 3000.0, 8000.0, ["DOMINANT_GAUGE"])
        agg = _compute_aggregates([r1, r2])
        self.assertEqual(agg["dominant_gauge_count"], 2)

    def test_single_gauge_is_both_most_and_least_efficient(self):
        r1 = self._make_r("A", 150.0, 20.0, 5000.0, 10000.0, [])
        agg = _compute_aggregates([r1])
        self.assertEqual(agg["most_efficient_gauge"], "A")
        self.assertEqual(agg["least_efficient_gauge"], "A")


# ---------------------------------------------------------------------------
# Unit tests: atomic write and log
# ---------------------------------------------------------------------------

class TestAtomicWriteAndLog(unittest.TestCase):

    def test_atomic_write_creates_file(self):
        with tempfile.TemporaryDirectory() as td:
            path = os.path.join(td, "test.json")
            _atomic_write(path, {"a": 1})
            with open(path) as f:
                data = json.load(f)
            self.assertEqual(data["a"], 1)

    def test_atomic_write_overwrites(self):
        with tempfile.TemporaryDirectory() as td:
            path = os.path.join(td, "test.json")
            _atomic_write(path, {"a": 1})
            _atomic_write(path, {"a": 99})
            with open(path) as f:
                data = json.load(f)
            self.assertEqual(data["a"], 99)

    def test_append_log_creates_list(self):
        with tempfile.TemporaryDirectory() as td:
            path = os.path.join(td, "log.json")
            _append_log({"x": 1}, path)
            with open(path) as f:
                log = json.load(f)
            self.assertIsInstance(log, list)
            self.assertEqual(len(log), 1)

    def test_append_log_accumulates(self):
        with tempfile.TemporaryDirectory() as td:
            path = os.path.join(td, "log.json")
            for i in range(5):
                _append_log({"i": i}, path)
            with open(path) as f:
                log = json.load(f)
            self.assertEqual(len(log), 5)

    def test_append_log_ring_buffer_cap(self):
        with tempfile.TemporaryDirectory() as td:
            path = os.path.join(td, "log.json")
            for i in range(15):
                _append_log({"i": i}, path, cap=10)
            with open(path) as f:
                log = json.load(f)
            self.assertLessEqual(len(log), 10)

    def test_append_log_preserves_latest(self):
        with tempfile.TemporaryDirectory() as td:
            path = os.path.join(td, "log.json")
            for i in range(15):
                _append_log({"i": i}, path, cap=10)
            with open(path) as f:
                log = json.load(f)
            self.assertEqual(log[-1]["result"]["i"], 14)

    def test_log_has_timestamp(self):
        with tempfile.TemporaryDirectory() as td:
            path = os.path.join(td, "log.json")
            _append_log({"x": 1}, path)
            with open(path) as f:
                log = json.load(f)
            self.assertIn("timestamp", log[0])

    def test_log_corrupt_file_reset(self):
        with tempfile.TemporaryDirectory() as td:
            path = os.path.join(td, "log.json")
            with open(path, "w") as f:
                f.write("INVALID JSON{{")
            _append_log({"x": 1}, path)
            with open(path) as f:
                log = json.load(f)
            self.assertEqual(len(log), 1)


# ---------------------------------------------------------------------------
# Integration tests: ProtocolVeTokenBribeMarketAnalyzer.analyze
# ---------------------------------------------------------------------------

class TestAnalyzerIntegration(unittest.TestCase):

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.log_path = os.path.join(self.tmpdir, "bribe_log.json")
        self.analyzer = ProtocolVeTokenBribeMarketAnalyzer(log_path=self.log_path)

    def _cfg(self, write=False):
        return {"write_log": write}

    def test_analyze_returns_all_keys(self):
        result = self.analyzer.analyze([_base_gauge()], self._cfg())
        for k in ["timestamp", "module", "mp", "gauges", "aggregates",
                   "errors", "total_analyzed", "total_errors"]:
            self.assertIn(k, result)

    def test_module_name(self):
        result = self.analyzer.analyze([], self._cfg())
        self.assertEqual(result["module"], "ProtocolVeTokenBribeMarketAnalyzer")

    def test_mp_tag(self):
        result = self.analyzer.analyze([], self._cfg())
        self.assertEqual(result["mp"], "MP-937")

    def test_empty_list(self):
        result = self.analyzer.analyze([], self._cfg())
        self.assertEqual(result["total_analyzed"], 0)
        self.assertEqual(result["total_errors"], 0)

    def test_single_valid_gauge(self):
        result = self.analyzer.analyze([_base_gauge()], self._cfg())
        self.assertEqual(result["total_analyzed"], 1)
        self.assertEqual(result["total_errors"], 0)

    def test_multiple_valid_gauges(self):
        gauges = [_base_gauge(), _highly_efficient_gauge(), _wasteful_gauge()]
        result = self.analyzer.analyze(gauges, self._cfg())
        self.assertEqual(result["total_analyzed"], 3)
        self.assertEqual(result["total_errors"], 0)

    def test_invalid_gauge_goes_to_errors(self):
        g = _base_gauge()
        del g["protocol"]
        result = self.analyzer.analyze([g], self._cfg())
        self.assertEqual(result["total_errors"], 1)
        self.assertEqual(result["total_analyzed"], 0)

    def test_mixed_valid_invalid(self):
        bad = _base_gauge()
        del bad["weekly_bribe_usd"]
        result = self.analyzer.analyze([_base_gauge(), bad], self._cfg())
        self.assertEqual(result["total_analyzed"], 1)
        self.assertEqual(result["total_errors"], 1)

    def test_writes_log_when_enabled(self):
        self.analyzer.analyze([_base_gauge()], {"write_log": True})
        self.assertTrue(os.path.exists(self.log_path))

    def test_no_log_when_disabled(self):
        self.analyzer.analyze([_base_gauge()], self._cfg(write=False))
        self.assertFalse(os.path.exists(self.log_path))

    def test_log_structure(self):
        self.analyzer.analyze([_base_gauge()], {"write_log": True})
        with open(self.log_path) as f:
            log = json.load(f)
        self.assertIsInstance(log, list)
        self.assertIn("timestamp", log[0])
        self.assertIn("result", log[0])

    def test_requires_list_input(self):
        with self.assertRaises(TypeError):
            self.analyzer.analyze("not a list", self._cfg())

    def test_competitive_pressure_computed_relative_to_avg(self):
        g1 = _base_gauge(weekly_bribe_usd=1000.0, gauge_name="Small")
        g2 = _base_gauge(weekly_bribe_usd=100000.0, gauge_name="Big")
        result = self.analyzer.analyze([g1, g2], self._cfg())
        gauges = {g["gauge_name"]: g for g in result["gauges"]}
        # Big should have higher competitive pressure than Small
        self.assertGreater(
            gauges["Big"]["competitive_pressure"],
            gauges["Small"]["competitive_pressure"]
        )

    def test_aggregates_most_efficient_correct(self):
        g1 = _base_gauge(briber_roi_pct=120.0, gauge_name="Medium")
        g2 = _base_gauge(briber_roi_pct=250.0, gauge_name="Best")
        result = self.analyzer.analyze([g1, g2], self._cfg())
        self.assertEqual(result["aggregates"]["most_efficient_gauge"], "Best")

    def test_aggregates_least_efficient_correct(self):
        g1 = _base_gauge(briber_roi_pct=40.0, gauge_name="Worst")
        g2 = _base_gauge(briber_roi_pct=250.0, gauge_name="Best")
        result = self.analyzer.analyze([g1, g2], self._cfg())
        self.assertEqual(result["aggregates"]["least_efficient_gauge"], "Worst")

    def test_overbribed_count_in_aggregates(self):
        g1 = _base_gauge(briber_roi_pct=80.0, gauge_name="Overbribed1")
        g2 = _base_gauge(briber_roi_pct=150.0, gauge_name="Good")
        result = self.analyzer.analyze([g1, g2], self._cfg())
        self.assertEqual(result["aggregates"]["overbribed_count"], 1)

    def test_total_bribes_sum_correct(self):
        g1 = _base_gauge(weekly_bribe_usd=5000.0)
        g2 = _base_gauge(weekly_bribe_usd=7000.0)
        result = self.analyzer.analyze([g1, g2], self._cfg())
        self.assertAlmostEqual(
            result["aggregates"]["total_weekly_bribes_usd"], 12000.0, places=2
        )

    def test_error_detail_has_gauge_name(self):
        bad = _base_gauge(vote_share_pct=200.0)
        bad["gauge_name"] = "BadGauge"
        result = self.analyzer.analyze([bad], self._cfg())
        self.assertEqual(result["errors"][0]["gauge_name"], "BadGauge")

    def test_multiple_log_entries_accumulate(self):
        cfg = {"write_log": True}
        self.analyzer.analyze([_base_gauge()], cfg)
        self.analyzer.analyze([_base_gauge()], cfg)
        with open(self.log_path) as f:
            log = json.load(f)
        self.assertEqual(len(log), 2)

    def test_all_flags_detected(self):
        g = _base_gauge(
            briber_roi_pct=50.0,
            voter_apr_pct=80.0,
            vote_share_pct=40.0,
            lock_duration_avg_days=400.0,
            weekly_bribe_usd=10.0,  # very small → low competition
        )
        result = self.analyzer.analyze([g], self._cfg())
        flags = result["gauges"][0]["flags"]
        self.assertIn("OVERBRIBED", flags)
        self.assertIn("HIGH_VOTER_APR", flags)
        self.assertIn("DOMINANT_GAUGE", flags)
        self.assertIn("LONG_LOCK", flags)

    def test_gauge_data_preserved(self):
        g = _base_gauge(protocol="Balancer", gauge_name="80/20 BAL-ETH")
        result = self.analyzer.analyze([g], self._cfg())
        gauge = result["gauges"][0]
        self.assertEqual(gauge["protocol"], "Balancer")
        self.assertEqual(gauge["gauge_name"], "80/20 BAL-ETH")

    def test_zero_votes_edge_case(self):
        g = _base_gauge(total_votes_vetoken=0.0)
        result = self.analyzer.analyze([g], self._cfg())
        self.assertEqual(result["total_analyzed"], 1)

    def test_zero_bribes_edge_case(self):
        g = _base_gauge(weekly_bribe_usd=0.0, bribe_per_vote_usd=0.0)
        result = self.analyzer.analyze([g], self._cfg())
        self.assertEqual(result["total_analyzed"], 1)

    def test_voter_yield_score_reflects_apr(self):
        g_low = _base_gauge(voter_apr_pct=5.0, gauge_name="LowAPR")
        g_high = _base_gauge(voter_apr_pct=90.0, gauge_name="HighAPR")
        result = self.analyzer.analyze([g_low, g_high], self._cfg())
        scores = {g["gauge_name"]: g["voter_yield_score"] for g in result["gauges"]}
        self.assertGreater(scores["HighAPR"], scores["LowAPR"])

    def test_timestamp_in_result(self):
        result = self.analyzer.analyze([_base_gauge()], self._cfg())
        self.assertIn("timestamp", result)
        self.assertRegex(result["timestamp"], r"\d{4}-\d{2}-\d{2}T")


if __name__ == "__main__":
    unittest.main()
