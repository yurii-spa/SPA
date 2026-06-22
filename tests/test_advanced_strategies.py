"""
tests/test_advanced_strategies.py — S71–S77 advanced DeFi yield strategies (66 tests)

Covers:
  S71 Delta-Neutral Yield (Ethena)
  S72 Basis Trade / Funding Rate Arb
  S73 Leverage Loop / Recursive Lending
  S74 RWA Yield
  S75 Pendle Yield Tokenisation Max
  S76 Concentrated Liquidity Stablecoin LP
  S77 Points + Yield Farming

Each strategy: instantiation, allocate() weights sum to 1.0, IS_ADVISORY flag,
RISK_TIER, EXPECTED_APY_PCT, CAVEAT, regime switching (S72/S74/S75/S76),
S73 effective_apy calculation, new protocol registrations in adapter_status.json.
"""
import json
import pathlib
import unittest

# ─── Import all 7 strategies ──────────────────────────────────────────────────

from spa_core.strategies.s71_delta_neutral import (
    S71DeltaNeutral,
)
from spa_core.strategies.s72_basis_trade import (
    S72BasisTrade, ALLOC_POSITIVE, ALLOC_NEGATIVE,
)
from spa_core.strategies.s73_leverage_loop import (
    S73LeverageLoop, LEVERAGE_RATIO, LIQUIDATION_THRESHOLD,
    STAKING_APY_DEFAULT, BORROW_RATE_DEFAULT,
)
from spa_core.strategies.s74_rwa_yield import (
    S74RWAYield, ALLOC_HIGH_MAPLE, ALLOC_NORMAL_MAPLE, MAPLE_HIGH_THRESHOLD,
)
from spa_core.strategies.s75_pendle_yield_max import (
    S75PendleYieldMax, ALLOC_HIGH_RATE, ALLOC_NORMAL_RATE, HIGH_RATE_THRESHOLD,
)
from spa_core.strategies.s76_concentrated_lp import (
    S76ConcentratedLP, ALLOC_LP_ACTIVE,
)
from spa_core.strategies.s77_points_farming import (
    S77PointsFarming, POINTS_APY_PREMIUM_PCT,
)
from spa_core.strategies.strategy_registry import REGISTRY

# ─── Helpers ─────────────────────────────────────────────────────────────────

def _wsum(weights: dict) -> float:
    """Sum all weight values, rounded to 6 decimal places."""
    return round(sum(weights.values()), 6)


DATA_DIR = pathlib.Path(__file__).parent.parent / "data"


# ═══════════════════════════════════════════════════════════════════════════════
# S71 — Delta-Neutral Yield
# ═══════════════════════════════════════════════════════════════════════════════

