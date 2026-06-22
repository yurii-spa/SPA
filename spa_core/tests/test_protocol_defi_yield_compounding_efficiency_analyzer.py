"""
Tests for MP-1031 ProtocolDeFiYieldCompoundingEfficiencyAnalyzer.
Run: python3 -m unittest spa_core.tests.test_protocol_defi_yield_compounding_efficiency_analyzer -v
"""

import json
import os
import sys
import tempfile
import unittest

_REPO = os.path.normpath(os.path.join(os.path.dirname(__file__), "..", ".."))
if _REPO not in sys.path:
    sys.path.insert(0, _REPO)

from spa_core.analytics.protocol_defi_yield_compounding_efficiency_analyzer import (
    ProtocolDeFiYieldCompoundingEfficiencyAnalyzer,
    compute_simple_daily_rate,
    compute_compound_apy,
    compute_gas_drag_annual_pct,
    compute_gas_drag_bps,
    compute_effective_apy,
    compute_optimal_compound_frequency,
    compute_net_compounding_benefit,
    compute_label,
    _analyze_one,
    _atomic_write,
    _init_log,
    _append_log,
    _iso_now,
    analyze,
    LOG_MAX_ENTRIES,
    LABEL_OPTIMAL_BENEFIT_PCT,
    LABEL_GOOD_BENEFIT_PCT,
    LABEL_OPTIMAL_GAS_BPS,
    LABEL_GOOD_GAS_BPS,
    LABEL_SUBOPTIMAL_GAS_BPS,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

def _pos(
    name="TestPos",
    base_apy_pct=8.0,
    gas_cost_per_compound_usd=10.0,
    position_size_usd=100_000.0,
    compound_frequency_per_day=1.0,
    auto_compound=False,
    protocol_fee_on_compound_pct=0.0,
):
    return {
        "name": name,
        "base_apy_pct": base_apy_pct,
        "gas_cost_per_compound_usd": gas_cost_per_compound_usd,
        "position_size_usd": position_size_usd,
        "compound_frequency_per_day": compound_frequency_per_day,
        "auto_compound": auto_compound,
        "protocol_fee_on_compound_pct": protocol_fee_on_compound_pct,
    }


def _optimal_pos():
    """Large position, low gas, auto_compound — OPTIMAL_COMPOUNDING expected."""
    return _pos(
        name="OptimalPos",
        base_apy_pct=10.0,
        gas_cost_per_compound_usd=0.0,
        position_size_usd=1_000_000.0,
        compound_frequency_per_day=4.0,
        auto_compound=True,
        protocol_fee_on_compound_pct=0.0,
    )


def _gas_dominated_pos():
    """Tiny position, expensive gas — GAS_DOMINATED expected."""
    return _pos(
        name="GasDomPos",
        base_apy_pct=5.0,
        gas_cost_per_compound_usd=100.0,
        position_size_usd=1_000.0,
        compound_frequency_per_day=2.0,
        auto_compound=False,
        protocol_fee_on_compound_pct=0.0,
    )


def _destroys_yield_pos():
    """Gas cost so large it exceeds compound gain — COMPOUNDING_DESTROYS_YIELD."""
    return _pos(
        name="DestroyPos",
        base_apy_pct=1.0,
        gas_cost_per_compound_usd=5000.0,
        position_size_usd=1_000.0,
        compound_frequency_per_day=365.0,
        auto_compound=False,
        protocol_fee_on_compound_pct=0.0,
    )


# ---------------------------------------------------------------------------
# 1. compute_simple_daily_rate
# ---------------------------------------------------------------------------

class TestComputeSimpleDailyRate(unittest.TestCase):

    def test_zero_apy(self):
        self.assertAlmostEqual(compute_simple_daily_rate(0.0), 0.0)

    def test_ten_pct_apy(self):
        expected = 0.10 / 365.0
        self.assertAlmostEqual(compute_simple_daily_rate(10.0), expected, places=10)

    def test_hundred_pct_apy(self):
        expected = 1.0 / 365.0
        self.assertAlmostEqual(compute_simple_daily_rate(100.0), expected, places=10)

    def test_negative_apy_treated_as_zero(self):
        self.assertEqual(compute_simple_daily_rate(-5.0), 0.0)

    def test_proportional(self):
        r5  = compute_simple_daily_rate(5.0)
        r10 = compute_simple_daily_rate(10.0)
        self.assertAlmostEqual(r10 / r5, 2.0, places=8)


# ---------------------------------------------------------------------------
# 2. compute_compound_apy
# ---------------------------------------------------------------------------

class TestComputeCompoundApy(unittest.TestCase):

    def test_zero_apy_returns_zero(self):
        result = compute_compound_apy(0.0, 1.0, 0.0)
        self.assertAlmostEqual(result, 0.0, places=4)

    def test_higher_frequency_higher_apy(self):
        apy_1 = compute_compound_apy(10.0, 1.0, 0.0)
        apy_4 = compute_compound_apy(10.0, 4.0, 0.0)
        self.assertGreater(apy_4, apy_1)

    def test_protocol_fee_reduces_apy(self):
        apy_no_fee  = compute_compound_apy(10.0, 1.0, 0.0)
        apy_with_fee = compute_compound_apy(10.0, 1.0, 10.0)
        self.assertGreater(apy_no_fee, apy_with_fee)

    def test_returns_float(self):
        result = compute_compound_apy(8.0, 1.0, 0.0)
        self.assertIsInstance(result, float)

    def test_non_negative(self):
        for apy in (0.0, 1.0, 5.0, 20.0):
            self.assertGreaterEqual(compute_compound_apy(apy, 1.0, 0.0), 0.0)

    def test_100pct_fee_collapses_apy(self):
        result = compute_compound_apy(10.0, 1.0, 100.0)
        self.assertAlmostEqual(result, 0.0, places=4)

    def test_compound_beats_simple(self):
        simple = 8.0
        compound = compute_compound_apy(8.0, 365.0, 0.0)
        self.assertGreater(compound, simple)


# ---------------------------------------------------------------------------
# 3. compute_gas_drag_annual_pct
# ---------------------------------------------------------------------------

class TestComputeGasDragAnnualPct(unittest.TestCase):

    def test_auto_compound_zero_drag(self):
        drag = compute_gas_drag_annual_pct(100.0, 10_000.0, 2.0, True)
        self.assertEqual(drag, 0.0)

    def test_no_gas_zero_drag(self):
        drag = compute_gas_drag_annual_pct(0.0, 10_000.0, 1.0, False)
        self.assertEqual(drag, 0.0)

    def test_basic_drag(self):
        # gas=10, pos=100000, freq=1/day → annual gas = 10*365 = 3650
        # drag% = 3650/100000 * 100 = 3.65%
        drag = compute_gas_drag_annual_pct(10.0, 100_000.0, 1.0, False)
        self.assertAlmostEqual(drag, 3.65, places=3)

    def test_higher_frequency_higher_drag(self):
        d1 = compute_gas_drag_annual_pct(10.0, 100_000.0, 1.0, False)
        d4 = compute_gas_drag_annual_pct(10.0, 100_000.0, 4.0, False)
        self.assertAlmostEqual(d4, d1 * 4.0, places=4)

    def test_larger_position_lower_drag(self):
        d_small = compute_gas_drag_annual_pct(10.0, 1_000.0, 1.0, False)
        d_large = compute_gas_drag_annual_pct(10.0, 1_000_000.0, 1.0, False)
        self.assertGreater(d_small, d_large)

    def test_non_negative(self):
        drag = compute_gas_drag_annual_pct(10.0, 100_000.0, 1.0, False)
        self.assertGreaterEqual(drag, 0.0)


# ---------------------------------------------------------------------------
# 4. compute_gas_drag_bps
# ---------------------------------------------------------------------------

class TestComputeGasDragBps(unittest.TestCase):

    def test_bps_is_pct_times_100(self):
        pct = compute_gas_drag_annual_pct(10.0, 100_000.0, 1.0, False)
        bps = compute_gas_drag_bps(10.0, 100_000.0, 1.0, False)
        self.assertAlmostEqual(bps, pct * 100.0, places=4)

    def test_auto_compound_zero(self):
        bps = compute_gas_drag_bps(100.0, 10_000.0, 5.0, True)
        self.assertEqual(bps, 0.0)

    def test_non_negative(self):
        bps = compute_gas_drag_bps(5.0, 50_000.0, 2.0, False)
        self.assertGreaterEqual(bps, 0.0)


# ---------------------------------------------------------------------------
# 5. compute_effective_apy
# ---------------------------------------------------------------------------

class TestComputeEffectiveApy(unittest.TestCase):

    def test_auto_compound_beats_manual_same_freq(self):
        manual = compute_effective_apy(8.0, 20.0, 100_000.0, 1.0, False, 0.0)
        auto   = compute_effective_apy(8.0, 0.0, 100_000.0, 1.0, True, 0.0)
        self.assertGreater(auto, manual)

    def test_zero_base_apy(self):
        eff = compute_effective_apy(0.0, 0.0, 100_000.0, 1.0, False, 0.0)
        self.assertAlmostEqual(eff, 0.0, places=4)

    def test_large_gas_can_go_negative(self):
        # tiny position, high gas, many compounds
        eff = compute_effective_apy(1.0, 5000.0, 1000.0, 10.0, False, 0.0)
        self.assertLess(eff, 0.0)

    def test_no_fee_higher_than_with_fee(self):
        no_fee   = compute_effective_apy(10.0, 0.0, 100_000.0, 1.0, True, 0.0)
        with_fee = compute_effective_apy(10.0, 0.0, 100_000.0, 1.0, True, 5.0)
        self.assertGreater(no_fee, with_fee)

    def test_returns_float(self):
        result = compute_effective_apy(8.0, 10.0, 100_000.0, 1.0, False, 0.0)
        self.assertIsInstance(result, float)


# ---------------------------------------------------------------------------
# 6. compute_optimal_compound_frequency
# ---------------------------------------------------------------------------

class TestComputeOptimalCompoundFrequency(unittest.TestCase):

    def test_auto_compound_returns_high(self):
        freq = compute_optimal_compound_frequency(8.0, 0.0, 100_000.0, True, 0.0)
        self.assertEqual(freq, 1440.0)

    def test_zero_gas_returns_high(self):
        freq = compute_optimal_compound_frequency(8.0, 0.0, 100_000.0, False, 0.0)
        self.assertEqual(freq, 1440.0)

    def test_returns_float(self):
        freq = compute_optimal_compound_frequency(8.0, 10.0, 100_000.0, False, 0.0)
        self.assertIsInstance(freq, float)

    def test_non_negative(self):
        freq = compute_optimal_compound_frequency(8.0, 10.0, 100_000.0, False, 0.0)
        self.assertGreaterEqual(freq, 0.0)

    def test_larger_position_allows_higher_freq(self):
        freq_small = compute_optimal_compound_frequency(8.0, 20.0, 1_000.0, False, 0.0)
        freq_large = compute_optimal_compound_frequency(8.0, 20.0, 10_000_000.0, False, 0.0)
        self.assertGreaterEqual(freq_large, freq_small)

    def test_high_gas_low_apy_returns_zero(self):
        # With tiny apy and very high gas, should return 0 (compounding never wins)
        freq = compute_optimal_compound_frequency(0.01, 10_000.0, 100.0, False, 0.0)
        self.assertEqual(freq, 0.0)


# ---------------------------------------------------------------------------
# 7. compute_net_compounding_benefit
# ---------------------------------------------------------------------------

class TestComputeNetCompoundingBenefit(unittest.TestCase):

    def test_positive_when_compounding_adds_value(self):
        benefit = compute_net_compounding_benefit(9.0, 8.0, 0.0)
        self.assertGreater(benefit, 0.0)

    def test_negative_when_gas_kills_yield(self):
        # effective 1%, base 8%, no fee → benefit = 1-8 = -7
        benefit = compute_net_compounding_benefit(1.0, 8.0, 0.0)
        self.assertLess(benefit, 0.0)

    def test_returns_float(self):
        result = compute_net_compounding_benefit(9.0, 8.0, 0.0)
        self.assertIsInstance(result, float)

    def test_protocol_fee_reduces_simple_baseline(self):
        # With 10% fee, simple yield = 8 * 0.9 = 7.2; effective = 7.5 → benefit > 0
        benefit = compute_net_compounding_benefit(7.5, 8.0, 10.0)
        self.assertGreater(benefit, 0.0)

    def test_zero_effective_negative_benefit(self):
        benefit = compute_net_compounding_benefit(0.0, 8.0, 0.0)
        self.assertAlmostEqual(benefit, -8.0, places=4)

    def test_100pct_fee_simple_baseline_zero(self):
        # simple = 8 * (1-1) = 0; effective = 4 → benefit = 4
        benefit = compute_net_compounding_benefit(4.0, 8.0, 100.0)
        self.assertAlmostEqual(benefit, 4.0, places=4)


# ---------------------------------------------------------------------------
# 8. compute_label
# ---------------------------------------------------------------------------

class TestComputeLabel(unittest.TestCase):

    def test_compounding_destroys_yield_on_negative_benefit(self):
        label = compute_label(-0.1, 10.0)
        self.assertEqual(label, "COMPOUNDING_DESTROYS_YIELD")

    def test_gas_dominated_high_bps(self):
        label = compute_label(0.0, 600.0)
        self.assertEqual(label, "GAS_DOMINATED")

    def test_suboptimal_moderate_bps(self):
        label = compute_label(0.05, 300.0)
        self.assertEqual(label, "SUBOPTIMAL")

    def test_good_compounding(self):
        label = compute_label(0.2, 100.0)
        self.assertEqual(label, "GOOD_COMPOUNDING")

    def test_optimal_compounding(self):
        label = compute_label(1.0, 10.0)
        self.assertEqual(label, "OPTIMAL_COMPOUNDING")

    def test_boundary_negative_benefit(self):
        label = compute_label(-0.0001, 0.0)
        self.assertEqual(label, "COMPOUNDING_DESTROYS_YIELD")

    def test_boundary_gas_dominated(self):
        label = compute_label(0.0, LABEL_SUBOPTIMAL_GAS_BPS)
        self.assertEqual(label, "GAS_DOMINATED")

    def test_boundary_optimal(self):
        label = compute_label(LABEL_OPTIMAL_BENEFIT_PCT, LABEL_OPTIMAL_GAS_BPS - 0.1)
        self.assertEqual(label, "OPTIMAL_COMPOUNDING")

    def test_boundary_good(self):
        label = compute_label(LABEL_GOOD_BENEFIT_PCT, LABEL_GOOD_GAS_BPS - 1.0)
        self.assertEqual(label, "GOOD_COMPOUNDING")


# ---------------------------------------------------------------------------
# 9. _analyze_one
# ---------------------------------------------------------------------------

class TestAnalyzeOne(unittest.TestCase):

    def test_returns_dict(self):
        result = _analyze_one(_optimal_pos())
        self.assertIsInstance(result, dict)

    def test_required_output_keys(self):
        result = _analyze_one(_optimal_pos())
        for key in ("name", "base_apy_pct", "gas_cost_per_compound_usd",
                    "position_size_usd", "compound_frequency_per_day",
                    "auto_compound", "protocol_fee_on_compound_pct",
                    "effective_apy_pct", "optimal_compound_frequency_per_day",
                    "gas_drag_bps", "net_compounding_benefit_pct", "label"):
            self.assertIn(key, result, f"Missing key: {key}")

    def test_optimal_position_label(self):
        result = _analyze_one(_optimal_pos())
        self.assertEqual(result["label"], "OPTIMAL_COMPOUNDING")

    def test_gas_dominated_label(self):
        result = _analyze_one(_gas_dominated_pos())
        self.assertIn(result["label"], ("GAS_DOMINATED", "COMPOUNDING_DESTROYS_YIELD"))

    def test_destroys_yield_label(self):
        result = _analyze_one(_destroys_yield_pos())
        self.assertIn(result["label"],
                      ("COMPOUNDING_DESTROYS_YIELD", "GAS_DOMINATED"))

    def test_name_preserved(self):
        result = _analyze_one(_pos(name="MyPool"))
        self.assertEqual(result["name"], "MyPool")

    def test_default_name_unknown(self):
        result = _analyze_one({})
        self.assertEqual(result["name"], "unknown")

    def test_effective_apy_is_float(self):
        result = _analyze_one(_optimal_pos())
        self.assertIsInstance(result["effective_apy_pct"], float)

    def test_optimal_freq_non_negative(self):
        result = _analyze_one(_optimal_pos())
        self.assertGreaterEqual(result["optimal_compound_frequency_per_day"], 0.0)

    def test_gas_drag_bps_non_negative(self):
        result = _analyze_one(_optimal_pos())
        self.assertGreaterEqual(result["gas_drag_bps"], 0.0)

    def test_auto_compound_zero_drag_bps(self):
        result = _analyze_one(_pos(auto_compound=True, gas_cost_per_compound_usd=1000.0))
        self.assertEqual(result["gas_drag_bps"], 0.0)


# ---------------------------------------------------------------------------
# 10. ProtocolDeFiYieldCompoundingEfficiencyAnalyzer.analyze
# ---------------------------------------------------------------------------

class TestAnalyzerAnalyze(unittest.TestCase):

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.log = os.path.join(self.tmpdir, "test_yield_log.json")
        self.analyzer = ProtocolDeFiYieldCompoundingEfficiencyAnalyzer(log_path=self.log)

    def test_returns_dict(self):
        result = self.analyzer.analyze([_optimal_pos()])
        self.assertIsInstance(result, dict)

    def test_required_output_keys(self):
        result = self.analyzer.analyze([_optimal_pos()])
        for key in ("positions", "best_compounding", "worst_compounding",
                    "avg_effective_apy_pct", "optimal_count",
                    "destroys_yield_count", "analyzed_at"):
            self.assertIn(key, result)

    def test_raises_on_empty_list(self):
        with self.assertRaises(ValueError):
            self.analyzer.analyze([])

    def test_raises_on_non_list(self):
        with self.assertRaises((ValueError, TypeError)):
            self.analyzer.analyze(None)  # type: ignore

    def test_single_position_best_equals_worst(self):
        result = self.analyzer.analyze([_optimal_pos()])
        self.assertEqual(result["best_compounding"], result["worst_compounding"])

    def test_two_positions_different(self):
        result = self.analyzer.analyze([_optimal_pos(), _destroys_yield_pos()])
        # best should be the one with higher effective_apy
        self.assertIn(result["best_compounding"], ("OptimalPos", "DestroyPos"))
        self.assertNotEqual(result["best_compounding"], result["worst_compounding"])

    def test_avg_is_average(self):
        result = self.analyzer.analyze([_optimal_pos(), _gas_dominated_pos()])
        effs = [p["effective_apy_pct"] for p in result["positions"]]
        expected = round(sum(effs) / len(effs), 4)
        self.assertAlmostEqual(result["avg_effective_apy_pct"], expected, places=3)

    def test_optimal_count(self):
        result = self.analyzer.analyze([_optimal_pos(), _optimal_pos(), _destroys_yield_pos()])
        self.assertEqual(result["optimal_count"], 2)

    def test_destroys_yield_count(self):
        result = self.analyzer.analyze([_destroys_yield_pos(), _destroys_yield_pos()])
        self.assertGreaterEqual(result["destroys_yield_count"], 1)

    def test_analyzed_at_is_string(self):
        result = self.analyzer.analyze([_optimal_pos()])
        self.assertIsInstance(result["analyzed_at"], str)

    def test_log_written(self):
        self.analyzer.analyze([_optimal_pos()])
        self.assertTrue(os.path.exists(self.log))

    def test_log_is_list(self):
        self.analyzer.analyze([_optimal_pos()])
        with open(self.log) as f:
            data = json.load(f)
        self.assertIsInstance(data, list)

    def test_config_log_path_override(self):
        alt = os.path.join(self.tmpdir, "alt_log.json")
        self.analyzer.analyze([_optimal_pos()], config={"log_path": alt})
        self.assertTrue(os.path.exists(alt))

    def test_positions_list_correct_length(self):
        positions = [_pos(name=f"P{i}") for i in range(5)]
        result = self.analyzer.analyze(positions)
        self.assertEqual(len(result["positions"]), 5)


# ---------------------------------------------------------------------------
# 11. analyze_one convenience method
# ---------------------------------------------------------------------------

class TestAnalyzeOneMethod(unittest.TestCase):

    def setUp(self):
        self.analyzer = ProtocolDeFiYieldCompoundingEfficiencyAnalyzer(
            log_path=os.path.join(tempfile.mkdtemp(), "log.json")
        )

    def test_returns_dict(self):
        result = self.analyzer.analyze_one(_optimal_pos())
        self.assertIsInstance(result, dict)

    def test_same_as_analyze_one_function(self):
        pos = _optimal_pos()
        direct = _analyze_one(pos)
        method = self.analyzer.analyze_one(pos)
        self.assertEqual(direct["effective_apy_pct"], method["effective_apy_pct"])
        self.assertEqual(direct["label"], method["label"])


# ---------------------------------------------------------------------------
# 12. Module-level analyze() shorthand
# ---------------------------------------------------------------------------

class TestModuleLevelAnalyze(unittest.TestCase):

    def test_returns_dict(self):
        td = tempfile.mkdtemp()
        result = analyze([_optimal_pos()], config={"log_path": os.path.join(td, "log.json")})
        self.assertIsInstance(result, dict)
        self.assertIn("positions", result)


# ---------------------------------------------------------------------------
# 13. Ring-buffer log helpers
# ---------------------------------------------------------------------------

class TestLogHelpers(unittest.TestCase):

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.log = os.path.join(self.tmpdir, "test_log.json")

    def test_atomic_write_creates_file(self):
        _atomic_write(self.log, [{"a": 1}])
        self.assertTrue(os.path.exists(self.log))

    def test_atomic_write_content(self):
        _atomic_write(self.log, [{"hello": "world"}])
        with open(self.log) as f:
            data = json.load(f)
        self.assertEqual(data, [{"hello": "world"}])

    def test_init_log_missing_file(self):
        entries = _init_log("/nonexistent/path/log.json")
        self.assertEqual(entries, [])

    def test_init_log_existing(self):
        _atomic_write(self.log, [{"x": 1}])
        entries = _init_log(self.log)
        self.assertEqual(entries, [{"x": 1}])

    def test_init_log_corrupt(self):
        with open(self.log, "w") as f:
            f.write("not json{{")
        entries = _init_log(self.log)
        self.assertEqual(entries, [])

    def test_append_log_increments(self):
        result = {
            "analyzed_at": "2026-01-01T00:00:00Z",
            "positions": [],
            "avg_effective_apy_pct": 8.0,
            "optimal_count": 0,
            "destroys_yield_count": 0,
            "best_compounding": "X",
            "worst_compounding": "X",
        }
        _append_log(result, self.log)
        _append_log(result, self.log)
        entries = _init_log(self.log)
        self.assertEqual(len(entries), 2)

    def test_ring_buffer_capped(self):
        result = {
            "analyzed_at": "2026-01-01T00:00:00Z",
            "positions": [],
            "avg_effective_apy_pct": 8.0,
            "optimal_count": 0,
            "destroys_yield_count": 0,
            "best_compounding": "X",
            "worst_compounding": "X",
        }
        for _ in range(LOG_MAX_ENTRIES + 20):
            _append_log(result, self.log)
        entries = _init_log(self.log)
        self.assertLessEqual(len(entries), LOG_MAX_ENTRIES)


# ---------------------------------------------------------------------------
# 14. _iso_now
# ---------------------------------------------------------------------------

class TestIsoNow(unittest.TestCase):

    def test_returns_string(self):
        self.assertIsInstance(_iso_now(), str)

    def test_contains_T(self):
        self.assertIn("T", _iso_now())

    def test_contains_Z(self):
        self.assertIn("Z", _iso_now())

    def test_length_is_20(self):
        self.assertEqual(len(_iso_now()), 20)


# ---------------------------------------------------------------------------
# 15. Label coverage — all 5 labels reachable
# ---------------------------------------------------------------------------

class TestAllLabelsReachable(unittest.TestCase):

    def test_optimal_compounding_reachable(self):
        result = _analyze_one(_optimal_pos())
        self.assertEqual(result["label"], "OPTIMAL_COMPOUNDING")

    def test_compounding_destroys_yield_reachable(self):
        result = _analyze_one(_destroys_yield_pos())
        self.assertIn(result["label"], ("COMPOUNDING_DESTROYS_YIELD", "GAS_DOMINATED"))

    def test_gas_dominated_reachable(self):
        result = _analyze_one(_gas_dominated_pos())
        self.assertIn(result["label"], ("GAS_DOMINATED", "COMPOUNDING_DESTROYS_YIELD"))

    def test_suboptimal_reachable(self):
        # Moderate gas, small-medium position, low APY
        pos = _pos(
            base_apy_pct=3.0,
            gas_cost_per_compound_usd=5.0,
            position_size_usd=5_000.0,
            compound_frequency_per_day=1.0,
            auto_compound=False,
            protocol_fee_on_compound_pct=0.0,
        )
        result = _analyze_one(pos)
        self.assertIn(result["label"],
                      ("SUBOPTIMAL", "GOOD_COMPOUNDING", "GAS_DOMINATED",
                       "COMPOUNDING_DESTROYS_YIELD"))

    def test_good_compounding_reachable(self):
        # Low gas ($0.5), large position ($100K), 12% APY → GOOD or OPTIMAL
        pos = _pos(
            base_apy_pct=12.0,
            gas_cost_per_compound_usd=0.5,
            position_size_usd=100_000.0,
            compound_frequency_per_day=1.0,
            auto_compound=False,
            protocol_fee_on_compound_pct=0.0,
        )
        result = _analyze_one(pos)
        self.assertIn(result["label"],
                      ("GOOD_COMPOUNDING", "OPTIMAL_COMPOUNDING", "SUBOPTIMAL"))

    def test_compute_label_all_five_reachable(self):
        self.assertEqual(compute_label(1.0, 10.0), "OPTIMAL_COMPOUNDING")
        self.assertEqual(compute_label(0.2, 100.0), "GOOD_COMPOUNDING")
        self.assertEqual(compute_label(0.05, 300.0), "SUBOPTIMAL")
        self.assertEqual(compute_label(0.0, 600.0), "GAS_DOMINATED")
        self.assertEqual(compute_label(-1.0, 0.0), "COMPOUNDING_DESTROYS_YIELD")


# ---------------------------------------------------------------------------
# 16. Edge cases
# ---------------------------------------------------------------------------

class TestEdgeCases(unittest.TestCase):

    def test_empty_dict_defaults(self):
        result = _analyze_one({})
        self.assertIn("effective_apy_pct", result)
        self.assertIsInstance(result["effective_apy_pct"], float)

    def test_zero_position_size_clamped(self):
        result = _analyze_one(_pos(position_size_usd=0.0))
        self.assertIsInstance(result["effective_apy_pct"], float)

    def test_very_large_position_optimal(self):
        pos = _pos(
            base_apy_pct=10.0,
            gas_cost_per_compound_usd=5.0,
            position_size_usd=1e9,
            compound_frequency_per_day=1.0,
            auto_compound=False,
        )
        result = _analyze_one(pos)
        self.assertGreater(result["effective_apy_pct"], 0.0)

    def test_zero_frequency_no_compounding(self):
        pos = _pos(
            base_apy_pct=8.0,
            gas_cost_per_compound_usd=10.0,
            position_size_usd=100_000.0,
            compound_frequency_per_day=0.0,
            auto_compound=False,
            protocol_fee_on_compound_pct=0.0,
        )
        result = _analyze_one(pos)
        # No compounding → effective_apy = base_apy (no fee, no gas)
        self.assertAlmostEqual(result["effective_apy_pct"], 8.0, places=3)

    def test_auto_compound_ignores_gas(self):
        pos_low_gas  = _pos(auto_compound=True, gas_cost_per_compound_usd=0.01)
        pos_high_gas = _pos(auto_compound=True, gas_cost_per_compound_usd=9999.0)
        r_low  = _analyze_one(pos_low_gas)
        r_high = _analyze_one(pos_high_gas)
        self.assertAlmostEqual(r_low["gas_drag_bps"], 0.0)
        self.assertAlmostEqual(r_high["gas_drag_bps"], 0.0)

    def test_multiple_positions_analyzed(self):
        positions = [_pos(name=f"P{i}", base_apy_pct=float(i + 1)) for i in range(8)]
        td = tempfile.mkdtemp()
        result = ProtocolDeFiYieldCompoundingEfficiencyAnalyzer(
            log_path=os.path.join(td, "log.json")
        ).analyze(positions)
        self.assertEqual(len(result["positions"]), 8)

    def test_high_protocol_fee_reduces_benefit(self):
        low_fee_r  = _analyze_one(_pos(protocol_fee_on_compound_pct=0.0))
        high_fee_r = _analyze_one(_pos(protocol_fee_on_compound_pct=50.0))
        self.assertGreaterEqual(
            low_fee_r["effective_apy_pct"],
            high_fee_r["effective_apy_pct"],
        )

    def test_negative_apy_zero_effective(self):
        result = _analyze_one(_pos(base_apy_pct=-5.0, auto_compound=True))
        self.assertLessEqual(result["effective_apy_pct"], 0.0)


if __name__ == "__main__":
    unittest.main()
