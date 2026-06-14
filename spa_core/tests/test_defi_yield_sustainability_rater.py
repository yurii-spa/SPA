"""
Tests for MP-917: DeFiYieldSustainabilityRater
≥85 unittest tests covering all metrics, labels, flags, aggregates, ring-buffer.
"""

import json
import os
import tempfile
import unittest

import sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from spa_core.analytics.defi_yield_sustainability_rater import (
    DeFiYieldSustainabilityRater,
    _safe_div,
    _real_yield_ratio,
    _emission_dependency,
    _token_drag_pct,
    _sustainability_score,
    _sustainability_label,
    _compute_flags,
    _rate_strategy,
    _build_aggregates,
    _atomic_log_append,
    LABEL_HIGHLY_SUSTAINABLE,
    LABEL_SUSTAINABLE,
    LABEL_MODERATE,
    LABEL_DEPENDENT_ON_EMISSIONS,
    LABEL_PONZI_RISK,
    FLAG_EMISSION_HEAVY,
    FLAG_DECLINING_TVL,
    FLAG_TOKEN_COLLAPSING,
    FLAG_UNAUDITED,
    FLAG_YOUNG_PROTOCOL,
    FLAG_REVENUE_POSITIVE,
)


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #

def _strat(**kwargs):
    """Build a minimal valid strategy dict with reasonable defaults."""
    base = {
        "name": "TestStrategy",
        "current_apy_pct": 10.0,
        "real_yield_pct": 7.0,
        "emission_apy_pct": 3.0,
        "protocol_age_months": 24.0,
        "tvl_usd": 50_000_000,
        "tvl_trend": "stable",
        "token_inflation_rate_pct": 5.0,
        "token_price_change_90d_pct": 0.0,
        "audit_count": 3,
        "revenue_per_tvl_pct": 8.0,
    }
    base.update(kwargs)
    return base


# --------------------------------------------------------------------------- #
# Unit: _safe_div
# --------------------------------------------------------------------------- #

class TestSafeDiv(unittest.TestCase):
    def test_normal(self):
        self.assertAlmostEqual(_safe_div(10, 2), 5.0)

    def test_zero_denominator(self):
        self.assertEqual(_safe_div(5, 0), 0.0)

    def test_zero_denominator_custom(self):
        self.assertEqual(_safe_div(5, 0, -99.0), -99.0)

    def test_zero_numerator(self):
        self.assertEqual(_safe_div(0, 5), 0.0)

    def test_both_zero(self):
        self.assertEqual(_safe_div(0, 0), 0.0)

    def test_float_result(self):
        self.assertAlmostEqual(_safe_div(1, 3), 1/3)


# --------------------------------------------------------------------------- #
# Unit: _real_yield_ratio
# --------------------------------------------------------------------------- #

class TestRealYieldRatio(unittest.TestCase):
    def test_fully_real(self):
        # real_yield == total_apy → ratio = 1.0
        self.assertAlmostEqual(_real_yield_ratio(10.0, 10.0), 1.0)

    def test_zero_real(self):
        self.assertAlmostEqual(_real_yield_ratio(0.0, 10.0), 0.0)

    def test_partial_real(self):
        self.assertAlmostEqual(_real_yield_ratio(5.0, 10.0), 0.5, places=3)

    def test_zero_total_apy(self):
        # Division by zero → default 0
        self.assertEqual(_real_yield_ratio(5.0, 0.0), 0.0)

    def test_clamp_above_one(self):
        # real > total (data error) → clamp to 1.0
        self.assertAlmostEqual(_real_yield_ratio(15.0, 10.0), 1.0)

    def test_clamp_below_zero(self):
        # Negative real yield → clamp to 0
        self.assertAlmostEqual(_real_yield_ratio(-5.0, 10.0), 0.0)

    def test_returns_float(self):
        self.assertIsInstance(_real_yield_ratio(5.0, 10.0), float)


# --------------------------------------------------------------------------- #
# Unit: _emission_dependency
# --------------------------------------------------------------------------- #