class TestS71DeltaNeutral(unittest.TestCase):
    def setUp(self):
        self.s = S71DeltaNeutral()

    # Identity
    def test_strategy_id(self):
        self.assertEqual(self.s.strategy_id, "S71")

    def test_risk_tier_class_attr(self):
        self.assertEqual(S71DeltaNeutral.RISK_TIER, "T2")

    def test_is_advisory_true(self):
        self.assertTrue(S71DeltaNeutral.IS_ADVISORY)

    def test_expected_apy_defined(self):
        self.assertIsInstance(S71DeltaNeutral.EXPECTED_APY_PCT, float)
        self.assertGreater(S71DeltaNeutral.EXPECTED_APY_PCT, 0.0)

    def test_caveat_non_empty(self):
        self.assertIsInstance(S71DeltaNeutral.CAVEAT, str)
        self.assertGreater(len(S71DeltaNeutral.CAVEAT), 10)

    # allocate()
    def test_allocate_returns_dict(self):
        result = self.s.allocate({})
        self.assertIsInstance(result, dict)

    def test_allocate_weights_sum_to_one(self):
        result = self.s.allocate({})
        self.assertAlmostEqual(_wsum(result), 1.0, places=6)

    def test_allocate_has_ethena_susde(self):
        result = self.s.allocate({})
        self.assertIn("ethena_susde", result)

    def test_allocate_has_spark_susds(self):
        result = self.s.allocate({})
        self.assertIn("spark_susds", result)

    def test_allocate_has_cash(self):
        result = self.s.allocate({})
        self.assertIn("cash", result)

    def test_allocate_static_ignores_apy_data(self):
        r1 = self.s.allocate({})
        r2 = self.s.allocate({"ethena_susde": 5.0, "funding_rate_regime": "negative"})
        self.assertEqual(r1, r2)

    def test_allocate_all_weights_non_negative(self):
        for w in self.s.allocate({}).values():
            self.assertGreaterEqual(w, 0.0)

    # compute_weighted_apy
    def test_weighted_apy_positive(self):
        apy = self.s.compute_weighted_apy()
        self.assertGreater(apy, 0.0)

    def test_weighted_apy_close_to_expected(self):
        # 0.60*12 + 0.25*4.2 + 0.15*0 = 8.25
        self.assertAlmostEqual(self.s.compute_weighted_apy(), 8.25, places=2)

    # get_info
    def test_get_info_keys(self):
        info = self.s.get_info()
        for key in ("strategy_id", "risk_tier", "is_advisory", "caveat", "allocation"):
            self.assertIn(key, info)

    # registry
    def test_registered_in_registry(self):
        meta = REGISTRY.get("S71")
        self.assertIsNotNone(meta, "S71 should be registered")

    def test_registry_tier(self):
        meta = REGISTRY.get("S71")
        self.assertEqual(meta.risk_tier, "T2")


# ═══════════════════════════════════════════════════════════════════════════════
# S72 — Basis Trade
# ═══════════════════════════════════════════════════════════════════════════════

class TestS72BasisTrade(unittest.TestCase):
    def setUp(self):
        self.s = S72BasisTrade()

    # Identity
    def test_strategy_id(self):
        self.assertEqual(self.s.strategy_id, "S72")

    def test_risk_tier_class_attr(self):
        self.assertEqual(S72BasisTrade.RISK_TIER, "T2")

    def test_is_advisory_true(self):
        self.assertTrue(S72BasisTrade.IS_ADVISORY)

    def test_expected_apy_defined(self):
        self.assertIsInstance(S72BasisTrade.EXPECTED_APY_PCT, float)

    def test_caveat_non_empty(self):
        self.assertGreater(len(S72BasisTrade.CAVEAT), 10)

    # allocate() — positive regime (default)
    def test_allocate_positive_sums_to_one(self):
        result = self.s.allocate({})
        self.assertAlmostEqual(_wsum(result), 1.0, places=6)

    def test_allocate_positive_has_ethena(self):
        result = self.s.allocate({"funding_rate_regime": "positive"})
        self.assertIn("ethena_susde", result)
        self.assertGreater(result["ethena_susde"], 0)

    def test_allocate_positive_default(self):
        # No key → defaults to positive regime
        result = self.s.allocate({})
        self.assertEqual(result, dict(ALLOC_POSITIVE))

    # allocate() — negative regime
    def test_allocate_negative_sums_to_one(self):
        result = self.s.allocate({"funding_rate_regime": "negative"})
        self.assertAlmostEqual(_wsum(result), 1.0, places=6)

    def test_allocate_negative_no_ethena(self):
        result = self.s.allocate({"funding_rate_regime": "negative"})
        self.assertNotIn("ethena_susde", result)

    def test_allocate_neutral_treated_as_negative(self):
        result = self.s.allocate({"funding_rate_regime": "neutral"})
        self.assertEqual(result, dict(ALLOC_NEGATIVE))

    # regime switching
    def test_regime_positive(self):
        self.assertEqual(self.s.current_regime({}), "positive")

    def test_regime_negative(self):
        self.assertEqual(
            self.s.current_regime({"funding_rate_regime": "negative"}), "negative"
        )

    # weighted APY
    def test_weighted_apy_positive_regime(self):
        apy = self.s.compute_weighted_apy({"funding_rate_regime": "positive"})
        self.assertGreater(apy, 0.0)

    def test_weighted_apy_negative_lower_than_positive(self):
        apy_pos = self.s.compute_weighted_apy({"funding_rate_regime": "positive"})
        apy_neg = self.s.compute_weighted_apy({"funding_rate_regime": "negative"})
        self.assertGreater(apy_pos, apy_neg)

    # registry
    def test_registered(self):
        self.assertIsNotNone(REGISTRY.get("S72"))


