"""
Tests for MP-1049 ProtocolDeFiLiquidityMiningDilutionAnalyzer
≥90 unittest tests — pure stdlib, no third-party dependencies.
"""

import json
import math
import os
import sys
import tempfile
import unittest

# ---------------------------------------------------------------------------
# Path setup
# ---------------------------------------------------------------------------
_HERE = os.path.dirname(__file__)
_ROOT = os.path.abspath(os.path.join(_HERE, "..", ".."))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from spa_core.analytics.protocol_defi_liquidity_mining_dilution_analyzer import (
    ProtocolDeFiLiquidityMiningDilutionAnalyzer,
    analyze,
    _real_yield_pct,
    _dilution_yield_pct,
    _fdv_to_revenue_ratio,
    _dilution_ratio,
    _dilution_base_score,
    _fdv_penalty,
    _schedule_modifier,
    _emission_sustainability_score,
    _label,
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


def _proto(
    protocol_name: str = "TestProtocol",
    native_token_emission_rate_per_day: float = 100_000.0,
    native_token_price_usd: float = 1.0,
    total_tvl_usd: float = 100_000_000.0,
    protocol_revenue_daily_usd: float = 50_000.0,
    token_fully_diluted_valuation_usd: float = 500_000_000.0,
    emission_schedule_years_remaining: float = 3.0,
) -> dict:
    return {
        "protocol_name": protocol_name,
        "native_token_emission_rate_per_day": native_token_emission_rate_per_day,
        "native_token_price_usd": native_token_price_usd,
        "total_tvl_usd": total_tvl_usd,
        "protocol_revenue_daily_usd": protocol_revenue_daily_usd,
        "token_fully_diluted_valuation_usd": token_fully_diluted_valuation_usd,
        "emission_schedule_years_remaining": emission_schedule_years_remaining,
    }


# ===========================================================================
# 1. _real_yield_pct
# ===========================================================================

class TestRealYieldPct(unittest.TestCase):
    def test_basic(self):
        # revenue 50k/day, tvl 100M → 50k*365/100M*100 = 18.25%
        result = _real_yield_pct(50_000.0, 100_000_000.0)
        self.assertAlmostEqual(result, 18.25)

    def test_zero_tvl_safe(self):
        self.assertEqual(_real_yield_pct(50_000.0, 0.0), 0.0)

    def test_negative_tvl_safe(self):
        self.assertEqual(_real_yield_pct(50_000.0, -1.0), 0.0)

    def test_zero_revenue(self):
        self.assertEqual(_real_yield_pct(0.0, 100_000_000.0), 0.0)

    def test_negative_revenue_clamped(self):
        # negative revenue → 0
        self.assertEqual(_real_yield_pct(-1000.0, 100_000_000.0), 0.0)

    def test_monotonic_in_revenue(self):
        self.assertLess(
            _real_yield_pct(10_000.0, 100_000_000.0),
            _real_yield_pct(50_000.0, 100_000_000.0),
        )

    def test_decreases_with_tvl(self):
        self.assertGreater(
            _real_yield_pct(50_000.0, 50_000_000.0),
            _real_yield_pct(50_000.0, 200_000_000.0),
        )


# ===========================================================================
# 2. _dilution_yield_pct
# ===========================================================================

class TestDilutionYieldPct(unittest.TestCase):
    def test_basic(self):
        # 100k tokens/day * $1 * 365 / 100M * 100 = 36.5%
        result = _dilution_yield_pct(100_000.0, 1.0, 100_000_000.0)
        self.assertAlmostEqual(result, 36.5)

    def test_zero_emission_rate(self):
        self.assertEqual(_dilution_yield_pct(0.0, 1.0, 100_000_000.0), 0.0)

    def test_zero_token_price(self):
        self.assertEqual(_dilution_yield_pct(100_000.0, 0.0, 100_000_000.0), 0.0)

    def test_zero_tvl_safe(self):
        self.assertEqual(_dilution_yield_pct(100_000.0, 1.0, 0.0), 0.0)

    def test_negative_inputs_clamped(self):
        self.assertEqual(_dilution_yield_pct(-1.0, -1.0, 100_000_000.0), 0.0)

    def test_scales_with_price(self):
        low = _dilution_yield_pct(100_000.0, 0.5, 100_000_000.0)
        high = _dilution_yield_pct(100_000.0, 2.0, 100_000_000.0)
        self.assertLess(low, high)

    def test_scales_with_emission_rate(self):
        low = _dilution_yield_pct(10_000.0, 1.0, 100_000_000.0)
        high = _dilution_yield_pct(100_000.0, 1.0, 100_000_000.0)
        self.assertLess(low, high)


# ===========================================================================
# 3. _fdv_to_revenue_ratio
# ===========================================================================

class TestFdvToRevenueRatio(unittest.TestCase):
    def test_basic(self):
        # fdv=500M, revenue=50k/day → annual=18.25M → ratio≈27.4
        result = _fdv_to_revenue_ratio(500_000_000.0, 50_000.0)
        expected = 500_000_000.0 / (50_000.0 * 365)
        self.assertAlmostEqual(result, expected, places=2)

    def test_zero_revenue_with_fdv(self):
        result = _fdv_to_revenue_ratio(1_000_000.0, 0.0)
        self.assertEqual(result, float("inf"))

    def test_zero_revenue_zero_fdv(self):
        result = _fdv_to_revenue_ratio(0.0, 0.0)
        self.assertEqual(result, 0.0)

    def test_negative_revenue_treated_as_zero(self):
        result = _fdv_to_revenue_ratio(1_000_000.0, -100.0)
        self.assertEqual(result, float("inf"))

    def test_increases_with_fdv(self):
        r1 = _fdv_to_revenue_ratio(100_000_000.0, 50_000.0)
        r2 = _fdv_to_revenue_ratio(500_000_000.0, 50_000.0)
        self.assertLess(r1, r2)

    def test_decreases_with_revenue(self):
        r1 = _fdv_to_revenue_ratio(500_000_000.0, 100_000.0)
        r2 = _fdv_to_revenue_ratio(500_000_000.0, 10_000.0)
        self.assertLess(r1, r2)


# ===========================================================================
# 4. _dilution_ratio
# ===========================================================================

class TestDilutionRatio(unittest.TestCase):
    def test_equal_yields(self):
        self.assertAlmostEqual(_dilution_ratio(10.0, 10.0), 1.0)

    def test_no_real_yield_high_ratio(self):
        # real yield ≈ 0 → huge ratio
        ratio = _dilution_ratio(10.0, 0.0)
        self.assertGreater(ratio, 1_000_000.0)

    def test_zero_dilution(self):
        self.assertAlmostEqual(_dilution_ratio(0.0, 10.0), 0.0)

    def test_dilution_twice_real_yield(self):
        self.assertAlmostEqual(_dilution_ratio(20.0, 10.0), 2.0)

    def test_always_non_negative(self):
        self.assertGreaterEqual(_dilution_ratio(0.0, 0.0), 0.0)


# ===========================================================================
# 5. _dilution_base_score
# ===========================================================================

class TestDilutionBaseScore(unittest.TestCase):
    def test_zero_dilution_gives_100(self):
        self.assertAlmostEqual(_dilution_base_score(0.0), 100.0)

    def test_half_ratio_gives_90(self):
        self.assertAlmostEqual(_dilution_base_score(0.5), 90.0)

    def test_ratio_1_gives_75(self):
        self.assertAlmostEqual(_dilution_base_score(1.0), 75.0)

    def test_ratio_3_gives_50(self):
        self.assertAlmostEqual(_dilution_base_score(3.0), 50.0)

    def test_ratio_10_gives_25(self):
        self.assertAlmostEqual(_dilution_base_score(10.0), 25.0)

    def test_ratio_50_gives_5(self):
        self.assertAlmostEqual(_dilution_base_score(50.0), 5.0)

    def test_very_high_ratio_approaches_zero(self):
        self.assertAlmostEqual(_dilution_base_score(100.0), 0.0, delta=2.0)

    def test_monotonically_decreasing(self):
        scores = [_dilution_base_score(r) for r in (0, 0.5, 1.0, 3.0, 10.0, 50.0, 100.0)]
        for i in range(len(scores) - 1):
            self.assertGreaterEqual(scores[i], scores[i + 1])

    def test_score_in_0_100(self):
        for ratio in (0, 0.1, 1, 5, 20, 100, 500):
            s = _dilution_base_score(float(ratio))
            self.assertGreaterEqual(s, 0.0)
            self.assertLessEqual(s, 100.0)


# ===========================================================================
# 6. _fdv_penalty
# ===========================================================================

class TestFdvPenalty(unittest.TestCase):
    def test_zero_fdv_no_penalty(self):
        self.assertAlmostEqual(_fdv_penalty(0.0), 0.0)

    def test_low_fdv_no_penalty(self):
        self.assertAlmostEqual(_fdv_penalty(10.0), 0.0)

    def test_moderate_fdv_small_penalty(self):
        p = _fdv_penalty(30.0)
        self.assertGreater(p, 0.0)
        self.assertLess(p, 10.0)

    def test_high_fdv_large_penalty(self):
        p = _fdv_penalty(500.0)
        self.assertGreater(p, 20.0)

    def test_inf_fdv_max_penalty(self):
        p = _fdv_penalty(float("inf"))
        self.assertAlmostEqual(p, 30.0)

    def test_penalty_increases_with_fdv(self):
        self.assertLess(_fdv_penalty(20.0), _fdv_penalty(100.0))
        self.assertLess(_fdv_penalty(100.0), _fdv_penalty(500.0))

    def test_penalty_non_negative(self):
        for fdv in (0.0, 5.0, 20.0, 50.0, 100.0, 500.0, 1000.0):
            self.assertGreaterEqual(_fdv_penalty(fdv), 0.0)

    def test_penalty_max_30(self):
        for fdv in (1001.0, 5000.0, float("inf")):
            self.assertLessEqual(_fdv_penalty(fdv), 30.0)


# ===========================================================================
# 7. _schedule_modifier
# ===========================================================================

class TestScheduleModifier(unittest.TestCase):
    def test_sustainable_emissions_no_modifier(self):
        # dilution_ratio ≤ 1.0 → no adjustment
        self.assertAlmostEqual(_schedule_modifier(0.5, 5.0), 0.0)

    def test_zero_years_no_modifier(self):
        self.assertAlmostEqual(_schedule_modifier(5.0, 0.0), 0.0)

    def test_short_schedule_positive_bonus(self):
        mod = _schedule_modifier(5.0, 0.5)
        self.assertGreater(mod, 0.0)

    def test_very_long_schedule_negative(self):
        mod = _schedule_modifier(5.0, 15.0)
        self.assertLess(mod, 0.0)

    def test_medium_schedule_slightly_negative(self):
        mod = _schedule_modifier(5.0, 7.0)
        self.assertLessEqual(mod, 0.0)


# ===========================================================================
# 8. _emission_sustainability_score
# ===========================================================================

class TestEmissionSustainabilityScore(unittest.TestCase):
    def test_zero_dilution_gives_near_100(self):
        score = _emission_sustainability_score(0.0, 10.0, 3.0)
        self.assertGreater(score, 85.0)

    def test_high_dilution_gives_low_score(self):
        score = _emission_sustainability_score(20.0, 200.0, 5.0)
        self.assertLess(score, 25.0)

    def test_death_spiral_territory_near_zero(self):
        score = _emission_sustainability_score(100.0, 1000.0, 10.0)
        self.assertLess(score, 10.0)

    def test_score_in_0_100(self):
        for ratio in (0.0, 0.5, 1.0, 3.0, 10.0, 50.0, 200.0):
            for fdv in (5.0, 50.0, 500.0):
                s = _emission_sustainability_score(ratio, fdv, 3.0)
                self.assertGreaterEqual(s, 0.0)
                self.assertLessEqual(s, 100.0)

    def test_lower_dilution_gives_higher_score(self):
        low = _emission_sustainability_score(0.5, 20.0, 3.0)
        high = _emission_sustainability_score(5.0, 20.0, 3.0)
        self.assertGreater(low, high)


# ===========================================================================
# 9. _label
# ===========================================================================

class TestLabelLiquidityMining(unittest.TestCase):
    def test_sustainable(self):
        self.assertEqual(_label(80.0, 0.3), "SUSTAINABLE_EMISSIONS")

    def test_manageable(self):
        self.assertEqual(_label(60.0, 2.0), "MANAGEABLE")

    def test_high_dilution(self):
        self.assertEqual(_label(35.0, 4.0), "HIGH_DILUTION")

    def test_hyperinflationary(self):
        self.assertEqual(_label(15.0, 12.0), "HYPERINFLATIONARY")

    def test_death_spiral_low_score(self):
        self.assertEqual(_label(5.0, 20.0), "DEATH_SPIRAL_EMISSIONS")

    def test_death_spiral_high_ratio(self):
        # ratio > 50 overrides score
        self.assertEqual(_label(50.0, 55.0), "DEATH_SPIRAL_EMISSIONS")

    def test_all_valid_labels(self):
        valid = {
            "SUSTAINABLE_EMISSIONS", "MANAGEABLE", "HIGH_DILUTION",
            "HYPERINFLATIONARY", "DEATH_SPIRAL_EMISSIONS"
        }
        for score in (5, 15, 35, 60, 80):
            self.assertIn(_label(float(score), 1.0), valid)


# ===========================================================================
# 10. _build_recommendations
# ===========================================================================

class TestBuildRecommendationsLiquidityMining(unittest.TestCase):
    def test_death_spiral_has_warning(self):
        recs = _build_recommendations(
            "DEATH_SPIRAL_EMISSIONS", 1.0, 200.0, 100.0, 500.0, 5.0, "BadProtocol"
        )
        self.assertTrue(len(recs) >= 1)
        self.assertTrue(any("death" in r.lower() or "avoid" in r.lower() for r in recs))

    def test_sustainable_has_positive(self):
        recs = _build_recommendations(
            "SUSTAINABLE_EMISSIONS", 10.0, 2.0, 0.3, 15.0, 3.0, "GoodProtocol"
        )
        self.assertTrue(len(recs) >= 1)
        self.assertTrue(any("sustainable" in r.lower() for r in recs))

    def test_high_fdv_adds_warning(self):
        recs = _build_recommendations(
            "MANAGEABLE", 5.0, 10.0, 2.0, 200.0, 4.0, "Proto"
        )
        self.assertTrue(any("fdv" in r.lower() or "revenue" in r.lower() for r in recs))

    def test_short_schedule_mention(self):
        recs = _build_recommendations(
            "HIGH_DILUTION", 2.0, 8.0, 4.0, 50.0, 0.5, "Proto"
        )
        self.assertTrue(any("1 year" in r or "year" in r for r in recs))

    def test_long_schedule_high_dilution_warning(self):
        recs = _build_recommendations(
            "HIGH_DILUTION", 2.0, 15.0, 8.0, 100.0, 10.0, "Proto"
        )
        self.assertTrue(any("year" in r.lower() for r in recs))

    def test_returns_list(self):
        recs = _build_recommendations(
            "MANAGEABLE", 5.0, 10.0, 2.0, 50.0, 3.0, "Proto"
        )
        self.assertIsInstance(recs, list)

    def test_protocol_name_in_recommendation(self):
        recs = _build_recommendations(
            "MANAGEABLE", 5.0, 10.0, 2.0, 50.0, 3.0, "UniswapV4"
        )
        self.assertTrue(any("UniswapV4" in r for r in recs))


# ===========================================================================
# 11. _atomic_log
# ===========================================================================

class TestAtomicLogMining(unittest.TestCase):
    def test_creates_file(self):
        log = _tmp_log()
        _atomic_log(log, {"k": "v"})
        with open(log) as f:
            data = json.load(f)
        self.assertEqual(len(data), 1)
        os.unlink(log)

    def test_appends_entries(self):
        log = _tmp_log()
        _atomic_log(log, {"n": 1})
        _atomic_log(log, {"n": 2})
        with open(log) as f:
            data = json.load(f)
        self.assertEqual(len(data), 2)
        os.unlink(log)

    def test_ring_buffer_cap(self):
        log = _tmp_log()
        for i in range(110):
            _atomic_log(log, {"i": i})
        with open(log) as f:
            data = json.load(f)
        self.assertLessEqual(len(data), 100)
        self.assertEqual(data[-1]["i"], 109)
        os.unlink(log)

    def test_recovers_from_corrupt_file(self):
        log = _tmp_log()
        with open(log, "w") as f:
            f.write("bad json{")
        _atomic_log(log, {"ok": True})
        with open(log) as f:
            data = json.load(f)
        self.assertEqual(data[0]["ok"], True)
        os.unlink(log)


# ===========================================================================
# 12. ProtocolDeFiLiquidityMiningDilutionAnalyzer — class API
# ===========================================================================

class TestAnalyzerClassMining(unittest.TestCase):
    def setUp(self):
        self._log = _tmp_log()
        self._cfg = {"log_path": self._log}

    def tearDown(self):
        if os.path.exists(self._log):
            os.unlink(self._log)

    def _run(self, **kw) -> dict:
        return ProtocolDeFiLiquidityMiningDilutionAnalyzer(self._cfg).analyze(_proto(**kw))

    def test_returns_dict(self):
        r = self._run()
        self.assertIsInstance(r, dict)

    def test_all_required_keys(self):
        r = self._run()
        for key in (
            "protocol_name", "real_yield_pct", "dilution_yield_pct",
            "total_yield_pct", "dilution_ratio", "fdv_to_revenue_ratio",
            "emission_sustainability_score", "label", "recommendations", "timestamp",
        ):
            self.assertIn(key, r, f"Missing key: {key}")

    def test_score_in_0_100(self):
        r = self._run()
        self.assertGreaterEqual(r["emission_sustainability_score"], 0.0)
        self.assertLessEqual(r["emission_sustainability_score"], 100.0)

    def test_label_is_valid(self):
        r = self._run()
        self.assertIn(r["label"], {
            "SUSTAINABLE_EMISSIONS", "MANAGEABLE", "HIGH_DILUTION",
            "HYPERINFLATIONARY", "DEATH_SPIRAL_EMISSIONS"
        })

    def test_logs_entry(self):
        self._run()
        with open(self._log) as f:
            data = json.load(f)
        self.assertEqual(len(data), 1)

    def test_total_yield_is_sum(self):
        r = self._run()
        self.assertAlmostEqual(
            r["total_yield_pct"],
            r["real_yield_pct"] + r["dilution_yield_pct"],
            places=3,
        )

    def test_zero_emissions_sustainable(self):
        r = self._run(native_token_emission_rate_per_day=0.0)
        self.assertIn(r["label"], {"SUSTAINABLE_EMISSIONS", "MANAGEABLE"})

    def test_zero_revenue_high_dilution(self):
        r = self._run(protocol_revenue_daily_usd=0.0, native_token_emission_rate_per_day=1_000_000.0)
        self.assertIn(r["label"], {"DEATH_SPIRAL_EMISSIONS", "HYPERINFLATIONARY"})

    def test_zero_tvl_safe(self):
        r = self._run(total_tvl_usd=0.0)
        self.assertIn("label", r)
        self.assertEqual(r["real_yield_pct"], 0.0)
        self.assertEqual(r["dilution_yield_pct"], 0.0)

    def test_protocol_name_preserved(self):
        r = self._run(protocol_name="Compound")
        self.assertEqual(r["protocol_name"], "Compound")

    def test_recommendations_non_empty(self):
        r = self._run()
        self.assertIsInstance(r["recommendations"], list)
        self.assertGreater(len(r["recommendations"]), 0)

    def test_timestamp_positive(self):
        r = self._run()
        self.assertGreater(r["timestamp"], 0.0)

    def test_missing_keys_use_defaults(self):
        r = ProtocolDeFiLiquidityMiningDilutionAnalyzer(self._cfg).analyze({})
        self.assertIn("label", r)

    def test_dilution_ratio_correct(self):
        r = self._run(
            native_token_emission_rate_per_day=100_000.0,
            native_token_price_usd=1.0,
            total_tvl_usd=100_000_000.0,
            protocol_revenue_daily_usd=50_000.0,
        )
        # dilution = 100k * 1 * 365 / 100M * 100 = 36.5%
        # real = 50k * 365 / 100M * 100 = 18.25%
        # ratio ≈ 36.5 / 18.25 ≈ 2.0
        self.assertAlmostEqual(r["dilution_ratio"], 2.0, places=2)

    def test_high_emission_high_dilution_or_worse(self):
        r = self._run(
            native_token_emission_rate_per_day=50_000_000.0,
            native_token_price_usd=10.0,
        )
        self.assertIn(r["label"], {"HIGH_DILUTION", "HYPERINFLATIONARY", "DEATH_SPIRAL_EMISSIONS"})

    def test_real_yield_pct_computed(self):
        r = self._run(
            protocol_revenue_daily_usd=100_000.0,
            total_tvl_usd=100_000_000.0,
        )
        expected = 100_000.0 * 365 / 100_000_000.0 * 100
        self.assertAlmostEqual(r["real_yield_pct"], expected, places=3)

    def test_fdv_to_revenue_ratio_computed(self):
        r = self._run(
            token_fully_diluted_valuation_usd=1_000_000_000.0,
            protocol_revenue_daily_usd=100_000.0,
        )
        expected = 1_000_000_000.0 / (100_000.0 * 365)
        self.assertAlmostEqual(r["fdv_to_revenue_ratio"], round(expected, 2), places=1)

    def test_analyzer_with_none_config(self):
        a = ProtocolDeFiLiquidityMiningDilutionAnalyzer(None)
        r = a.analyze(_proto())
        self.assertIn("label", r)


# ===========================================================================
# 13. Module-level analyze() wrapper
# ===========================================================================

class TestModuleLevelAnalyzeMining(unittest.TestCase):
    def setUp(self):
        self._log = _tmp_log()
        self._cfg = {"log_path": self._log}

    def tearDown(self):
        if os.path.exists(self._log):
            os.unlink(self._log)

    def test_returns_dict(self):
        r = analyze(_proto(), self._cfg)
        self.assertIsInstance(r, dict)

    def test_has_all_keys(self):
        r = analyze(_proto(), self._cfg)
        self.assertIn("emission_sustainability_score", r)
        self.assertIn("label", r)

    def test_score_in_range(self):
        r = analyze(_proto(), self._cfg)
        self.assertGreaterEqual(r["emission_sustainability_score"], 0.0)
        self.assertLessEqual(r["emission_sustainability_score"], 100.0)

    def test_multiple_calls_logged(self):
        for _ in range(3):
            analyze(_proto(), self._cfg)
        with open(self._log) as f:
            data = json.load(f)
        self.assertEqual(len(data), 3)


# ===========================================================================
# 14. Label consistency across the protocol space
# ===========================================================================

class TestLabelConsistencyMining(unittest.TestCase):
    def setUp(self):
        self._log = _tmp_log()
        self._cfg = {"log_path": self._log}

    def tearDown(self):
        if os.path.exists(self._log):
            os.unlink(self._log)

    def test_zero_emissions_never_death_spiral(self):
        r = analyze(_proto(native_token_emission_rate_per_day=0.0), self._cfg)
        self.assertNotEqual(r["label"], "DEATH_SPIRAL_EMISSIONS")

    def test_extreme_emissions_is_death_spiral(self):
        r = analyze(
            _proto(
                native_token_emission_rate_per_day=1_000_000_000.0,
                native_token_price_usd=10.0,
                protocol_revenue_daily_usd=1.0,
            ),
            self._cfg,
        )
        self.assertEqual(r["label"], "DEATH_SPIRAL_EMISSIONS")

    def test_score_increases_as_emissions_decrease(self):
        rates = [1_000_000.0, 500_000.0, 100_000.0, 10_000.0, 0.0]
        scores = [
            analyze(_proto(native_token_emission_rate_per_day=r), self._cfg)[
                "emission_sustainability_score"
            ]
            for r in rates
        ]
        # Should generally increase as emissions decrease
        self.assertLess(scores[0], scores[-1])

    def test_all_5_labels_reachable(self):
        labels = set()
        configs = [
            _proto(native_token_emission_rate_per_day=0.0),              # sustainable
            _proto(native_token_emission_rate_per_day=50_000.0),         # manageable
            _proto(native_token_emission_rate_per_day=200_000.0),        # high dilution
            _proto(native_token_emission_rate_per_day=1_000_000.0),      # hyperinflationary
            _proto(
                native_token_emission_rate_per_day=100_000_000.0,
                protocol_revenue_daily_usd=100.0,
            ),  # death spiral
        ]
        for c in configs:
            r = analyze(c, self._cfg)
            labels.add(r["label"])
        self.assertEqual(len(labels), 5)

    def test_high_revenue_improves_score(self):
        low = analyze(_proto(protocol_revenue_daily_usd=10_000.0), self._cfg)[
            "emission_sustainability_score"
        ]
        high = analyze(_proto(protocol_revenue_daily_usd=500_000.0), self._cfg)[
            "emission_sustainability_score"
        ]
        self.assertLess(low, high)

    def test_lower_fdv_improves_score(self):
        low_fdv = analyze(
            _proto(token_fully_diluted_valuation_usd=50_000_000.0,
                   protocol_revenue_daily_usd=50_000.0,
                   native_token_emission_rate_per_day=200_000.0),
            self._cfg,
        )["emission_sustainability_score"]
        high_fdv = analyze(
            _proto(token_fully_diluted_valuation_usd=50_000_000_000.0,
                   protocol_revenue_daily_usd=50_000.0,
                   native_token_emission_rate_per_day=200_000.0),
            self._cfg,
        )["emission_sustainability_score"]
        self.assertGreater(low_fdv, high_fdv)


# ===========================================================================
# 15. Edge cases
# ===========================================================================

class TestEdgeCasesMining(unittest.TestCase):
    def setUp(self):
        self._log = _tmp_log()
        self._cfg = {"log_path": self._log}

    def tearDown(self):
        if os.path.exists(self._log):
            os.unlink(self._log)

    def test_empty_dict_does_not_crash(self):
        r = ProtocolDeFiLiquidityMiningDilutionAnalyzer(self._cfg).analyze({})
        self.assertIn("label", r)

    def test_all_zeros(self):
        r = analyze(
            _proto(
                native_token_emission_rate_per_day=0.0,
                native_token_price_usd=0.0,
                total_tvl_usd=0.0,
                protocol_revenue_daily_usd=0.0,
                token_fully_diluted_valuation_usd=0.0,
            ),
            self._cfg,
        )
        self.assertIn("label", r)

    def test_very_large_tvl(self):
        r = analyze(
            _proto(total_tvl_usd=1e15),
            self._cfg,
        )
        self.assertGreaterEqual(r["emission_sustainability_score"], 0.0)

    def test_fdv_to_revenue_inf_does_not_crash(self):
        r = analyze(
            _proto(protocol_revenue_daily_usd=0.0,
                   token_fully_diluted_valuation_usd=1_000_000.0),
            self._cfg,
        )
        # fdv_to_revenue_ratio sentinel is 9_999_999.0
        self.assertIsInstance(r["fdv_to_revenue_ratio"], float)
        self.assertFalse(math.isinf(r["fdv_to_revenue_ratio"]))

    def test_negative_inputs_clamped(self):
        r = analyze(
            _proto(
                native_token_emission_rate_per_day=-1000.0,
                native_token_price_usd=-5.0,
                total_tvl_usd=-1_000_000.0,
            ),
            self._cfg,
        )
        self.assertEqual(r["dilution_yield_pct"], 0.0)

    def test_score_never_nan(self):
        r = analyze(_proto(), self._cfg)
        self.assertFalse(math.isnan(r["emission_sustainability_score"]))

    def test_dilution_yield_zero_when_emission_zero(self):
        r = analyze(_proto(native_token_emission_rate_per_day=0.0), self._cfg)
        self.assertEqual(r["dilution_yield_pct"], 0.0)

    def test_total_yield_always_nonnegative(self):
        r = analyze(_proto(), self._cfg)
        self.assertGreaterEqual(r["total_yield_pct"], 0.0)


if __name__ == "__main__":
    unittest.main()