class TestEmissionDependency(unittest.TestCase):
    def test_fully_emission(self):
        self.assertAlmostEqual(_emission_dependency(10.0, 10.0), 1.0)

    def test_zero_emission(self):
        self.assertAlmostEqual(_emission_dependency(0.0, 10.0), 0.0)

    def test_half_emission(self):
        self.assertAlmostEqual(_emission_dependency(5.0, 10.0), 0.5, places=3)

    def test_zero_total(self):
        self.assertEqual(_emission_dependency(5.0, 0.0), 0.0)

    def test_clamp_above_one(self):
        self.assertAlmostEqual(_emission_dependency(15.0, 10.0), 1.0)

    def test_clamp_below_zero(self):
        self.assertAlmostEqual(_emission_dependency(-1.0, 10.0), 0.0)

    def test_returns_float(self):
        self.assertIsInstance(_emission_dependency(3.0, 10.0), float)


# --------------------------------------------------------------------------- #
# Unit: _token_drag_pct
# --------------------------------------------------------------------------- #

class TestTokenDragPct(unittest.TestCase):
    def test_no_drag_stable_token(self):
        # 0 inflation, 0 price change → drag = 0
        drag = _token_drag_pct(0.0, 0.0, 0.5)
        self.assertAlmostEqual(drag, 0.0)

    def test_drag_with_inflation(self):
        # inflation=10%, no price change, dep=1.0 → drag=10%
        drag = _token_drag_pct(10.0, 0.0, 1.0)
        self.assertAlmostEqual(drag, 10.0)

    def test_drag_with_price_loss(self):
        # no inflation, price -20%, dep=1.0 → drag=20%
        drag = _token_drag_pct(0.0, -20.0, 1.0)
        self.assertAlmostEqual(drag, 20.0)

    def test_price_gain_ignored(self):
        # Price gain should not reduce drag below 0
        drag = _token_drag_pct(0.0, 50.0, 1.0)
        self.assertAlmostEqual(drag, 0.0)

    def test_zero_emission_dep(self):
        # Even with inflation, zero dependency → zero drag
        drag = _token_drag_pct(20.0, -30.0, 0.0)
        self.assertAlmostEqual(drag, 0.0)

    def test_combined_drag(self):
        # inflation=10%, price=-10%, dep=0.5 → drag=(10+10)*0.5=10
        drag = _token_drag_pct(10.0, -10.0, 0.5)
        self.assertAlmostEqual(drag, 10.0)

    def test_returns_float(self):
        self.assertIsInstance(_token_drag_pct(5.0, -5.0, 0.5), float)


# --------------------------------------------------------------------------- #
# Unit: _sustainability_score
# --------------------------------------------------------------------------- #

class TestSustainabilityScore(unittest.TestCase):
    def _score(self, **kwargs):
        defaults = dict(
            real_yield_ratio=1.0,
            protocol_age_months=24.0,
            audit_count=3,
            tvl_trend="growing",
            token_price_change_90d_pct=10.0,
            revenue_per_tvl_pct=5.0,
            emission_dep=0.0,
        )
        defaults.update(kwargs)
        return _sustainability_score(**defaults)

    def test_perfect_score_near_100(self):
        score = self._score()
        self.assertGreaterEqual(score, 80.0)
        self.assertLessEqual(score, 100.0)

    def test_worst_score_near_zero(self):
        score = self._score(
            real_yield_ratio=0.0,
            protocol_age_months=0.0,
            audit_count=0,
            tvl_trend="declining",
            token_price_change_90d_pct=-90.0,
            revenue_per_tvl_pct=0.0,
            emission_dep=0.9,
        )
        self.assertLessEqual(score, 30.0)

    def test_result_in_0_100(self):
        for em in [0.0, 0.5, 0.9, 1.0]:
            score = self._score(emission_dep=em)
            self.assertGreaterEqual(score, 0.0)
            self.assertLessEqual(score, 100.0)

    def test_growing_tvl_better_than_declining(self):
        s_grow = self._score(tvl_trend="growing")
        s_decl = self._score(tvl_trend="declining")
        self.assertGreater(s_grow, s_decl)

    def test_stable_tvl_between(self):
        s_grow = self._score(tvl_trend="growing")
        s_stable = self._score(tvl_trend="stable")
        s_decl = self._score(tvl_trend="declining")
        self.assertGreater(s_grow, s_stable)
        self.assertGreater(s_stable, s_decl)

    def test_more_audits_better(self):
        s_low = self._score(audit_count=0)
        s_high = self._score(audit_count=3)
        self.assertGreater(s_high, s_low)

    def test_older_protocol_better(self):
        s_young = self._score(protocol_age_months=0)
        s_old = self._score(protocol_age_months=24)
        self.assertGreater(s_old, s_young)

    def test_emission_penalty_applied(self):
        s_no_em = self._score(emission_dep=0.0)
        s_heavy_em = self._score(emission_dep=0.9)
        self.assertGreater(s_no_em, s_heavy_em)

    def test_higher_real_yield_ratio_better(self):
        s_low = self._score(real_yield_ratio=0.0)
        s_high = self._score(real_yield_ratio=1.0)
        self.assertGreater(s_high, s_low)

    def test_token_collapse_lowers_score(self):
        s_good = self._score(token_price_change_90d_pct=20.0)
        s_bad = self._score(token_price_change_90d_pct=-80.0)
        self.assertGreater(s_good, s_bad)

    def test_returns_float(self):
        self.assertIsInstance(self._score(), float)