# ═══════════════════════════════════════════════════════════════════════════════
# S73 — Leverage Loop
# ═══════════════════════════════════════════════════════════════════════════════

class TestS73LeverageLoop(unittest.TestCase):
    def setUp(self):
        self.s = S73LeverageLoop()

    # Identity
    def test_strategy_id(self):
        self.assertEqual(self.s.strategy_id, "S73")

    def test_risk_tier_t3(self):
        self.assertEqual(S73LeverageLoop.RISK_TIER, "T3")

    def test_is_advisory_true(self):
        self.assertTrue(S73LeverageLoop.IS_ADVISORY)

    def test_expected_apy_defined(self):
        self.assertIsInstance(S73LeverageLoop.EXPECTED_APY_PCT, float)

    def test_caveat_non_empty(self):
        self.assertGreater(len(S73LeverageLoop.CAVEAT), 10)

    # class constants
    def test_leverage_ratio_conservative(self):
        self.assertEqual(LEVERAGE_RATIO, 2.0)

    def test_liquidation_threshold(self):
        self.assertAlmostEqual(LIQUIDATION_THRESHOLD, 0.825, places=3)

    # allocate()
    def test_allocate_sums_to_one(self):
        result = self.s.allocate({})
        self.assertAlmostEqual(_wsum(result), 1.0, places=6)

    def test_allocate_has_wsteth(self):
        result = self.s.allocate({})
        self.assertIn("aave_v3_wsteth", result)

    def test_allocate_has_cash(self):
        result = self.s.allocate({})
        self.assertIn("cash", result)

    def test_allocate_cash_at_least_15pct(self):
        result = self.s.allocate({})
        self.assertGreaterEqual(result["cash"], 0.15)

    # effective_apy
    def test_effective_apy_formula(self):
        # staking*leverage - borrow*(leverage-1)
        apy = self.s.effective_apy(3.5, 1.5)
        expected = 3.5 * 2.0 - 1.5 * (2.0 - 1.0)
        self.assertAlmostEqual(apy, expected, places=6)

    def test_effective_apy_default(self):
        apy = self.s.effective_apy(STAKING_APY_DEFAULT, BORROW_RATE_DEFAULT)
        self.assertAlmostEqual(apy, 5.5, places=2)

    def test_effective_apy_higher_borrow_reduces_net(self):
        apy_low  = self.s.effective_apy(3.5, 1.0)
        apy_high = self.s.effective_apy(3.5, 3.0)
        self.assertGreater(apy_low, apy_high)

    def test_effective_apy_can_be_negative(self):
        # high borrow rate can produce negative net
        apy = self.s.effective_apy(1.0, 5.0)
        self.assertLess(apy, 0.0)

    # eligibility
    def test_eligible_100k(self):
        self.assertTrue(self.s.is_eligible(capital_usd=100_000.0))

    def test_not_eligible_10k(self):
        self.assertFalse(self.s.is_eligible(capital_usd=10_000.0))

    # registry
    def test_registered(self):
        self.assertIsNotNone(REGISTRY.get("S73"))

    def test_registry_tier_t3(self):
        meta = REGISTRY.get("S73")
        self.assertEqual(meta.risk_tier, "T3")


# ═══════════════════════════════════════════════════════════════════════════════
# S74 — RWA Yield
# ═══════════════════════════════════════════════════════════════════════════════

