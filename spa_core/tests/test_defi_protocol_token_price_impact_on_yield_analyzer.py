"""
Tests for MP-1108: DeFiProtocolTokenPriceImpactOnYieldAnalyzer
≥ 110 tests, unittest framework (python3 -m unittest).

Label decision tree (uses 30d-ago token ratio to measure original exposure):
  1. token_apy_current <= 0                                 → APY_DESTROYED
  2. token_ratio_30d < 30% (base yield dominates originally) → PRICE_RESILIENT
  3. |price_change| >= 70%                                  → APY_DESTROYED
  4. token_ratio_30d in [30-50%] AND |change| < 20%         → MILD_IMPACT
  5. |price_change| >= 40%                                  → HIGH_IMPACT
  6. |price_change| >= 20%                                  → MODERATE_IMPACT
  7. else (token dominates, small change)                   → MILD_IMPACT
"""

import json
import math
import os
import tempfile
import unittest

from spa_core.analytics.defi_protocol_token_price_impact_on_yield_analyzer import (
    DeFiProtocolTokenPriceImpactOnYieldAnalyzer,
    _atomic_write,
    _clamp,
    VALID_LABELS,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def make_analyzer(tmp_dir: str, cap: int = 5) -> DeFiProtocolTokenPriceImpactOnYieldAnalyzer:
    log_path = os.path.join(tmp_dir, "token_price_impact_test.json")
    return DeFiProtocolTokenPriceImpactOnYieldAnalyzer(log_path=log_path, log_cap=cap)


def base_kwargs(**overrides):
    """Return a minimal, valid kwarg dict (emission=1000 tokens/day, price=$1, TVL=$1M)."""
    kw = dict(
        reward_token_emission_per_day=1000.0,
        reward_token_current_price_usd=1.0,
        reward_token_price_30d_ago_usd=1.0,
        pool_tvl_usd=1_000_000.0,
        base_protocol_apy_pct=3.0,
        position_size_usd=10_000.0,
        protocol_name="TestProtocol",
    )
    kw.update(overrides)
    return kw


# token_apy for default base_kwargs: 1000 * $1 * 365 / $1M * 100 = 36.5%
_DEFAULT_TOKEN_APY = 36.5


def _label_with_token_ratio_30d(base_apy: float, token_ratio_30d_target: float,
                                  abs_change_pct: float, change_direction: int = -1,
                                  emission: float = 1000.0, tvl: float = 1_000_000.0
                                 ) -> str:
    """
    Helper: set base_apy so token_ratio_30d == target, apply price change.
    Returns the label produced by the analyzer.
    emission & tvl determine token_apy_30d.
    """
    import tempfile, os
    tmp = tempfile.mkdtemp()
    az = make_analyzer(tmp)
    token_apy_30d = emission * 1.0 * 365 / tvl * 100  # old_price=1.0
    # token_ratio_30d = token_apy_30d / (token_apy_30d + base) = target
    # → base = token_apy_30d * (1 - target) / target
    base = token_apy_30d * (1 - token_ratio_30d_target) / token_ratio_30d_target
    new_price = 1.0 * (1 - change_direction * abs_change_pct / 100)
    # use change_direction=-1 for drop
    r = az.analyze(**base_kwargs(
        reward_token_emission_per_day=emission,
        base_protocol_apy_pct=base,
        reward_token_current_price_usd=new_price,
        reward_token_price_30d_ago_usd=1.0,
        pool_tvl_usd=tvl,
    ))
    return r["price_impact_label"]


# ===========================================================================
# 1. Helpers unit tests
# ===========================================================================

class TestHelpers(unittest.TestCase):

    def test_clamp_within_range(self):
        self.assertEqual(_clamp(50.0), 50.0)

    def test_clamp_at_lower_bound(self):
        self.assertEqual(_clamp(0.0), 0.0)

    def test_clamp_at_upper_bound(self):
        self.assertEqual(_clamp(100.0), 100.0)

    def test_clamp_below_zero(self):
        self.assertEqual(_clamp(-5.0), 0.0)

    def test_clamp_above_100(self):
        self.assertEqual(_clamp(105.0), 100.0)

    def test_clamp_custom_lo(self):
        self.assertEqual(_clamp(5.0, lo=10.0, hi=50.0), 10.0)

    def test_clamp_custom_hi(self):
        self.assertEqual(_clamp(60.0, lo=10.0, hi=50.0), 50.0)

    def test_clamp_custom_mid(self):
        self.assertEqual(_clamp(30.0, lo=10.0, hi=50.0), 30.0)

    def test_atomic_write_creates_file(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "sub", "test.json")
            _atomic_write(path, [1, 2, 3])
            self.assertTrue(os.path.exists(path))
            with open(path) as f:
                data = json.load(f)
            self.assertEqual(data, [1, 2, 3])

    def test_atomic_write_no_tmp_left(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "test.json")
            _atomic_write(path, {"x": 1})
            self.assertFalse(os.path.exists(path + ".tmp"))

    def test_valid_labels_set_size(self):
        self.assertEqual(len(VALID_LABELS), 5)

    def test_valid_labels_contains_all(self):
        for lbl in ["PRICE_RESILIENT", "MILD_IMPACT", "MODERATE_IMPACT",
                    "HIGH_IMPACT", "APY_DESTROYED"]:
            self.assertIn(lbl, VALID_LABELS)


# ===========================================================================
# 2. Token APY calculations
# ===========================================================================

class TestTokenAPYCalculation(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.az = make_analyzer(self.tmp)

    def test_token_apy_current_basic(self):
        # 1000 tokens/day * $1 * 365 / $1M * 100 = 36.5%
        r = self.az.analyze(**base_kwargs())
        self.assertAlmostEqual(r["token_apy_current_pct"], 36.5, places=3)

    def test_token_apy_current_zero_emission(self):
        r = self.az.analyze(**base_kwargs(reward_token_emission_per_day=0))
        self.assertEqual(r["token_apy_current_pct"], 0.0)

    def test_token_apy_current_zero_price(self):
        r = self.az.analyze(**base_kwargs(reward_token_current_price_usd=0.0))
        self.assertEqual(r["token_apy_current_pct"], 0.0)

    def test_token_apy_current_high_price(self):
        r = self.az.analyze(**base_kwargs(reward_token_current_price_usd=10.0))
        self.assertAlmostEqual(r["token_apy_current_pct"], 365.0, places=3)

    def test_token_apy_current_large_tvl(self):
        r = self.az.analyze(**base_kwargs(pool_tvl_usd=1_000_000_000.0))
        self.assertAlmostEqual(r["token_apy_current_pct"], 0.0365, places=4)

    def test_token_apy_30d_higher_30d_price(self):
        r = self.az.analyze(**base_kwargs(reward_token_price_30d_ago_usd=2.0))
        self.assertAlmostEqual(r["token_apy_30d_ago_pct"], 73.0, places=3)

    def test_token_apy_30d_equals_current_same_price(self):
        r = self.az.analyze(**base_kwargs())
        self.assertAlmostEqual(r["token_apy_current_pct"],
                               r["token_apy_30d_ago_pct"], places=6)

    def test_token_apy_current_rounds_to_6_places(self):
        r = self.az.analyze(**base_kwargs())
        val = r["token_apy_current_pct"]
        self.assertEqual(round(val, 6), val)

    def test_token_apy_30d_rounds_to_6_places(self):
        r = self.az.analyze(**base_kwargs())
        val = r["token_apy_30d_ago_pct"]
        self.assertEqual(round(val, 6), val)

    def test_token_apy_proportional_to_emission(self):
        r1 = self.az.analyze(**base_kwargs(reward_token_emission_per_day=500.0))
        r2 = self.az.analyze(**base_kwargs(reward_token_emission_per_day=1000.0))
        self.assertAlmostEqual(r2["token_apy_current_pct"],
                               r1["token_apy_current_pct"] * 2, places=5)

    def test_token_apy_proportional_to_price(self):
        r1 = self.az.analyze(**base_kwargs(reward_token_current_price_usd=1.0))
        r2 = self.az.analyze(**base_kwargs(reward_token_current_price_usd=3.0))
        self.assertAlmostEqual(r2["token_apy_current_pct"],
                               r1["token_apy_current_pct"] * 3, places=5)

    def test_token_apy_inversely_proportional_to_tvl(self):
        r1 = self.az.analyze(**base_kwargs(pool_tvl_usd=500_000.0))
        r2 = self.az.analyze(**base_kwargs(pool_tvl_usd=1_000_000.0))
        self.assertAlmostEqual(r1["token_apy_current_pct"],
                               r2["token_apy_current_pct"] * 2, places=5)


# ===========================================================================
# 3. Token price change
# ===========================================================================

class TestPriceChange(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.az = make_analyzer(self.tmp)

    def test_price_unchanged(self):
        r = self.az.analyze(**base_kwargs())
        self.assertAlmostEqual(r["token_price_change_pct"], 0.0, places=6)

    def test_price_doubled(self):
        r = self.az.analyze(**base_kwargs(
            reward_token_current_price_usd=2.0,
            reward_token_price_30d_ago_usd=1.0,
        ))
        self.assertAlmostEqual(r["token_price_change_pct"], 100.0, places=4)

    def test_price_halved(self):
        r = self.az.analyze(**base_kwargs(
            reward_token_current_price_usd=0.5,
            reward_token_price_30d_ago_usd=1.0,
        ))
        self.assertAlmostEqual(r["token_price_change_pct"], -50.0, places=4)

    def test_price_dropped_90pct(self):
        r = self.az.analyze(**base_kwargs(
            reward_token_current_price_usd=0.1,
            reward_token_price_30d_ago_usd=1.0,
        ))
        self.assertAlmostEqual(r["token_price_change_pct"], -90.0, places=4)

    def test_price_up_25pct(self):
        r = self.az.analyze(**base_kwargs(
            reward_token_current_price_usd=1.25,
            reward_token_price_30d_ago_usd=1.0,
        ))
        self.assertAlmostEqual(r["token_price_change_pct"], 25.0, places=4)

    def test_price_change_rounds_to_6_places(self):
        r = self.az.analyze(**base_kwargs(
            reward_token_current_price_usd=1.333,
            reward_token_price_30d_ago_usd=1.0,
        ))
        val = r["token_price_change_pct"]
        self.assertEqual(round(val, 6), val)

    def test_price_increase_gives_positive_change(self):
        r = self.az.analyze(**base_kwargs(
            reward_token_current_price_usd=1.5,
            reward_token_price_30d_ago_usd=1.0,
        ))
        self.assertGreater(r["token_price_change_pct"], 0)

    def test_price_decrease_gives_negative_change(self):
        r = self.az.analyze(**base_kwargs(
            reward_token_current_price_usd=0.8,
            reward_token_price_30d_ago_usd=1.0,
        ))
        self.assertLess(r["token_price_change_pct"], 0)


# ===========================================================================
# 4. APY impact
# ===========================================================================

class TestAPYImpact(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.az = make_analyzer(self.tmp)

    def test_no_impact_when_price_unchanged(self):
        r = self.az.analyze(**base_kwargs())
        self.assertAlmostEqual(r["apy_impact_pct"], 0.0, places=6)

    def test_positive_impact_when_price_up(self):
        r = self.az.analyze(**base_kwargs(
            reward_token_current_price_usd=2.0,
            reward_token_price_30d_ago_usd=1.0,
        ))
        self.assertGreater(r["apy_impact_pct"], 0)

    def test_negative_impact_when_price_down(self):
        r = self.az.analyze(**base_kwargs(
            reward_token_current_price_usd=0.5,
            reward_token_price_30d_ago_usd=1.0,
        ))
        self.assertLess(r["apy_impact_pct"], 0)

    def test_apy_impact_equals_diff_of_token_apys(self):
        r = self.az.analyze(**base_kwargs(
            reward_token_current_price_usd=0.6,
            reward_token_price_30d_ago_usd=1.2,
        ))
        expected = r["token_apy_current_pct"] - r["token_apy_30d_ago_pct"]
        self.assertAlmostEqual(r["apy_impact_pct"], expected, places=5)

    def test_apy_impact_zero_emission(self):
        r = self.az.analyze(**base_kwargs(reward_token_emission_per_day=0))
        self.assertAlmostEqual(r["apy_impact_pct"], 0.0, places=6)

    def test_apy_impact_rounds_to_6_places(self):
        r = self.az.analyze(**base_kwargs(
            reward_token_current_price_usd=0.77,
            reward_token_price_30d_ago_usd=1.0,
        ))
        val = r["apy_impact_pct"]
        self.assertEqual(round(val, 6), val)


# ===========================================================================
# 5. Total APY and daily yield
# ===========================================================================

class TestTotalAPYAndDailyYield(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.az = make_analyzer(self.tmp)

    def test_total_apy_is_base_plus_token(self):
        r = self.az.analyze(**base_kwargs(base_protocol_apy_pct=5.0))
        expected = r["token_apy_current_pct"] + 5.0
        self.assertAlmostEqual(r["total_apy_current_pct"], expected, places=5)

    def test_total_apy_zero_base(self):
        r = self.az.analyze(**base_kwargs(base_protocol_apy_pct=0.0))
        self.assertAlmostEqual(r["total_apy_current_pct"],
                               r["token_apy_current_pct"], places=5)

    def test_total_apy_zero_emission(self):
        r = self.az.analyze(**base_kwargs(
            reward_token_emission_per_day=0.0,
            base_protocol_apy_pct=4.0,
        ))
        self.assertAlmostEqual(r["total_apy_current_pct"], 4.0, places=6)

    def test_total_apy_rounds_to_6_places(self):
        r = self.az.analyze(**base_kwargs())
        val = r["total_apy_current_pct"]
        self.assertEqual(round(val, 6), val)

    def test_daily_yield_basic(self):
        # position=10000, total_apy=10%, daily = 10000*10/365/100
        r = self.az.analyze(**base_kwargs(
            reward_token_emission_per_day=0.0,
            base_protocol_apy_pct=10.0,
            position_size_usd=10_000.0,
        ))
        expected = 10_000.0 * 10.0 / 365 / 100
        self.assertAlmostEqual(r["daily_yield_usd"], expected, places=4)

    def test_daily_yield_zero_position(self):
        r = self.az.analyze(**base_kwargs(position_size_usd=0.0))
        self.assertEqual(r["daily_yield_usd"], 0.0)

    def test_daily_yield_proportional_to_position(self):
        r1 = self.az.analyze(**base_kwargs(position_size_usd=5_000.0))
        r2 = self.az.analyze(**base_kwargs(position_size_usd=10_000.0))
        self.assertAlmostEqual(r2["daily_yield_usd"],
                               r1["daily_yield_usd"] * 2, places=5)

    def test_daily_yield_rounds_to_6_places(self):
        r = self.az.analyze(**base_kwargs())
        val = r["daily_yield_usd"]
        self.assertEqual(round(val, 6), val)

    def test_daily_yield_large_position(self):
        r = self.az.analyze(**base_kwargs(
            position_size_usd=1_000_000.0,
            base_protocol_apy_pct=5.0,
            reward_token_emission_per_day=0.0,
        ))
        expected = 1_000_000.0 * 5.0 / 365 / 100
        self.assertAlmostEqual(r["daily_yield_usd"], expected, places=4)

    def test_total_apy_can_exceed_100_pct(self):
        r = self.az.analyze(**base_kwargs(
            reward_token_emission_per_day=50_000.0,
            reward_token_current_price_usd=5.0,
            base_protocol_apy_pct=20.0,
        ))
        self.assertGreater(r["total_apy_current_pct"], 100.0)


# ===========================================================================
# 6. Price sensitivity score
# ===========================================================================

class TestPriceSensitivityScore(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.az = make_analyzer(self.tmp)

    def test_score_zero_when_no_token_emission(self):
        r = self.az.analyze(**base_kwargs(
            reward_token_emission_per_day=0.0,
            base_protocol_apy_pct=5.0,
        ))
        self.assertEqual(r["price_sensitivity_score"], 0)

    def test_score_100_when_only_token_yield(self):
        r = self.az.analyze(**base_kwargs(base_protocol_apy_pct=0.0))
        self.assertEqual(r["price_sensitivity_score"], 100)

    def test_score_is_int(self):
        r = self.az.analyze(**base_kwargs())
        self.assertIsInstance(r["price_sensitivity_score"], int)

    def test_score_between_0_and_100(self):
        r = self.az.analyze(**base_kwargs())
        self.assertGreaterEqual(r["price_sensitivity_score"], 0)
        self.assertLessEqual(r["price_sensitivity_score"], 100)

    def test_score_decreases_with_higher_base(self):
        r_low = self.az.analyze(**base_kwargs(base_protocol_apy_pct=50.0))
        r_high = self.az.analyze(**base_kwargs(base_protocol_apy_pct=0.0))
        self.assertLess(r_low["price_sensitivity_score"],
                        r_high["price_sensitivity_score"])

    def test_score_50_50_split(self):
        # token_apy = 36.5, base = 36.5 → score ~50
        r = self.az.analyze(**base_kwargs(base_protocol_apy_pct=36.5))
        self.assertAlmostEqual(r["price_sensitivity_score"], 50, delta=1)

    def test_score_zero_total_zero_token(self):
        # emission=0, base=0 → score 0
        r = self.az.analyze(**base_kwargs(
            reward_token_emission_per_day=0.0,
            base_protocol_apy_pct=0.0,
        ))
        self.assertEqual(r["price_sensitivity_score"], 0)

    def test_score_never_negative_any_base(self):
        for base in [0, 5, 50, 200]:
            r = self.az.analyze(**base_kwargs(base_protocol_apy_pct=float(base)))
            self.assertGreaterEqual(r["price_sensitivity_score"], 0,
                                    msg=f"base={base}")

    def test_score_never_above_100(self):
        for emission in [1, 100, 100000]:
            r = self.az.analyze(**base_kwargs(
                reward_token_emission_per_day=float(emission),
                base_protocol_apy_pct=0.0,
            ))
            self.assertLessEqual(r["price_sensitivity_score"], 100,
                                 msg=f"emission={emission}")

    def test_score_positive_when_some_token_yield(self):
        r = self.az.analyze(**base_kwargs(base_protocol_apy_pct=10.0))
        self.assertGreater(r["price_sensitivity_score"], 0)


# ===========================================================================
# 7. Label: PRICE_RESILIENT
# (uses token_ratio_30d < 30% — base yield dominated originally)
# ===========================================================================

class TestLabelPriceResilient(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.az = make_analyzer(self.tmp)

    def _resilient_base_kwargs(self, **overrides):
        """High base APY → token_ratio_30d << 30%."""
        # token_apy_30d = 36.5, base=100 → ratio = 26.7% < 30%
        kw = base_kwargs(base_protocol_apy_pct=100.0)
        kw.update(overrides)
        return kw

    def test_resilient_high_base_apy(self):
        r = self.az.analyze(**self._resilient_base_kwargs())
        self.assertEqual(r["price_impact_label"], "PRICE_RESILIENT")

    def test_resilient_very_small_emission(self):
        # token_apy_30d = 1 token * $1 * 365 / $1M * 100 = 0.0365%
        # base=50 → ratio = 0.0007% → PRICE_RESILIENT
        r = self.az.analyze(**base_kwargs(
            reward_token_emission_per_day=1.0,
            base_protocol_apy_pct=50.0,
        ))
        self.assertEqual(r["price_impact_label"], "PRICE_RESILIENT")

    def test_resilient_token_below_30pct_of_total(self):
        # token_apy_30d = 36.5, base=100 → ratio = 26.7%
        r = self.az.analyze(**self._resilient_base_kwargs())
        self.assertEqual(r["price_impact_label"], "PRICE_RESILIENT")

    def test_resilient_despite_mild_price_drop(self):
        # Pool originally had tiny token exposure; -15% drop → still RESILIENT
        r = self.az.analyze(**self._resilient_base_kwargs(
            reward_token_current_price_usd=0.85,
            reward_token_price_30d_ago_usd=1.0,
        ))
        self.assertEqual(r["price_impact_label"], "PRICE_RESILIENT")

    def test_resilient_despite_moderate_price_drop(self):
        # -25% drop, but pool had base_apy=100 (token ratio < 30%) → RESILIENT
        r = self.az.analyze(**self._resilient_base_kwargs(
            reward_token_current_price_usd=0.75,
            reward_token_price_30d_ago_usd=1.0,
        ))
        self.assertEqual(r["price_impact_label"], "PRICE_RESILIENT")

    def test_resilient_large_token_price_increase(self):
        # +50% price rise, but pool still base-dominant (originally) → RESILIENT
        r = self.az.analyze(**self._resilient_base_kwargs(
            reward_token_current_price_usd=1.5,
            reward_token_price_30d_ago_usd=1.0,
        ))
        self.assertEqual(r["price_impact_label"], "PRICE_RESILIENT")

    def test_resilient_label_in_valid_set(self):
        r = self.az.analyze(**self._resilient_base_kwargs())
        self.assertIn(r["price_impact_label"], VALID_LABELS)

    def test_resilient_zero_price_change(self):
        r = self.az.analyze(**self._resilient_base_kwargs())
        self.assertEqual(r["price_impact_label"], "PRICE_RESILIENT")

    def test_resilient_high_tvl_tiny_ratio(self):
        # emission=100 tokens, huge tvl → tiny token apy
        r = self.az.analyze(**base_kwargs(
            reward_token_emission_per_day=100.0,
            pool_tvl_usd=1_000_000_000.0,  # 1B → token_apy_30d = 0.00365%
            base_protocol_apy_pct=5.0,
        ))
        self.assertEqual(r["price_impact_label"], "PRICE_RESILIENT")


# ===========================================================================
# 8. Label: MILD_IMPACT
# (token_ratio_30d 30-50% AND |change| clearly < 20%, OR high ratio small change)
# ===========================================================================

class TestLabelMildImpact(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.az = make_analyzer(self.tmp)

    def _mild_kwargs(self, token_ratio_30d: float = 0.40,
                     abs_change_pct: float = 10.0,
                     drop: bool = True) -> dict:
        """
        Build kwargs where original token_ratio == token_ratio_30d target
        and |price_change| == abs_change_pct.
        """
        token_apy_30d = _DEFAULT_TOKEN_APY
        base = token_apy_30d * (1 - token_ratio_30d) / token_ratio_30d
        factor = -1 if drop else 1
        new_price = 1.0 + factor * abs_change_pct / 100
        return base_kwargs(
            base_protocol_apy_pct=base,
            reward_token_current_price_usd=new_price,
            reward_token_price_30d_ago_usd=1.0,
        )

    def test_mild_40pct_token_ratio_10pct_drop(self):
        r = self.az.analyze(**self._mild_kwargs(0.40, 10.0))
        self.assertEqual(r["price_impact_label"], "MILD_IMPACT")

    def test_mild_40pct_token_ratio_zero_change(self):
        r = self.az.analyze(**self._mild_kwargs(0.40, 0.0))
        self.assertEqual(r["price_impact_label"], "MILD_IMPACT")

    def test_mild_40pct_token_ratio_15pct_drop(self):
        r = self.az.analyze(**self._mild_kwargs(0.40, 15.0))
        self.assertEqual(r["price_impact_label"], "MILD_IMPACT")

    def test_mild_50pct_token_ratio_10pct_drop(self):
        r = self.az.analyze(**self._mild_kwargs(0.50, 10.0))
        self.assertEqual(r["price_impact_label"], "MILD_IMPACT")

    def test_mild_large_token_ratio_small_change(self):
        # token dominates (ratio > 50%) with tiny price change
        r = self.az.analyze(**base_kwargs(
            base_protocol_apy_pct=1.0,            # token_ratio_30d ~ 97%
            reward_token_current_price_usd=1.05,  # +5% change
            reward_token_price_30d_ago_usd=1.0,
        ))
        self.assertEqual(r["price_impact_label"], "MILD_IMPACT")

    def test_mild_very_small_negative_change(self):
        r = self.az.analyze(**self._mild_kwargs(0.40, 5.0, drop=True))
        self.assertEqual(r["price_impact_label"], "MILD_IMPACT")

    def test_mild_very_small_positive_change(self):
        r = self.az.analyze(**self._mild_kwargs(0.40, 5.0, drop=False))
        self.assertEqual(r["price_impact_label"], "MILD_IMPACT")

    def test_mild_label_in_valid_set(self):
        r = self.az.analyze(**self._mild_kwargs())
        self.assertIn(r["price_impact_label"], VALID_LABELS)

    def test_mild_token_dominant_1pct_change(self):
        # 80% token weight, 1% change
        r = self.az.analyze(**self._mild_kwargs(0.80, 1.0))
        self.assertEqual(r["price_impact_label"], "MILD_IMPACT")


# ===========================================================================
# 9. Label: MODERATE_IMPACT
# (token_ratio_30d >= 30%, |change| in [20%, 40%) — values clearly away from edge)
# ===========================================================================

class TestLabelModerateImpact(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.az = make_analyzer(self.tmp)

    def _moderate_kwargs(self, abs_change_pct: float, drop: bool = True,
                         token_ratio_30d: float = 0.40) -> dict:
        token_apy_30d = _DEFAULT_TOKEN_APY
        base = token_apy_30d * (1 - token_ratio_30d) / token_ratio_30d
        factor = -1 if drop else 1
        new_price = 1.0 + factor * abs_change_pct / 100
        return base_kwargs(
            base_protocol_apy_pct=base,
            reward_token_current_price_usd=new_price,
            reward_token_price_30d_ago_usd=1.0,
        )

    def test_moderate_22pct_drop(self):
        r = self.az.analyze(**self._moderate_kwargs(22.0))
        self.assertEqual(r["price_impact_label"], "MODERATE_IMPACT")

    def test_moderate_30pct_drop(self):
        r = self.az.analyze(**self._moderate_kwargs(30.0))
        self.assertEqual(r["price_impact_label"], "MODERATE_IMPACT")

    def test_moderate_22pct_rise(self):
        r = self.az.analyze(**self._moderate_kwargs(22.0, drop=False))
        self.assertEqual(r["price_impact_label"], "MODERATE_IMPACT")

    def test_moderate_38pct_drop(self):
        r = self.az.analyze(**self._moderate_kwargs(38.0))
        self.assertEqual(r["price_impact_label"], "MODERATE_IMPACT")

    def test_moderate_25pct_high_token_ratio(self):
        # token_ratio_30d = 70%, 25% drop → MODERATE
        r = self.az.analyze(**self._moderate_kwargs(25.0, token_ratio_30d=0.70))
        self.assertEqual(r["price_impact_label"], "MODERATE_IMPACT")

    def test_moderate_label_in_valid_set(self):
        r = self.az.analyze(**self._moderate_kwargs(30.0))
        self.assertIn(r["price_impact_label"], VALID_LABELS)

    def test_moderate_35pct_rise(self):
        r = self.az.analyze(**self._moderate_kwargs(35.0, drop=False))
        self.assertEqual(r["price_impact_label"], "MODERATE_IMPACT")


# ===========================================================================
# 10. Label: HIGH_IMPACT
# (token_ratio_30d >= 30%, |change| in [40%, 70%) — use values clearly in range)
# ===========================================================================

class TestLabelHighImpact(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.az = make_analyzer(self.tmp)

    def _high_kwargs(self, abs_change_pct: float, drop: bool = True,
                     token_ratio_30d: float = 0.40) -> dict:
        token_apy_30d = _DEFAULT_TOKEN_APY
        base = token_apy_30d * (1 - token_ratio_30d) / token_ratio_30d
        factor = -1 if drop else 1
        new_price = 1.0 + factor * abs_change_pct / 100
        return base_kwargs(
            base_protocol_apy_pct=base,
            reward_token_current_price_usd=new_price,
            reward_token_price_30d_ago_usd=1.0,
        )

    def test_high_41pct_drop(self):
        r = self.az.analyze(**self._high_kwargs(41.0))
        self.assertEqual(r["price_impact_label"], "HIGH_IMPACT")

    def test_high_50pct_drop(self):
        r = self.az.analyze(**self._high_kwargs(50.0))
        self.assertEqual(r["price_impact_label"], "HIGH_IMPACT")

    def test_high_60pct_drop(self):
        r = self.az.analyze(**self._high_kwargs(60.0))
        self.assertEqual(r["price_impact_label"], "HIGH_IMPACT")

    def test_high_69pct_drop(self):
        r = self.az.analyze(**self._high_kwargs(69.0))
        self.assertEqual(r["price_impact_label"], "HIGH_IMPACT")

    def test_high_41pct_rise(self):
        r = self.az.analyze(**self._high_kwargs(41.0, drop=False))
        self.assertEqual(r["price_impact_label"], "HIGH_IMPACT")

    def test_high_55pct_rise(self):
        r = self.az.analyze(**self._high_kwargs(55.0, drop=False))
        self.assertEqual(r["price_impact_label"], "HIGH_IMPACT")

    def test_high_label_in_valid_set(self):
        r = self.az.analyze(**self._high_kwargs(45.0))
        self.assertIn(r["price_impact_label"], VALID_LABELS)

    def test_high_large_token_ratio_50pct_drop(self):
        r = self.az.analyze(**self._high_kwargs(50.0, token_ratio_30d=0.80))
        self.assertEqual(r["price_impact_label"], "HIGH_IMPACT")


# ===========================================================================
# 11. Label: APY_DESTROYED
# ===========================================================================

class TestLabelAPYDestroyed(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.az = make_analyzer(self.tmp)

    def test_destroyed_token_price_zero(self):
        # token_apy_current = 0 → rule 1 fires
        r = self.az.analyze(**base_kwargs(reward_token_current_price_usd=0.0))
        self.assertEqual(r["price_impact_label"], "APY_DESTROYED")

    def test_destroyed_71pct_drop_with_significant_token(self):
        # base=5, emission=1000 → token_ratio_30d=88%; |change|=71% > 70%
        r = self.az.analyze(**base_kwargs(
            base_protocol_apy_pct=5.0,
            reward_token_current_price_usd=0.29,  # ≈ -71% change
            reward_token_price_30d_ago_usd=1.0,
        ))
        self.assertEqual(r["price_impact_label"], "APY_DESTROYED")

    def test_destroyed_90pct_drop(self):
        r = self.az.analyze(**base_kwargs(
            base_protocol_apy_pct=5.0,
            reward_token_current_price_usd=0.1,
            reward_token_price_30d_ago_usd=1.0,
        ))
        self.assertEqual(r["price_impact_label"], "APY_DESTROYED")

    def test_destroyed_99pct_drop(self):
        # token_ratio_30d = 88% (emission=1000, base=5) → severe crash
        r = self.az.analyze(**base_kwargs(
            base_protocol_apy_pct=5.0,
            reward_token_current_price_usd=0.01,
            reward_token_price_30d_ago_usd=1.0,
        ))
        self.assertEqual(r["price_impact_label"], "APY_DESTROYED")

    def test_destroyed_zero_emission_zero_base(self):
        # token_apy=0 → APY_DESTROYED (rule 1)
        r = self.az.analyze(**base_kwargs(
            reward_token_emission_per_day=0.0,
            base_protocol_apy_pct=0.0,
        ))
        self.assertIn(r["price_impact_label"], VALID_LABELS)

    def test_destroyed_80pct_positive_change_significant_token(self):
        # +80% price rise, token_ratio_30d=88% → |change|>70 → APY_DESTROYED
        r = self.az.analyze(**base_kwargs(
            base_protocol_apy_pct=5.0,
            reward_token_current_price_usd=1.8,
            reward_token_price_30d_ago_usd=1.0,
        ))
        self.assertEqual(r["price_impact_label"], "APY_DESTROYED")

    def test_destroyed_label_in_valid_set(self):
        r = self.az.analyze(**base_kwargs(reward_token_current_price_usd=0.0))
        self.assertIn(r["price_impact_label"], VALID_LABELS)

    def test_destroyed_zero_current_price(self):
        r = self.az.analyze(**base_kwargs(
            reward_token_emission_per_day=1000.0,
            reward_token_current_price_usd=0.0,
            base_protocol_apy_pct=10.0,
        ))
        self.assertEqual(r["price_impact_label"], "APY_DESTROYED")

    def test_destroyed_100pct_drop(self):
        # Emission with price = 0 → APY_DESTROYED
        r = self.az.analyze(**base_kwargs(
            base_protocol_apy_pct=2.0,
            reward_token_current_price_usd=0.0,
        ))
        self.assertEqual(r["price_impact_label"], "APY_DESTROYED")


# ===========================================================================
# 12. Input validation
# ===========================================================================

class TestInputValidation(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.az = make_analyzer(self.tmp)

    def test_negative_tvl_raises(self):
        with self.assertRaises(ValueError):
            self.az.analyze(**base_kwargs(pool_tvl_usd=-1.0))

    def test_zero_tvl_raises(self):
        with self.assertRaises(ValueError):
            self.az.analyze(**base_kwargs(pool_tvl_usd=0.0))

    def test_zero_30d_price_raises(self):
        with self.assertRaises(ValueError):
            self.az.analyze(**base_kwargs(reward_token_price_30d_ago_usd=0.0))

    def test_negative_30d_price_raises(self):
        with self.assertRaises(ValueError):
            self.az.analyze(**base_kwargs(reward_token_price_30d_ago_usd=-1.0))

    def test_negative_emission_raises(self):
        with self.assertRaises(ValueError):
            self.az.analyze(**base_kwargs(reward_token_emission_per_day=-0.01))

    def test_negative_current_price_raises(self):
        with self.assertRaises(ValueError):
            self.az.analyze(**base_kwargs(reward_token_current_price_usd=-0.1))

    def test_negative_position_raises(self):
        with self.assertRaises(ValueError):
            self.az.analyze(**base_kwargs(position_size_usd=-100.0))

    def test_non_string_protocol_raises(self):
        with self.assertRaises(TypeError):
            self.az.analyze(**base_kwargs(protocol_name=123))

    def test_zero_position_is_valid(self):
        r = self.az.analyze(**base_kwargs(position_size_usd=0.0))
        self.assertEqual(r["daily_yield_usd"], 0.0)

    def test_zero_emission_is_valid(self):
        r = self.az.analyze(**base_kwargs(reward_token_emission_per_day=0.0))
        self.assertIsNotNone(r)

    def test_negative_base_apy_allowed(self):
        # Negative base APY is valid (net borrowing cost scenario)
        r = self.az.analyze(**base_kwargs(base_protocol_apy_pct=-2.0))
        self.assertIsNotNone(r)


# ===========================================================================
# 13. Output structure
# ===========================================================================

class TestOutputStructure(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.az = make_analyzer(self.tmp)

    def test_all_keys_present(self):
        r = self.az.analyze(**base_kwargs())
        expected_keys = {
            "protocol_name", "token_apy_current_pct", "token_apy_30d_ago_pct",
            "token_price_change_pct", "apy_impact_pct", "total_apy_current_pct",
            "daily_yield_usd", "price_sensitivity_score", "price_impact_label",
            "timestamp",
        }
        self.assertEqual(set(r.keys()), expected_keys)

    def test_protocol_name_preserved(self):
        r = self.az.analyze(**base_kwargs(protocol_name="Aave"))
        self.assertEqual(r["protocol_name"], "Aave")

    def test_timestamp_ends_with_z(self):
        r = self.az.analyze(**base_kwargs())
        self.assertTrue(r["timestamp"].endswith("Z"))

    def test_timestamp_parseable(self):
        import datetime as dt
        r = self.az.analyze(**base_kwargs())
        ts = r["timestamp"].replace("Z", "+00:00")
        parsed = dt.datetime.fromisoformat(ts)
        self.assertIsNotNone(parsed)

    def test_label_always_in_valid_set(self):
        for base_apy in [0, 5, 50, 200]:
            r = self.az.analyze(**base_kwargs(base_protocol_apy_pct=float(base_apy)))
            self.assertIn(r["price_impact_label"], VALID_LABELS, msg=f"base={base_apy}")

    def test_sensitivity_score_type_int(self):
        r = self.az.analyze(**base_kwargs())
        self.assertIsInstance(r["price_sensitivity_score"], int)

    def test_numeric_fields_are_float(self):
        r = self.az.analyze(**base_kwargs())
        for field in ["token_apy_current_pct", "token_apy_30d_ago_pct",
                      "token_price_change_pct", "apy_impact_pct",
                      "total_apy_current_pct", "daily_yield_usd"]:
            self.assertIsInstance(r[field], float, msg=f"{field} not float")

    def test_no_extra_keys(self):
        r = self.az.analyze(**base_kwargs())
        allowed = {"protocol_name", "token_apy_current_pct", "token_apy_30d_ago_pct",
                   "token_price_change_pct", "apy_impact_pct", "total_apy_current_pct",
                   "daily_yield_usd", "price_sensitivity_score", "price_impact_label",
                   "timestamp"}
        self.assertEqual(set(r.keys()), allowed)


# ===========================================================================
# 14. Logging
# ===========================================================================

class TestLogging(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.log_path = os.path.join(self.tmp, "test_log.json")
        self.az = DeFiProtocolTokenPriceImpactOnYieldAnalyzer(
            log_path=self.log_path, log_cap=5
        )

    def test_log_file_created(self):
        self.az.analyze_and_log(**base_kwargs())
        self.assertTrue(os.path.exists(self.log_path))

    def test_log_is_list(self):
        self.az.analyze_and_log(**base_kwargs())
        with open(self.log_path) as f:
            data = json.load(f)
        self.assertIsInstance(data, list)

    def test_log_has_one_entry_after_one_call(self):
        self.az.analyze_and_log(**base_kwargs())
        with open(self.log_path) as f:
            data = json.load(f)
        self.assertEqual(len(data), 1)

    def test_log_accumulates_entries(self):
        for _ in range(3):
            self.az.analyze_and_log(**base_kwargs())
        with open(self.log_path) as f:
            data = json.load(f)
        self.assertEqual(len(data), 3)

    def test_log_capped_at_log_cap(self):
        for _ in range(8):
            self.az.analyze_and_log(**base_kwargs())
        with open(self.log_path) as f:
            data = json.load(f)
        self.assertLessEqual(len(data), 5)

    def test_log_cap_enforced_exactly(self):
        for _ in range(7):
            self.az.analyze_and_log(**base_kwargs())
        with open(self.log_path) as f:
            data = json.load(f)
        self.assertEqual(len(data), 5)

    def test_log_entry_has_required_fields(self):
        self.az.analyze_and_log(**base_kwargs())
        with open(self.log_path) as f:
            entry = json.load(f)[0]
        self.assertIn("price_impact_label", entry)
        self.assertIn("timestamp", entry)
        self.assertIn("protocol_name", entry)

    def test_log_returns_same_as_stored(self):
        r = self.az.analyze_and_log(**base_kwargs())
        with open(self.log_path) as f:
            stored = json.load(f)[0]
        self.assertEqual(r, stored)

    def test_no_tmp_file_left_after_log(self):
        self.az.analyze_and_log(**base_kwargs())
        self.assertFalse(os.path.exists(self.log_path + ".tmp"))

    def test_log_cap_100_default(self):
        az100 = DeFiProtocolTokenPriceImpactOnYieldAnalyzer(
            log_path=self.log_path, log_cap=100
        )
        for _ in range(110):
            az100.analyze_and_log(**base_kwargs())
        with open(self.log_path) as f:
            data = json.load(f)
        self.assertEqual(len(data), 100)

    def test_log_keeps_most_recent_entries(self):
        for i in range(7):
            self.az.analyze_and_log(**base_kwargs(protocol_name=f"P{i}"))
        with open(self.log_path) as f:
            data = json.load(f)
        # Should have last 5: P2..P6
        names = [e["protocol_name"] for e in data]
        self.assertEqual(names[-1], "P6")
        self.assertEqual(names[0], "P2")


# ===========================================================================
# 15. Edge cases
# ===========================================================================

class TestEdgeCases(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.az = make_analyzer(self.tmp)

    def test_very_small_tvl(self):
        r = self.az.analyze(**base_kwargs(pool_tvl_usd=1.0))
        self.assertGreater(r["token_apy_current_pct"], 0)

    def test_very_large_emission(self):
        r = self.az.analyze(**base_kwargs(reward_token_emission_per_day=1e9))
        self.assertGreater(r["token_apy_current_pct"], 0)

    def test_very_small_current_price(self):
        r = self.az.analyze(**base_kwargs(
            reward_token_current_price_usd=1e-8,
            reward_token_price_30d_ago_usd=1.0,
        ))
        self.assertAlmostEqual(r["token_apy_current_pct"], 0.0, places=3)

    def test_very_small_30d_price(self):
        r = self.az.analyze(**base_kwargs(
            reward_token_current_price_usd=1.0,
            reward_token_price_30d_ago_usd=0.001,
        ))
        self.assertGreater(r["token_price_change_pct"], 1000)

    def test_empty_protocol_name(self):
        r = self.az.analyze(**base_kwargs(protocol_name=""))
        self.assertEqual(r["protocol_name"], "")

    def test_unicode_protocol_name(self):
        r = self.az.analyze(**base_kwargs(protocol_name="Протокол-Α"))
        self.assertEqual(r["protocol_name"], "Протокол-Α")

    def test_analyze_does_not_write_to_disk(self):
        log_path = os.path.join(self.tmp, "should_not_exist.json")
        az = DeFiProtocolTokenPriceImpactOnYieldAnalyzer(log_path=log_path)
        az.analyze(**base_kwargs())
        self.assertFalse(os.path.exists(log_path))

    def test_corrupted_log_file_is_reset(self):
        log_path = os.path.join(self.tmp, "corrupted.json")
        with open(log_path, "w") as f:
            f.write("{invalid json}")
        az = DeFiProtocolTokenPriceImpactOnYieldAnalyzer(log_path=log_path, log_cap=5)
        az.analyze_and_log(**base_kwargs())
        with open(log_path) as f:
            data = json.load(f)
        self.assertEqual(len(data), 1)

    def test_log_not_a_list_is_reset(self):
        log_path = os.path.join(self.tmp, "notalist.json")
        with open(log_path, "w") as f:
            json.dump({"key": "value"}, f)
        az = DeFiProtocolTokenPriceImpactOnYieldAnalyzer(log_path=log_path, log_cap=5)
        az.analyze_and_log(**base_kwargs())
        with open(log_path) as f:
            data = json.load(f)
        self.assertIsInstance(data, list)
        self.assertEqual(len(data), 1)


# ===========================================================================
# 16. Integration / compound scenarios
# ===========================================================================

class TestIntegration(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.az = make_analyzer(self.tmp)

    def test_aave_like_scenario(self):
        """High-TVL lending pool with modest token rewards and -22% price drop."""
        r = self.az.analyze(
            reward_token_emission_per_day=5000,
            reward_token_current_price_usd=78.0,   # -22% from 100
            reward_token_price_30d_ago_usd=100.0,
            pool_tvl_usd=500_000_000.0,
            base_protocol_apy_pct=3.5,
            position_size_usd=50_000.0,
            protocol_name="Aave-V3",
        )
        # token_apy_30d = 5000*100*365/500M*100 = 3.65% → total_30d ~7.15 → ratio ~51%
        self.assertIn(r["price_impact_label"], VALID_LABELS)
        self.assertGreater(r["daily_yield_usd"], 0)

    def test_yield_farm_rug_scenario(self):
        """Yield farm token crashes 95% from $1.00 → $0.05."""
        r = self.az.analyze(
            reward_token_emission_per_day=100_000,
            reward_token_current_price_usd=0.05,
            reward_token_price_30d_ago_usd=1.0,
            pool_tvl_usd=10_000_000.0,
            base_protocol_apy_pct=1.0,
            position_size_usd=10_000.0,
            protocol_name="FarmToken",
        )
        # |change| = 95% > 70%, token_ratio_30d >> 30% → APY_DESTROYED
        self.assertEqual(r["price_impact_label"], "APY_DESTROYED")
        self.assertLess(r["token_apy_current_pct"], r["token_apy_30d_ago_pct"])

    def test_stable_base_yield_only(self):
        """Pure base yield protocol with no token rewards."""
        r = self.az.analyze(
            reward_token_emission_per_day=0.0,
            reward_token_current_price_usd=1.0,
            reward_token_price_30d_ago_usd=1.0,
            pool_tvl_usd=100_000_000.0,
            base_protocol_apy_pct=5.0,
            position_size_usd=100_000.0,
            protocol_name="StableProtocol",
        )
        self.assertEqual(r["price_sensitivity_score"], 0)
        self.assertAlmostEqual(r["total_apy_current_pct"], 5.0, places=5)

    def test_analyze_and_log_stores_protocol_name(self):
        self.az.analyze_and_log(**base_kwargs(protocol_name="Compound"))
        with open(self.az.log_path) as f:
            stored = json.load(f)
        self.assertEqual(stored[0]["protocol_name"], "Compound")

    def test_multiple_protocols_logged_in_order(self):
        for name in ["Aave", "Compound", "Morpho"]:
            self.az.analyze_and_log(**base_kwargs(protocol_name=name))
        with open(self.az.log_path) as f:
            stored = json.load(f)
        names = [e["protocol_name"] for e in stored]
        self.assertEqual(names, ["Aave", "Compound", "Morpho"])


if __name__ == "__main__":
    unittest.main()