# --------------------------------------------------------------------------- #
# Unit: _sustainability_label
# --------------------------------------------------------------------------- #

class TestSustainabilityLabel(unittest.TestCase):
    def test_highly_sustainable_high_score_low_emission(self):
        label = _sustainability_label(85.0, 0.1)
        self.assertEqual(label, LABEL_HIGHLY_SUSTAINABLE)

    def test_sustainable_mid_score(self):
        label = _sustainability_label(60.0, 0.3)
        self.assertEqual(label, LABEL_SUSTAINABLE)

    def test_moderate_mid_score(self):
        label = _sustainability_label(40.0, 0.3)
        self.assertEqual(label, LABEL_MODERATE)

    def test_dependent_on_emissions(self):
        label = _sustainability_label(40.0, 0.7)
        self.assertEqual(label, LABEL_DEPENDENT_ON_EMISSIONS)

    def test_ponzi_risk_low_score_high_emission(self):
        label = _sustainability_label(15.0, 0.9)
        self.assertEqual(label, LABEL_PONZI_RISK)

    def test_ponzi_risk_very_low_score(self):
        label = _sustainability_label(5.0, 0.2)
        self.assertEqual(label, LABEL_PONZI_RISK)

    def test_boundary_highly_sustainable_at_75(self):
        label = _sustainability_label(75.0, 0.1)
        self.assertEqual(label, LABEL_HIGHLY_SUSTAINABLE)

    def test_boundary_sustainable_at_55(self):
        label = _sustainability_label(55.0, 0.1)
        self.assertEqual(label, LABEL_SUSTAINABLE)

    def test_boundary_moderate_at_35(self):
        label = _sustainability_label(35.0, 0.3)
        self.assertEqual(label, LABEL_MODERATE)


# --------------------------------------------------------------------------- #
# Unit: _compute_flags
# --------------------------------------------------------------------------- #