class TestS74RWAYield(unittest.TestCase):
    def setUp(self):
        self.s = S74RWAYield()

    # Identity
    def test_strategy_id(self):
        self.assertEqual(self.s.strategy_id, "S74")

    def test_risk_tier_t2(self):
        self.assertEqual(S74RWAYield.RISK_TIER, "T2")

    def test_is_advisory_true(self):
        self.assertTrue(S74RWAYield.IS_ADVISORY)

    def test_expected_apy_defined(self):
        self.assertIsInstance(S74RWAYield.EXPECTED_APY_PCT, float)

    def test_caveat_non_empty(self):
        self.assertGreater(len(S74RWAYield.CAVEAT), 10)

    # allocate() — high-maple
    def test_allocate_high_maple_sums_to_one(self):
        result = self.s.allocate({"maple": 8.5})
        self.assertAlmostEqual(_wsum(result), 1.0, places=6)

    def test_allocate_high_maple_heavy_maple(self):
        result = self.s.allocate({"maple": 8.5})
        self.assertEqual(result, dict(ALLOC_HIGH_MAPLE))

    def test_allocate_normal_maple_sums_to_one(self):
        result = self.s.allocate({"maple": 5.0})
        self.assertAlmostEqual(_wsum(result), 1.0, places=6)

    def test_allocate_normal_maple_heavy_ondo(self):
        result = self.s.allocate({"maple": 5.0})
        self.assertEqual(result, dict(ALLOC_NORMAL_MAPLE))

    def test_allocate_default_uses_fallback(self):
        # fallback maple=6.5 ≤ 7.0 → normal regime
        result = self.s.allocate({})
        self.assertEqual(result, dict(ALLOC_NORMAL_MAPLE))

    # regime detection
    def test_regime_high_maple(self):
        self.assertEqual(self.s.current_regime({"maple": 7.5}), "high_maple")

    def test_regime_normal_maple(self):
        self.assertEqual(self.s.current_regime({"maple": 7.0}), "normal_maple")

    def test_maple_threshold(self):
        self.assertEqual(MAPLE_HIGH_THRESHOLD, 7.0)

    # APY
    def test_weighted_apy_high_maple_greater(self):
        apy_high   = self.s.compute_weighted_apy({"maple": 9.0})
        apy_normal = self.s.compute_weighted_apy({"maple": 5.0})
        self.assertGreater(apy_high, apy_normal)

    # registry
    def test_registered(self):
        self.assertIsNotNone(REGISTRY.get("S74"))


# ═══════════════════════════════════════════════════════════════════════════════
# S75 — Pendle Yield Max
# ═══════════════════════════════════════════════════════════════════════════════

class TestS75PendleYieldMax(unittest.TestCase):
    def setUp(self):
        self.s = S75PendleYieldMax()

    # Identity
    def test_strategy_id(self):
        self.assertEqual(self.s.strategy_id, "S75")

    def test_risk_tier_t2(self):
        self.assertEqual(S75PendleYieldMax.RISK_TIER, "T2")

    def test_is_advisory_true(self):
        self.assertTrue(S75PendleYieldMax.IS_ADVISORY)

    def test_expected_apy_defined(self):
        self.assertIsInstance(S75PendleYieldMax.EXPECTED_APY_PCT, float)

    def test_caveat_non_empty(self):
        self.assertGreater(len(S75PendleYieldMax.CAVEAT), 10)

    # allocate() — high-rate (aave > 0.06)
    def test_allocate_high_rate_sums_to_one(self):
        result = self.s.allocate({"aave_v3": 0.08})
        self.assertAlmostEqual(_wsum(result), 1.0, places=6)

    def test_allocate_high_rate_has_yt(self):
        result = self.s.allocate({"aave_v3": 0.08})
        self.assertIn("pendle_yt_susde", result)
        self.assertGreater(result["pendle_yt_susde"], 0)

    def test_allocate_high_rate_matches_alloc(self):
        result = self.s.allocate({"aave_v3": 0.08})
        self.assertEqual(result, dict(ALLOC_HIGH_RATE))

    # allocate() — normal-rate (aave ≤ 0.06)
    def test_allocate_normal_rate_sums_to_one(self):
        result = self.s.allocate({"aave_v3": 0.035})
        self.assertAlmostEqual(_wsum(result), 1.0, places=6)

    def test_allocate_normal_rate_no_yt(self):
        result = self.s.allocate({"aave_v3": 0.035})
        self.assertNotIn("pendle_yt_susde", result)

    def test_allocate_normal_rate_matches_alloc(self):
        result = self.s.allocate({"aave_v3": 0.035})
        self.assertEqual(result, dict(ALLOC_NORMAL_RATE))

    def test_allocate_default_normal_rate(self):
        # fallback aave_v3 = 0.035 ≤ 0.06 → normal
        result = self.s.allocate({})
        self.assertEqual(result, dict(ALLOC_NORMAL_RATE))

    # regime
    def test_regime_high_rate(self):
        self.assertEqual(self.s.current_regime({"aave_v3": 0.08}), "high_rate")

    def test_regime_normal_rate(self):
        self.assertEqual(self.s.current_regime({"aave_v3": 0.035}), "normal_rate")

    def test_high_rate_threshold(self):
        self.assertAlmostEqual(HIGH_RATE_THRESHOLD, 0.06, places=4)

    # registry
    def test_registered(self):
        self.assertIsNotNone(REGISTRY.get("S75"))