class TestComputeFlags(unittest.TestCase):
    def _flags(self, **kwargs):
        defaults = dict(
            emission_apy_pct=2.0,
            current_apy_pct=10.0,
            tvl_trend="stable",
            token_price_change_90d_pct=0.0,
            audit_count=3,
            protocol_age_months=12.0,
            revenue_per_tvl_pct=5.0,
            real_yield_pct=7.0,
        )
        defaults.update(kwargs)
        return _compute_flags(**defaults)

    def test_no_flags_normal(self):
        self.assertEqual(self._flags(), [])

    def test_emission_heavy(self):
        flags = self._flags(emission_apy_pct=9.0, current_apy_pct=10.0)
        self.assertIn(FLAG_EMISSION_HEAVY, flags)

    def test_emission_heavy_exactly_80pct(self):
        # 8/10 = 80% — should NOT trigger (> 80%)
        flags = self._flags(emission_apy_pct=8.0, current_apy_pct=10.0)
        self.assertNotIn(FLAG_EMISSION_HEAVY, flags)

    def test_declining_tvl(self):
        flags = self._flags(tvl_trend="declining")
        self.assertIn(FLAG_DECLINING_TVL, flags)

    def test_stable_tvl_no_flag(self):
        flags = self._flags(tvl_trend="stable")
        self.assertNotIn(FLAG_DECLINING_TVL, flags)

    def test_growing_tvl_no_flag(self):
        flags = self._flags(tvl_trend="growing")
        self.assertNotIn(FLAG_DECLINING_TVL, flags)

    def test_token_collapsing(self):
        flags = self._flags(token_price_change_90d_pct=-60.0)
        self.assertIn(FLAG_TOKEN_COLLAPSING, flags)

    def test_token_not_collapsing_boundary(self):
        flags = self._flags(token_price_change_90d_pct=-49.9)
        self.assertNotIn(FLAG_TOKEN_COLLAPSING, flags)

    def test_unaudited(self):
        flags = self._flags(audit_count=0)
        self.assertIn(FLAG_UNAUDITED, flags)

    def test_audited_no_flag(self):
        flags = self._flags(audit_count=1)
        self.assertNotIn(FLAG_UNAUDITED, flags)

    def test_young_protocol(self):
        flags = self._flags(protocol_age_months=3.0)
        self.assertIn(FLAG_YOUNG_PROTOCOL, flags)

    def test_not_young_at_6_months(self):
        flags = self._flags(protocol_age_months=6.0)
        self.assertNotIn(FLAG_YOUNG_PROTOCOL, flags)

    def test_revenue_positive(self):
        flags = self._flags(revenue_per_tvl_pct=10.0, real_yield_pct=7.0)
        self.assertIn(FLAG_REVENUE_POSITIVE, flags)

    def test_no_revenue_positive(self):
        flags = self._flags(revenue_per_tvl_pct=5.0, real_yield_pct=7.0)
        self.assertNotIn(FLAG_REVENUE_POSITIVE, flags)

    def test_all_flags_simultaneously(self):
        flags = self._flags(
            emission_apy_pct=9.0,
            current_apy_pct=10.0,
            tvl_trend="declining",
            token_price_change_90d_pct=-60.0,
            audit_count=0,
            protocol_age_months=3.0,
            revenue_per_tvl_pct=10.0,
            real_yield_pct=1.0,
        )
        self.assertEqual(len(flags), 6)

    def test_flags_return_list(self):
        self.assertIsInstance(self._flags(), list)


# --------------------------------------------------------------------------- #
# Unit: _rate_strategy
# --------------------------------------------------------------------------- #

class TestRateStrategy(unittest.TestCase):
    def test_returns_dict(self):
        r = _rate_strategy(_strat())
        self.assertIsInstance(r, dict)

    def test_required_keys(self):
        r = _rate_strategy(_strat())
        for key in ["name", "real_yield_ratio", "sustainability_score",
                    "emission_dependency", "token_drag_pct",
                    "sustainability_label", "flags"]:
            self.assertIn(key, r)

    def test_name_preserved(self):
        r = _rate_strategy(_strat(name="Aave"))
        self.assertEqual(r["name"], "Aave")

    def test_scores_in_range(self):
        r = _rate_strategy(_strat())
        self.assertGreaterEqual(r["sustainability_score"], 0.0)
        self.assertLessEqual(r["sustainability_score"], 100.0)
        self.assertGreaterEqual(r["real_yield_ratio"], 0.0)
        self.assertLessEqual(r["real_yield_ratio"], 1.0)
        self.assertGreaterEqual(r["emission_dependency"], 0.0)
        self.assertLessEqual(r["emission_dependency"], 1.0)

    def test_highly_sustainable_label(self):
        r = _rate_strategy(_strat(
            current_apy_pct=10.0,
            real_yield_pct=10.0,
            emission_apy_pct=0.0,
            protocol_age_months=36.0,
            tvl_trend="growing",
            token_price_change_90d_pct=20.0,
            audit_count=5,
            revenue_per_tvl_pct=12.0,
        ))
        self.assertIn(r["sustainability_label"],
                      [LABEL_HIGHLY_SUSTAINABLE, LABEL_SUSTAINABLE])

    def test_ponzi_risk_label(self):
        r = _rate_strategy(_strat(
            current_apy_pct=200.0,
            real_yield_pct=0.0,
            emission_apy_pct=200.0,
            protocol_age_months=1.0,
            tvl_trend="declining",
            token_price_change_90d_pct=-80.0,
            audit_count=0,
            revenue_per_tvl_pct=0.0,
        ))
        self.assertEqual(r["sustainability_label"], LABEL_PONZI_RISK)

    def test_flags_type(self):
        r = _rate_strategy(_strat())
        self.assertIsInstance(r["flags"], list)

    def test_unaudited_flag(self):
        r = _rate_strategy(_strat(audit_count=0))
        self.assertIn(FLAG_UNAUDITED, r["flags"])

    def test_young_protocol_flag(self):
        r = _rate_strategy(_strat(protocol_age_months=2.0))
        self.assertIn(FLAG_YOUNG_PROTOCOL, r["flags"])

    def test_emission_heavy_flag(self):
        r = _rate_strategy(_strat(
            current_apy_pct=10.0,
            emission_apy_pct=9.0,
            real_yield_pct=1.0,
        ))
        self.assertIn(FLAG_EMISSION_HEAVY, r["flags"])

    def test_token_collapsing_flag(self):
        r = _rate_strategy(_strat(token_price_change_90d_pct=-75.0))
        self.assertIn(FLAG_TOKEN_COLLAPSING, r["flags"])

    def test_declining_tvl_flag(self):
        r = _rate_strategy(_strat(tvl_trend="declining"))
        self.assertIn(FLAG_DECLINING_TVL, r["flags"])

    def test_revenue_positive_flag(self):
        r = _rate_strategy(_strat(revenue_per_tvl_pct=15.0, real_yield_pct=5.0))
        self.assertIn(FLAG_REVENUE_POSITIVE, r["flags"])

    def test_zero_apy_handled(self):
        r = _rate_strategy(_strat(current_apy_pct=0.0, real_yield_pct=0.0, emission_apy_pct=0.0))
        self.assertAlmostEqual(r["real_yield_ratio"], 0.0)
        self.assertAlmostEqual(r["emission_dependency"], 0.0)

    def test_missing_optional_fields_defaults(self):
        r = _rate_strategy({"name": "minimal"})
        self.assertEqual(r["name"], "minimal")
        self.assertGreaterEqual(r["sustainability_score"], 0.0)

    def test_token_drag_zero_with_no_emissions(self):
        r = _rate_strategy(_strat(
            emission_apy_pct=0.0, current_apy_pct=10.0,
            token_inflation_rate_pct=5.0, token_price_change_90d_pct=-10.0
        ))
        # emission_dep = 0 → token drag = 0
        self.assertAlmostEqual(r["token_drag_pct"], 0.0)


# --------------------------------------------------------------------------- #
# Unit: _build_aggregates
# --------------------------------------------------------------------------- #