# ═══════════════════════════════════════════════════════════════════════════════
# S76 — Concentrated LP
# ═══════════════════════════════════════════════════════════════════════════════

class TestS76ConcentratedLP(unittest.TestCase):
    def setUp(self):
        self.s = S76ConcentratedLP()

    # Identity
    def test_strategy_id(self):
        self.assertEqual(self.s.strategy_id, "S76")

    def test_risk_tier_t2(self):
        self.assertEqual(S76ConcentratedLP.RISK_TIER, "T2")

    def test_is_advisory_true(self):
        self.assertTrue(S76ConcentratedLP.IS_ADVISORY)

    def test_expected_apy_defined(self):
        self.assertIsInstance(S76ConcentratedLP.EXPECTED_APY_PCT, float)

    def test_caveat_non_empty(self):
        self.assertGreater(len(S76ConcentratedLP.CAVEAT), 10)

    # allocate() — LP active
    def test_allocate_lp_active_sums_to_one(self):
        result = self.s.allocate({"aerodrome_usdc_lp": 0.09})
        self.assertAlmostEqual(_wsum(result), 1.0, places=6)

    def test_allocate_lp_active_has_aerodrome(self):
        result = self.s.allocate({"aerodrome_usdc_lp": 0.09})
        self.assertIn("aerodrome_usdc_lp", result)
        self.assertGreater(result["aerodrome_usdc_lp"], 0)

    def test_allocate_lp_active_matches_alloc(self):
        result = self.s.allocate({"aerodrome_usdc_lp": 0.09})
        self.assertEqual(result, dict(ALLOC_LP_ACTIVE))

    # allocate() — LP off
    def test_allocate_lp_off_sums_to_one(self):
        result = self.s.allocate({"aerodrome_usdc_lp": 0.03})
        self.assertAlmostEqual(_wsum(result), 1.0, places=6)

    def test_allocate_lp_off_no_aerodrome(self):
        result = self.s.allocate({"aerodrome_usdc_lp": 0.03})
        self.assertNotIn("aerodrome_usdc_lp", result)

    def test_allocate_default_lp_active(self):
        # fallback = 0.085 > 0.06 → LP active
        result = self.s.allocate({})
        self.assertEqual(result, dict(ALLOC_LP_ACTIVE))

    # regime
    def test_regime_lp_active(self):
        self.assertEqual(self.s.current_regime({"aerodrome_usdc_lp": 0.09}), "lp_active")

    def test_regime_lp_off(self):
        self.assertEqual(self.s.current_regime({"aerodrome_usdc_lp": 0.03}), "lp_off")

    # registry
    def test_registered(self):
        self.assertIsNotNone(REGISTRY.get("S76"))


# ═══════════════════════════════════════════════════════════════════════════════
# S77 — Points Farming
# ═══════════════════════════════════════════════════════════════════════════════