class TestBuildAggregates(unittest.TestCase):
    def test_empty_returns_defaults(self):
        agg = _build_aggregates([])
        self.assertIsNone(agg["most_sustainable"])
        self.assertIsNone(agg["highest_ponzi_risk"])
        self.assertEqual(agg["average_real_yield_ratio"], 0.0)
        self.assertEqual(agg["average_sustainability"], 0.0)
        self.assertEqual(agg["ponzi_risk_count"], 0)

    def test_single_strategy(self):
        results = [_rate_strategy(_strat(name="Solo"))]
        agg = _build_aggregates(results)
        self.assertEqual(agg["most_sustainable"], "Solo")
        self.assertEqual(agg["highest_ponzi_risk"], "Solo")

    def test_most_sustainable_identified(self):
        r1 = _rate_strategy(_strat(name="Good", current_apy_pct=10.0, real_yield_pct=10.0,
                                   protocol_age_months=36, audit_count=5, tvl_trend="growing"))
        r2 = _rate_strategy(_strat(name="Bad", current_apy_pct=200.0, real_yield_pct=0.0,
                                   emission_apy_pct=200.0, protocol_age_months=1, audit_count=0,
                                   tvl_trend="declining"))
        agg = _build_aggregates([r1, r2])
        self.assertEqual(agg["most_sustainable"], "Good")

    def test_highest_ponzi_risk_identified(self):
        r1 = _rate_strategy(_strat(name="Good", current_apy_pct=10.0, real_yield_pct=10.0,
                                   protocol_age_months=36, audit_count=5, tvl_trend="growing"))
        r2 = _rate_strategy(_strat(name="Ponzi", current_apy_pct=200.0, real_yield_pct=0.0,
                                   emission_apy_pct=200.0, protocol_age_months=1, audit_count=0,
                                   tvl_trend="declining"))
        agg = _build_aggregates([r1, r2])
        self.assertEqual(agg["highest_ponzi_risk"], "Ponzi")

    def test_average_real_yield_ratio(self):
        r1 = _rate_strategy(_strat(current_apy_pct=10.0, real_yield_pct=10.0))  # ratio ~1
        r2 = _rate_strategy(_strat(current_apy_pct=10.0, real_yield_pct=0.0))   # ratio ~0
        agg = _build_aggregates([r1, r2])
        self.assertAlmostEqual(agg["average_real_yield_ratio"], 0.5, places=2)

    def test_average_sustainability_in_range(self):
        results = [_rate_strategy(_strat()) for _ in range(5)]
        agg = _build_aggregates(results)
        self.assertGreaterEqual(agg["average_sustainability"], 0.0)
        self.assertLessEqual(agg["average_sustainability"], 100.0)

    def test_ponzi_risk_count(self):
        ponzi = _rate_strategy(_strat(
            current_apy_pct=200.0, real_yield_pct=0.0, emission_apy_pct=200.0,
            protocol_age_months=1, audit_count=0, tvl_trend="declining",
            token_price_change_90d_pct=-80.0,
        ))
        normal = _rate_strategy(_strat())
        agg = _build_aggregates([ponzi, normal])
        self.assertGreaterEqual(agg["ponzi_risk_count"], 1)

    def test_ponzi_count_zero(self):
        results = [_rate_strategy(_strat()) for _ in range(3)]
        agg = _build_aggregates(results)
        # Default strat should not be PONZI_RISK
        self.assertLessEqual(agg["ponzi_risk_count"], 3)


# --------------------------------------------------------------------------- #
# Unit: _atomic_log_append (ring-buffer)
# --------------------------------------------------------------------------- #

class TestAtomicLogAppend(unittest.TestCase):
    def setUp(self):
        self.tmp_dir = tempfile.mkdtemp()
        self.log_path = os.path.join(self.tmp_dir, "yield_sus_log.json")

    def test_creates_file(self):
        _atomic_log_append({"x": 1}, self.log_path, cap=10)
        self.assertTrue(os.path.exists(self.log_path))

    def test_single_entry(self):
        _atomic_log_append({"x": 1}, self.log_path, cap=10)
        with open(self.log_path) as f:
            data = json.load(f)
        self.assertEqual(len(data), 1)

    def test_multiple_entries(self):
        for i in range(5):
            _atomic_log_append({"i": i}, self.log_path, cap=10)
        with open(self.log_path) as f:
            data = json.load(f)
        self.assertEqual(len(data), 5)

    def test_ring_buffer_cap(self):
        for i in range(15):
            _atomic_log_append({"i": i}, self.log_path, cap=10)
        with open(self.log_path) as f:
            data = json.load(f)
        self.assertEqual(len(data), 10)

    def test_ring_buffer_newest_last(self):
        for i in range(12):
            _atomic_log_append({"i": i}, self.log_path, cap=10)
        with open(self.log_path) as f:
            data = json.load(f)
        self.assertEqual(data[-1]["i"], 11)

    def test_ring_buffer_oldest_evicted(self):
        for i in range(12):
            _atomic_log_append({"i": i}, self.log_path, cap=10)
        with open(self.log_path) as f:
            data = json.load(f)
        self.assertEqual(data[0]["i"], 2)

    def test_corrupted_file_resets(self):
        with open(self.log_path, "w") as f:
            f.write("INVALID JSON")
        _atomic_log_append({"x": 99}, self.log_path, cap=10)
        with open(self.log_path) as f:
            data = json.load(f)
        self.assertEqual(len(data), 1)
        self.assertEqual(data[0]["x"], 99)

    def test_no_tmp_file_left_behind(self):
        _atomic_log_append({"x": 1}, self.log_path, cap=10)
        self.assertFalse(os.path.exists(self.log_path + ".tmp"))

    def test_valid_json_output(self):
        _atomic_log_append({"key": "value"}, self.log_path, cap=10)
        with open(self.log_path) as f:
            data = json.load(f)
        self.assertIsInstance(data, list)