class TestS77PointsFarming(unittest.TestCase):
    def setUp(self):
        self.s = S77PointsFarming()

    # Identity
    def test_strategy_id(self):
        self.assertEqual(self.s.strategy_id, "S77")

    def test_risk_tier_t3(self):
        self.assertEqual(S77PointsFarming.RISK_TIER, "T3")

    def test_is_advisory_true(self):
        self.assertTrue(S77PointsFarming.IS_ADVISORY)

    def test_expected_apy_defined(self):
        self.assertIsInstance(S77PointsFarming.EXPECTED_APY_PCT, float)

    def test_caveat_non_empty(self):
        self.assertGreater(len(S77PointsFarming.CAVEAT), 10)

    # allocate()
    def test_allocate_sums_to_one(self):
        result = self.s.allocate({})
        self.assertAlmostEqual(_wsum(result), 1.0, places=6)

    def test_allocate_has_morpho(self):
        result = self.s.allocate({})
        self.assertIn("morpho_steakhouse", result)

    def test_allocate_has_pendle_yt(self):
        result = self.s.allocate({})
        self.assertIn("pendle_yt_susde", result)

    def test_allocate_static(self):
        r1 = self.s.allocate({})
        r2 = self.s.allocate({"morpho_steakhouse": 3.0})
        self.assertEqual(r1, r2)

    # points premium
    def test_points_premium_constant(self):
        self.assertGreater(POINTS_APY_PREMIUM_PCT, 0.0)

    def test_points_adjusted_apy_greater_than_base(self):
        base   = self.s.compute_weighted_apy()
        adj    = self.s.compute_points_adjusted_apy()
        self.assertGreater(adj, base)

    def test_points_adjusted_apy_custom_premium(self):
        base  = self.s.compute_weighted_apy()
        adj   = self.s.compute_points_adjusted_apy(points_premium_pct=5.0)
        self.assertAlmostEqual(adj, base + 5.0, places=4)

    def test_points_adjusted_zero_premium(self):
        base  = self.s.compute_weighted_apy()
        adj   = self.s.compute_points_adjusted_apy(points_premium_pct=0.0)
        self.assertAlmostEqual(adj, base, places=6)

    def test_active_campaigns_dict(self):
        campaigns = self.s.active_campaigns()
        self.assertIsInstance(campaigns, dict)
        self.assertIn("morpho_steakhouse", campaigns)

    # registry
    def test_registered(self):
        self.assertIsNotNone(REGISTRY.get("S77"))

    def test_registry_tier_t3(self):
        meta = REGISTRY.get("S77")
        self.assertEqual(meta.risk_tier, "T3")


# ═══════════════════════════════════════════════════════════════════════════════
# Protocol registrations in adapter_status.json
# ═══════════════════════════════════════════════════════════════════════════════

class TestNewProtocolRegistrations(unittest.TestCase):
    def setUp(self):
        adapter_path = DATA_DIR / "adapter_status.json"
        self.adapters: dict = {}
        if adapter_path.exists():
            with adapter_path.open() as f:
                data = json.load(f)
            self.adapters = data.get("adapters", {})

    def _check(self, key: str, expected_tier: int, min_apy: float) -> None:
        self.assertIn(key, self.adapters, f"{key} missing from adapter_status.json")
        entry = self.adapters[key]
        self.assertEqual(entry["tier"], expected_tier, f"{key} tier mismatch")
        self.assertGreaterEqual(entry["fallback_apy"], min_apy, f"{key} APY too low")
        self.assertTrue(entry["active"])

    def test_ethena_susde_registered(self):
        self._check("ethena_susde", 3, 5.0)

    def test_ondo_usdy_registered(self):
        self._check("ondo_usdy", 2, 4.0)

    def test_aave_v3_wsteth_registered(self):
        self._check("aave_v3_wsteth", 2, 5.0)

    def test_pendle_yt_susde_registered(self):
        self._check("pendle_yt_susde", 3, 10.0)

    def test_pendle_pt_susde_registered(self):
        self._check("pendle_pt_susde", 2, 5.0)

    def test_aerodrome_usdc_lp_registered(self):
        self._check("aerodrome_usdc_lp", 2, 5.0)

    def test_all_new_have_display_name(self):
        for key in ("ethena_susde", "ondo_usdy", "aave_v3_wsteth",
                    "pendle_yt_susde", "pendle_pt_susde", "aerodrome_usdc_lp"):
            entry = self.adapters.get(key, {})
            self.assertIn("display_name", entry, f"{key} missing display_name")
            self.assertGreater(len(entry["display_name"]), 3)