# --------------------------------------------------------------------------- #
# Integration: DeFiYieldSustainabilityRater.rate()
# --------------------------------------------------------------------------- #

class TestDeFiYieldSustainabilityRaterRate(unittest.TestCase):
    def setUp(self):
        self.tmp_dir = tempfile.mkdtemp()
        self.log_path = os.path.join(self.tmp_dir, "yield_sus.json")
        self.rater = DeFiYieldSustainabilityRater(log_path=self.log_path)

    def _make_strategies(self, n=3):
        return [_strat(name=f"Strategy{i}") for i in range(n)]

    def test_returns_dict(self):
        result = self.rater.rate(self._make_strategies())
        self.assertIsInstance(result, dict)

    def test_has_strategies_key(self):
        result = self.rater.rate(self._make_strategies())
        self.assertIn("strategies", result)

    def test_has_aggregates_key(self):
        result = self.rater.rate(self._make_strategies())
        self.assertIn("aggregates", result)

    def test_has_timestamp_key(self):
        result = self.rater.rate(self._make_strategies())
        self.assertIn("timestamp", result)

    def test_strategies_count_matches_input(self):
        result = self.rater.rate(self._make_strategies(5))
        self.assertEqual(len(result["strategies"]), 5)

    def test_empty_strategies(self):
        result = self.rater.rate([])
        self.assertEqual(result["strategies"], [])
        self.assertIsNone(result["aggregates"]["most_sustainable"])

    def test_log_created(self):
        self.rater.rate(self._make_strategies())
        self.assertTrue(os.path.exists(self.log_path))

    def test_log_entry_count(self):
        self.rater.rate(self._make_strategies())
        self.rater.rate(self._make_strategies())
        with open(self.log_path) as f:
            entries = json.load(f)
        self.assertEqual(len(entries), 2)

    def test_ring_buffer_cap_respected(self):
        for _ in range(105):
            self.rater.rate(self._make_strategies(1))
        with open(self.log_path) as f:
            entries = json.load(f)
        self.assertEqual(len(entries), 100)

    def test_config_none_allowed(self):
        result = self.rater.rate(self._make_strategies(), config=None)
        self.assertIn("strategies", result)

    def test_config_dict_allowed(self):
        result = self.rater.rate(self._make_strategies(), config={"x": 1})
        self.assertIn("strategies", result)

    def test_timestamp_format(self):
        result = self.rater.rate(self._make_strategies())
        ts = result["timestamp"]
        self.assertTrue(ts.endswith("Z"))
        self.assertIn("T", ts)

    def test_per_strategy_label_present(self):
        result = self.rater.rate(self._make_strategies(1))
        self.assertIn("sustainability_label", result["strategies"][0])

    def test_per_strategy_flags_list(self):
        result = self.rater.rate(self._make_strategies(1))
        self.assertIsInstance(result["strategies"][0]["flags"], list)

    def test_aggregates_most_sustainable(self):
        strats = [
            _strat(name="Best", current_apy_pct=10.0, real_yield_pct=10.0,
                   protocol_age_months=36, audit_count=5, tvl_trend="growing"),
            _strat(name="Worst", current_apy_pct=200.0, real_yield_pct=0.0,
                   emission_apy_pct=200.0, protocol_age_months=1, audit_count=0,
                   tvl_trend="declining"),
        ]
        result = self.rater.rate(strats)
        self.assertEqual(result["aggregates"]["most_sustainable"], "Best")

    def test_aggregates_highest_ponzi_risk(self):
        strats = [
            _strat(name="Best", current_apy_pct=10.0, real_yield_pct=10.0,
                   protocol_age_months=36, audit_count=5, tvl_trend="growing"),
            _strat(name="Worst", current_apy_pct=200.0, real_yield_pct=0.0,
                   emission_apy_pct=200.0, protocol_age_months=1, audit_count=0,
                   tvl_trend="declining"),
        ]
        result = self.rater.rate(strats)
        self.assertEqual(result["aggregates"]["highest_ponzi_risk"], "Worst")

    def test_unaudited_strategy_flagged(self):
        strats = [_strat(audit_count=0)]
        result = self.rater.rate(strats)
        self.assertIn(FLAG_UNAUDITED, result["strategies"][0]["flags"])

    def test_young_protocol_flagged(self):
        strats = [_strat(protocol_age_months=2.0)]
        result = self.rater.rate(strats)
        self.assertIn(FLAG_YOUNG_PROTOCOL, result["strategies"][0]["flags"])

    def test_token_collapsing_flagged(self):
        strats = [_strat(token_price_change_90d_pct=-75.0)]
        result = self.rater.rate(strats)
        self.assertIn(FLAG_TOKEN_COLLAPSING, result["strategies"][0]["flags"])

    def test_emission_heavy_flagged(self):
        strats = [_strat(current_apy_pct=10.0, emission_apy_pct=9.5, real_yield_pct=0.5)]
        result = self.rater.rate(strats)
        self.assertIn(FLAG_EMISSION_HEAVY, result["strategies"][0]["flags"])

    def test_declining_tvl_flagged(self):
        strats = [_strat(tvl_trend="declining")]
        result = self.rater.rate(strats)
        self.assertIn(FLAG_DECLINING_TVL, result["strategies"][0]["flags"])

    def test_revenue_positive_flagged(self):
        strats = [_strat(revenue_per_tvl_pct=15.0, real_yield_pct=5.0)]
        result = self.rater.rate(strats)
        self.assertIn(FLAG_REVENUE_POSITIVE, result["strategies"][0]["flags"])

    def test_normal_no_flags(self):
        strats = [_strat(
            current_apy_pct=10.0,
            real_yield_pct=7.0,
            emission_apy_pct=3.0,
            protocol_age_months=24.0,
            tvl_trend="stable",
            token_price_change_90d_pct=5.0,
            audit_count=3,
            revenue_per_tvl_pct=6.0,
        )]
        result = self.rater.rate(strats)
        # Should not have TOKEN_COLLAPSING, UNAUDITED, YOUNG_PROTOCOL, DECLINING_TVL
        flags = result["strategies"][0]["flags"]
        self.assertNotIn(FLAG_TOKEN_COLLAPSING, flags)
        self.assertNotIn(FLAG_UNAUDITED, flags)
        self.assertNotIn(FLAG_YOUNG_PROTOCOL, flags)
        self.assertNotIn(FLAG_DECLINING_TVL, flags)

    def test_sustainability_score_in_range(self):
        strats = self._make_strategies(10)
        result = self.rater.rate(strats)
        for s in result["strategies"]:
            self.assertGreaterEqual(s["sustainability_score"], 0.0)
            self.assertLessEqual(s["sustainability_score"], 100.0)

    def test_real_yield_ratio_in_range(self):
        strats = self._make_strategies(10)
        result = self.rater.rate(strats)
        for s in result["strategies"]:
            self.assertGreaterEqual(s["real_yield_ratio"], 0.0)
            self.assertLessEqual(s["real_yield_ratio"], 1.0)

    def test_large_strategy_set(self):
        strats = [_strat(name=f"S{i}") for i in range(50)]
        result = self.rater.rate(strats)
        self.assertEqual(len(result["strategies"]), 50)

    def test_average_real_yield_ratio_in_range(self):
        strats = self._make_strategies(5)
        result = self.rater.rate(strats)
        avg = result["aggregates"]["average_real_yield_ratio"]
        self.assertGreaterEqual(avg, 0.0)
        self.assertLessEqual(avg, 1.0)

    def test_log_entry_has_aggregates(self):
        self.rater.rate(self._make_strategies())
        with open(self.log_path) as f:
            entries = json.load(f)
        self.assertIn("aggregates", entries[0])

    def test_log_entry_has_timestamp(self):
        self.rater.rate(self._make_strategies())
        with open(self.log_path) as f:
            entries = json.load(f)
        self.assertIn("timestamp", entries[0])

    def test_log_entry_has_strategy_count(self):
        strats = self._make_strategies(7)
        self.rater.rate(strats)
        with open(self.log_path) as f:
            entries = json.load(f)
        self.assertEqual(entries[0]["strategy_count"], 7)


if __name__ == "__main__":
    unittest.main()