# ═══════════════════════════════════════════════════════════════════════════════
# Cross-strategy contract checks
# ═══════════════════════════════════════════════════════════════════════════════

class TestStrategyContract(unittest.TestCase):
    """Every strategy must satisfy the common contract."""

    STRATEGIES = [
        S71DeltaNeutral(),
        S72BasisTrade(),
        S73LeverageLoop(),
        S74RWAYield(),
        S75PendleYieldMax(),
        S76ConcentratedLP(),
        S77PointsFarming(),
    ]

    def test_all_have_risk_tier_class_attr(self):
        classes = [
            S71DeltaNeutral, S72BasisTrade, S73LeverageLoop, S74RWAYield,
            S75PendleYieldMax, S76ConcentratedLP, S77PointsFarming,
        ]
        for cls in classes:
            self.assertIn(cls.RISK_TIER, {"T1", "T2", "T3"},
                          f"{cls.__name__} invalid RISK_TIER")

    def test_all_have_is_advisory_true(self):
        classes = [
            S71DeltaNeutral, S72BasisTrade, S73LeverageLoop, S74RWAYield,
            S75PendleYieldMax, S76ConcentratedLP, S77PointsFarming,
        ]
        for cls in classes:
            self.assertTrue(cls.IS_ADVISORY, f"{cls.__name__} IS_ADVISORY must be True")

    def test_all_have_expected_apy_pct(self):
        classes = [
            S71DeltaNeutral, S72BasisTrade, S73LeverageLoop, S74RWAYield,
            S75PendleYieldMax, S76ConcentratedLP, S77PointsFarming,
        ]
        for cls in classes:
            self.assertIsInstance(cls.EXPECTED_APY_PCT, float,
                                  f"{cls.__name__} EXPECTED_APY_PCT must be float")
            self.assertGreater(cls.EXPECTED_APY_PCT, 0.0)

    def test_all_have_caveat(self):
        classes = [
            S71DeltaNeutral, S72BasisTrade, S73LeverageLoop, S74RWAYield,
            S75PendleYieldMax, S76ConcentratedLP, S77PointsFarming,
        ]
        for cls in classes:
            self.assertIsInstance(cls.CAVEAT, str,
                                  f"{cls.__name__} CAVEAT must be str")
            self.assertGreater(len(cls.CAVEAT), 10)

    def test_all_allocate_returns_dict(self):
        for s in self.STRATEGIES:
            result = s.allocate({})
            self.assertIsInstance(result, dict, f"{type(s).__name__} allocate() non-dict")

    def test_all_allocate_sums_to_one(self):
        for s in self.STRATEGIES:
            result = s.allocate({})
            total = round(sum(result.values()), 6)
            self.assertAlmostEqual(total, 1.0, places=5,
                                   msg=f"{type(s).__name__} weights sum {total} ≠ 1.0")

    def test_all_allocate_non_negative_weights(self):
        for s in self.STRATEGIES:
            for k, w in s.allocate({}).items():
                self.assertGreaterEqual(
                    w, 0.0, f"{type(s).__name__} negative weight for {k}"
                )

    def test_all_registered_in_registry(self):
        ids = ["S71", "S72", "S73", "S74", "S75", "S76", "S77"]
        for sid in ids:
            self.assertIsNotNone(REGISTRY.get(sid), f"{sid} not in REGISTRY")


if __name__ == "__main__":
    unittest.main(verbosity=2)
