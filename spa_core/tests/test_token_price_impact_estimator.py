"""Tests for MP-688 TokenPriceImpactEstimator.

Run with:
    python3 -m unittest spa_core.tests.test_token_price_impact_estimator -v

Covers ≥65 test cases:
  - CPAMM / CLMM / ORDERBOOK impact formulas
  - Impact cap at 10 000 bps
  - fee_cost_bps passthrough
  - total_slippage with half-spread for orderbook
  - execution_quality thresholds (all 5)
  - expected_fill_pct mappings
  - split_recommendation logic
  - Warning conditions (REJECT, spread, volatility, large trade)
  - estimate() known-value integration tests
  - estimate_batch() empty + multi
  - save_results() ring-buffer + atomic write
  - load_history() missing file returns []
"""

import json
import os
import tempfile
import unittest
from pathlib import Path

from spa_core.analytics.token_price_impact_estimator import (
    MAX_ENTRIES,
    PriceImpactEstimate,
    TokenPriceImpactEstimator,
    TradeSpec,
)


# ─── helpers ──────────────────────────────────────────────────────────────────

def _spec(
    *,
    trade_id="T1",
    token="USDC",
    direction="BUY",
    trade_size_usd=1_000.0,
    pool_type="CPAMM",
    pool_liquidity_usd=1_000_000.0,
    fee_tier_bps=30.0,
    volatility_24h_pct=2.0,
    spread_bps=None,
) -> TradeSpec:
    return TradeSpec(
        trade_id=trade_id,
        token=token,
        direction=direction,
        trade_size_usd=trade_size_usd,
        pool_type=pool_type,
        pool_liquidity_usd=pool_liquidity_usd,
        fee_tier_bps=fee_tier_bps,
        volatility_24h_pct=volatility_24h_pct,
        spread_bps=spread_bps,
    )


def _estimator(tmp_dir) -> TokenPriceImpactEstimator:
    data_file = Path(tmp_dir) / "price_impact_log.json"
    return TokenPriceImpactEstimator(data_file=data_file)


# ─── CPAMM model ──────────────────────────────────────────────────────────────

class TestCPAMMImpact(unittest.TestCase):

    def setUp(self):
        self.est = TokenPriceImpactEstimator()

    def test_cpamm_formula_basic(self):
        # impact = (1000 / 1_000_000) * 10_000 * 2 = 20.0 bps
        s = _spec(trade_size_usd=1_000, pool_liquidity_usd=1_000_000, pool_type="CPAMM")
        result = self.est._price_impact_bps(s)
        self.assertAlmostEqual(result, 20.0, places=6)

    def test_cpamm_formula_small_trade(self):
        # (100 / 1_000_000) * 10_000 * 2 = 2.0 bps
        s = _spec(trade_size_usd=100, pool_liquidity_usd=1_000_000, pool_type="CPAMM")
        self.assertAlmostEqual(self.est._price_impact_bps(s), 2.0, places=6)

    def test_cpamm_formula_large_pool(self):
        # (10_000 / 10_000_000) * 10_000 * 2 = 20.0
        s = _spec(trade_size_usd=10_000, pool_liquidity_usd=10_000_000, pool_type="CPAMM")
        self.assertAlmostEqual(self.est._price_impact_bps(s), 20.0, places=6)

    def test_cpamm_formula_half_liquidity(self):
        # (500_000 / 1_000_000) * 10_000 * 2 = 10_000 → capped
        s = _spec(trade_size_usd=500_000, pool_liquidity_usd=1_000_000, pool_type="CPAMM")
        self.assertEqual(self.est._price_impact_bps(s), 10_000.0)

    def test_cpamm_case_insensitive(self):
        s = _spec(pool_type="cpamm")
        r = self.est._price_impact_bps(s)
        self.assertAlmostEqual(r, 20.0, places=6)

    def test_cpamm_sell_direction_same_formula(self):
        # direction does not affect impact formula
        buy = _spec(direction="BUY", pool_type="CPAMM")
        sell = _spec(direction="SELL", pool_type="CPAMM")
        self.assertAlmostEqual(
            self.est._price_impact_bps(buy),
            self.est._price_impact_bps(sell),
        )


# ─── CLMM model ───────────────────────────────────────────────────────────────

class TestCLMMImpact(unittest.TestCase):

    def setUp(self):
        self.est = TokenPriceImpactEstimator()

    def test_clmm_formula_basic(self):
        # (1000 / 1_000_000) * 10_000 * 0.5 = 5.0 bps
        s = _spec(trade_size_usd=1_000, pool_liquidity_usd=1_000_000, pool_type="CLMM")
        self.assertAlmostEqual(self.est._price_impact_bps(s), 5.0, places=6)

    def test_clmm_lower_than_cpamm(self):
        kwargs = dict(trade_size_usd=5_000, pool_liquidity_usd=500_000)
        clmm = self.est._price_impact_bps(_spec(pool_type="CLMM", **kwargs))
        cpamm = self.est._price_impact_bps(_spec(pool_type="CPAMM", **kwargs))
        self.assertLess(clmm, cpamm)

    def test_clmm_ratio_to_cpamm(self):
        kwargs = dict(trade_size_usd=1_000, pool_liquidity_usd=1_000_000)
        clmm = self.est._price_impact_bps(_spec(pool_type="CLMM", **kwargs))
        cpamm = self.est._price_impact_bps(_spec(pool_type="CPAMM", **kwargs))
        # CLMM multiplier is 0.5 vs 2.0 → ratio = 1/4
        self.assertAlmostEqual(clmm / cpamm, 0.25, places=6)

    def test_clmm_formula_large_trade(self):
        # (200_000 / 1_000_000) * 10_000 * 0.5 = 1000 bps
        s = _spec(trade_size_usd=200_000, pool_liquidity_usd=1_000_000, pool_type="CLMM")
        self.assertAlmostEqual(self.est._price_impact_bps(s), 1_000.0, places=6)

    def test_clmm_cap_applied(self):
        s = _spec(trade_size_usd=3_000_000, pool_liquidity_usd=1_000_000, pool_type="CLMM")
        self.assertEqual(self.est._price_impact_bps(s), 10_000.0)


# ─── ORDERBOOK model ──────────────────────────────────────────────────────────

class TestOrderbookImpact(unittest.TestCase):

    def setUp(self):
        self.est = TokenPriceImpactEstimator()

    def test_orderbook_formula_basic(self):
        # vol=2%, size=1000, liq=1_000_000 → 2 * (1000/1_000_000) * 100 = 0.2 bps
        s = _spec(
            trade_size_usd=1_000,
            pool_liquidity_usd=1_000_000,
            pool_type="ORDERBOOK",
            volatility_24h_pct=2.0,
        )
        self.assertAlmostEqual(self.est._price_impact_bps(s), 0.2, places=6)

    def test_orderbook_formula_higher_vol(self):
        # vol=10%, size=10_000, liq=500_000 → 10 * (10_000/500_000) * 100 = 20 bps
        s = _spec(
            trade_size_usd=10_000,
            pool_liquidity_usd=500_000,
            pool_type="ORDERBOOK",
            volatility_24h_pct=10.0,
        )
        self.assertAlmostEqual(self.est._price_impact_bps(s), 20.0, places=6)

    def test_orderbook_zero_volatility_zero_impact(self):
        s = _spec(pool_type="ORDERBOOK", volatility_24h_pct=0.0)
        self.assertAlmostEqual(self.est._price_impact_bps(s), 0.0, places=6)

    def test_orderbook_cap_applied(self):
        # vol=200%, size=1_000_000, liq=100_000 → 200 * 10 * 100 = 200_000 → capped
        s = _spec(
            trade_size_usd=1_000_000,
            pool_liquidity_usd=100_000,
            pool_type="ORDERBOOK",
            volatility_24h_pct=200.0,
        )
        self.assertEqual(self.est._price_impact_bps(s), 10_000.0)


# ─── Impact cap ───────────────────────────────────────────────────────────────

class TestImpactCap(unittest.TestCase):

    def setUp(self):
        self.est = TokenPriceImpactEstimator()

    def test_impact_cap_cpamm(self):
        s = _spec(trade_size_usd=1_000_000, pool_liquidity_usd=1_000, pool_type="CPAMM")
        self.assertLessEqual(self.est._price_impact_bps(s), 10_000.0)

    def test_impact_cap_clmm(self):
        s = _spec(trade_size_usd=10_000_000, pool_liquidity_usd=1_000, pool_type="CLMM")
        self.assertLessEqual(self.est._price_impact_bps(s), 10_000.0)

    def test_impact_cap_orderbook(self):
        s = _spec(
            trade_size_usd=10_000_000,
            pool_liquidity_usd=1_000,
            pool_type="ORDERBOOK",
            volatility_24h_pct=999.0,
        )
        self.assertLessEqual(self.est._price_impact_bps(s), 10_000.0)

    def test_impact_exactly_at_cap(self):
        # CPAMM: (500_000 / 1_000_000) * 10_000 * 2 = 10_000 → exactly at cap
        s = _spec(trade_size_usd=500_000, pool_liquidity_usd=1_000_000, pool_type="CPAMM")
        self.assertEqual(self.est._price_impact_bps(s), 10_000.0)


# ─── fee_cost_bps passthrough ─────────────────────────────────────────────────

class TestFeeCostBps(unittest.TestCase):

    def setUp(self):
        self.est = TokenPriceImpactEstimator()

    def test_fee_cost_matches_spec(self):
        s = _spec(fee_tier_bps=30.0)
        result = self.est.estimate(s)
        self.assertAlmostEqual(result.fee_cost_bps, 30.0, places=6)

    def test_fee_cost_zero(self):
        s = _spec(fee_tier_bps=0.0)
        result = self.est.estimate(s)
        self.assertAlmostEqual(result.fee_cost_bps, 0.0, places=6)

    def test_fee_cost_high(self):
        s = _spec(fee_tier_bps=100.0)
        result = self.est.estimate(s)
        self.assertAlmostEqual(result.fee_cost_bps, 100.0, places=6)


# ─── total_slippage ───────────────────────────────────────────────────────────

class TestTotalSlippage(unittest.TestCase):

    def setUp(self):
        self.est = TokenPriceImpactEstimator()

    def test_total_slippage_cpamm_no_spread(self):
        # impact=20 bps, fee=30 bps, no spread → total=50
        s = _spec(trade_size_usd=1_000, pool_liquidity_usd=1_000_000,
                  pool_type="CPAMM", fee_tier_bps=30.0, spread_bps=None)
        result = self.est.estimate(s)
        self.assertAlmostEqual(result.total_slippage_bps, 50.0, places=6)

    def test_total_slippage_orderbook_with_spread(self):
        # impact=0.2, fee=10, spread=40 → half_spread=20 → total=30.2
        s = _spec(
            trade_size_usd=1_000,
            pool_liquidity_usd=1_000_000,
            pool_type="ORDERBOOK",
            fee_tier_bps=10.0,
            volatility_24h_pct=2.0,
            spread_bps=40.0,
        )
        result = self.est.estimate(s)
        self.assertAlmostEqual(result.total_slippage_bps, 0.2 + 10.0 + 20.0, places=5)

    def test_total_slippage_orderbook_none_spread(self):
        # spread=None → no spread component
        s = _spec(pool_type="ORDERBOOK", fee_tier_bps=5.0, spread_bps=None,
                  volatility_24h_pct=2.0)
        result = self.est.estimate(s)
        expected = self.est._price_impact_bps(s) + 5.0
        self.assertAlmostEqual(result.total_slippage_bps, expected, places=6)

    def test_total_slippage_half_spread_formula(self):
        # Confirm only half of spread_bps is added
        s = _spec(pool_type="ORDERBOOK", fee_tier_bps=0.0,
                  spread_bps=100.0, trade_size_usd=100,
                  pool_liquidity_usd=1_000_000, volatility_24h_pct=0.0)
        result = self.est.estimate(s)
        # impact=0, fee=0, half_spread=50 → total=50
        self.assertAlmostEqual(result.total_slippage_bps, 50.0, places=6)

    def test_cpamm_spread_ignored(self):
        # spread_bps supplied but pool_type=CPAMM → spread not added
        s = _spec(pool_type="CPAMM", fee_tier_bps=10.0, spread_bps=200.0)
        result = self.est.estimate(s)
        self.assertAlmostEqual(
            result.total_slippage_bps,
            result.price_impact_bps + 10.0,
            places=6,
        )


# ─── execution_quality thresholds ─────────────────────────────────────────────

class TestExecutionQuality(unittest.TestCase):

    def setUp(self):
        self.est = TokenPriceImpactEstimator()

    def test_quality_excellent_below_5(self):
        self.assertEqual(self.est._execution_quality(4.9), "EXCELLENT")

    def test_quality_excellent_zero(self):
        self.assertEqual(self.est._execution_quality(0.0), "EXCELLENT")

    def test_quality_good_boundary(self):
        self.assertEqual(self.est._execution_quality(5.0), "GOOD")

    def test_quality_good_mid(self):
        self.assertEqual(self.est._execution_quality(10.0), "GOOD")

    def test_quality_good_upper(self):
        self.assertEqual(self.est._execution_quality(19.9), "GOOD")

    def test_quality_fair_boundary(self):
        self.assertEqual(self.est._execution_quality(20.0), "FAIR")

    def test_quality_fair_mid(self):
        self.assertEqual(self.est._execution_quality(35.0), "FAIR")

    def test_quality_fair_upper(self):
        self.assertEqual(self.est._execution_quality(49.9), "FAIR")

    def test_quality_poor_boundary(self):
        self.assertEqual(self.est._execution_quality(50.0), "POOR")

    def test_quality_poor_mid(self):
        self.assertEqual(self.est._execution_quality(100.0), "POOR")

    def test_quality_poor_upper(self):
        self.assertEqual(self.est._execution_quality(199.9), "POOR")

    def test_quality_reject_boundary(self):
        self.assertEqual(self.est._execution_quality(200.0), "REJECT")

    def test_quality_reject_high(self):
        self.assertEqual(self.est._execution_quality(10_000.0), "REJECT")


# ─── expected_fill_pct ────────────────────────────────────────────────────────

class TestExpectedFillPct(unittest.TestCase):

    def setUp(self):
        self.est = TokenPriceImpactEstimator()

    def test_fill_excellent(self):
        self.assertAlmostEqual(self.est._expected_fill_pct("EXCELLENT"), 100.0)

    def test_fill_good(self):
        self.assertAlmostEqual(self.est._expected_fill_pct("GOOD"), 100.0)

    def test_fill_fair(self):
        self.assertAlmostEqual(self.est._expected_fill_pct("FAIR"), 95.0)

    def test_fill_poor(self):
        self.assertAlmostEqual(self.est._expected_fill_pct("POOR"), 80.0)

    def test_fill_reject(self):
        self.assertAlmostEqual(self.est._expected_fill_pct("REJECT"), 0.0)


# ─── split_recommendation ─────────────────────────────────────────────────────

class TestSplitRecommendation(unittest.TestCase):

    def setUp(self):
        self.est = TokenPriceImpactEstimator()

    def test_split_excellent_none(self):
        self.assertIsNone(self.est._split_recommendation("EXCELLENT"))

    def test_split_good_none(self):
        self.assertIsNone(self.est._split_recommendation("GOOD"))

    def test_split_fair_two(self):
        self.assertEqual(self.est._split_recommendation("FAIR"), 2)

    def test_split_poor_four(self):
        self.assertEqual(self.est._split_recommendation("POOR"), 4)

    def test_split_reject_none(self):
        self.assertIsNone(self.est._split_recommendation("REJECT"))


# ─── Warnings ─────────────────────────────────────────────────────────────────

class TestWarnings(unittest.TestCase):

    def setUp(self):
        self.est = TokenPriceImpactEstimator()

    def _spec_with_reject(self) -> TradeSpec:
        # Very large trade → REJECT
        return _spec(
            trade_size_usd=1_000_000,
            pool_liquidity_usd=1_000,
            pool_type="CPAMM",
            fee_tier_bps=0.0,
        )

    def test_reject_warning_present(self):
        result = self.est.estimate(self._spec_with_reject())
        self.assertEqual(result.execution_quality, "REJECT")
        self.assertTrue(
            any("do not execute" in w for w in result.warnings)
        )

    def test_no_reject_warning_when_good(self):
        s = _spec(trade_size_usd=100, pool_liquidity_usd=10_000_000, fee_tier_bps=1.0)
        result = self.est.estimate(s)
        self.assertFalse(
            any("do not execute" in w for w in result.warnings)
        )

    def test_wide_spread_warning_orderbook(self):
        s = _spec(
            pool_type="ORDERBOOK",
            spread_bps=51.0,
            volatility_24h_pct=1.0,
            fee_tier_bps=1.0,
        )
        warns = self.est._warnings(s, "GOOD")
        self.assertTrue(any("Wide bid-ask spread" in w for w in warns))

    def test_no_wide_spread_warning_below_50(self):
        s = _spec(pool_type="ORDERBOOK", spread_bps=50.0, volatility_24h_pct=1.0)
        warns = self.est._warnings(s, "GOOD")
        self.assertFalse(any("Wide bid-ask spread" in w for w in warns))

    def test_high_volatility_warning(self):
        s = _spec(volatility_24h_pct=10.1)
        warns = self.est._warnings(s, "GOOD")
        self.assertTrue(any("High 24h volatility" in w for w in warns))

    def test_no_high_volatility_warning_at_10(self):
        s = _spec(volatility_24h_pct=10.0)
        warns = self.est._warnings(s, "GOOD")
        self.assertFalse(any("High 24h volatility" in w for w in warns))

    def test_large_trade_warning(self):
        # trade_size > 5% of pool_liquidity
        s = _spec(trade_size_usd=60_000, pool_liquidity_usd=1_000_000)
        warns = self.est._warnings(s, "GOOD")
        self.assertTrue(any("5% of pool liquidity" in w for w in warns))

    def test_no_large_trade_warning_exactly_5pct(self):
        s = _spec(trade_size_usd=50_000, pool_liquidity_usd=1_000_000)
        warns = self.est._warnings(s, "GOOD")
        self.assertFalse(any("5% of pool liquidity" in w for w in warns))


# ─── estimate() integration ───────────────────────────────────────────────────

class TestEstimateIntegration(unittest.TestCase):

    def setUp(self):
        self.est = TokenPriceImpactEstimator()

    def test_estimate_small_cpamm_excellent(self):
        # 100 / 1_000_000 * 10_000 * 2 = 2 bps impact + 5 fee = 7 → GOOD
        s = _spec(
            trade_id="TEST_SMALL",
            trade_size_usd=100,
            pool_liquidity_usd=1_000_000,
            pool_type="CPAMM",
            fee_tier_bps=5.0,
        )
        result = self.est.estimate(s)
        self.assertEqual(result.trade_id, "TEST_SMALL")
        self.assertAlmostEqual(result.price_impact_bps, 2.0, places=6)
        self.assertAlmostEqual(result.fee_cost_bps, 5.0, places=6)
        self.assertAlmostEqual(result.total_slippage_bps, 7.0, places=6)
        self.assertEqual(result.execution_quality, "GOOD")
        self.assertAlmostEqual(result.expected_fill_pct, 100.0)
        self.assertIsNone(result.split_recommendation)

    def test_estimate_huge_trade_cpamm_reject(self):
        s = _spec(
            trade_size_usd=600_000,
            pool_liquidity_usd=1_000_000,
            pool_type="CPAMM",
            fee_tier_bps=30.0,
        )
        result = self.est.estimate(s)
        self.assertEqual(result.execution_quality, "REJECT")
        self.assertAlmostEqual(result.expected_fill_pct, 0.0)
        self.assertIsNone(result.split_recommendation)
        self.assertTrue(
            any("do not execute" in w for w in result.warnings)
        )

    def test_estimate_fair_trade_cpamm(self):
        # impact = (20_000 / 1_000_000) * 10_000 * 2 = 400 bps → REJECT
        # Let's get FAIR: need total 20–50 bps
        # CPAMM: (1_000 / 1_000_000) * 20_000 = 20 bps impact, + 5 fee = 25 → FAIR
        s = _spec(
            trade_size_usd=1_000,
            pool_liquidity_usd=500_000,
            pool_type="CPAMM",
            fee_tier_bps=5.0,
        )
        result = self.est.estimate(s)
        # impact = (1000/500000)*10000*2 = 40 bps, + 5 = 45 → FAIR
        self.assertEqual(result.execution_quality, "FAIR")
        self.assertEqual(result.split_recommendation, 2)
        self.assertAlmostEqual(result.expected_fill_pct, 95.0)

    def test_estimate_poor_trade(self):
        # impact = (5_000 / 100_000) * 10_000 * 2 = 1000 bps → REJECT
        # Need POOR: 50–200 bps; use CLMM
        # CLMM: (5_000 / 100_000) * 10_000 * 0.5 = 250 bps → POOR
        s = _spec(
            trade_size_usd=5_000,
            pool_liquidity_usd=100_000,
            pool_type="CLMM",
            fee_tier_bps=10.0,
        )
        result = self.est.estimate(s)
        # 250 + 10 = 260 → REJECT
        # Adjust: 3_000 / 100_000 * 10_000 * 0.5 = 150 + 10 = 160 → POOR
        s2 = _spec(
            trade_size_usd=3_000,
            pool_liquidity_usd=100_000,
            pool_type="CLMM",
            fee_tier_bps=10.0,
        )
        result2 = self.est.estimate(s2)
        self.assertEqual(result2.execution_quality, "POOR")
        self.assertEqual(result2.split_recommendation, 4)
        self.assertAlmostEqual(result2.expected_fill_pct, 80.0)

    def test_estimate_fields_complete(self):
        s = _spec()
        result = self.est.estimate(s)
        self.assertIsInstance(result, PriceImpactEstimate)
        self.assertEqual(result.token, "USDC")
        self.assertEqual(result.direction, "BUY")
        self.assertIsInstance(result.warnings, list)


# ─── estimate_batch() ─────────────────────────────────────────────────────────

class TestEstimateBatch(unittest.TestCase):

    def setUp(self):
        self.est = TokenPriceImpactEstimator()

    def test_batch_empty_returns_empty(self):
        self.assertEqual(self.est.estimate_batch([]), [])

    def test_batch_single(self):
        result = self.est.estimate_batch([_spec()])
        self.assertEqual(len(result), 1)
        self.assertIsInstance(result[0], PriceImpactEstimate)

    def test_batch_multiple(self):
        specs = [
            _spec(trade_id="A", trade_size_usd=100),
            _spec(trade_id="B", trade_size_usd=200, pool_type="CLMM"),
            _spec(trade_id="C", trade_size_usd=300, pool_type="ORDERBOOK",
                  spread_bps=20.0),
        ]
        results = self.est.estimate_batch(specs)
        self.assertEqual(len(results), 3)
        self.assertEqual(results[0].trade_id, "A")
        self.assertEqual(results[1].trade_id, "B")
        self.assertEqual(results[2].trade_id, "C")

    def test_batch_preserves_order(self):
        ids = [f"T{i}" for i in range(10)]
        specs = [_spec(trade_id=tid) for tid in ids]
        results = self.est.estimate_batch(specs)
        self.assertEqual([r.trade_id for r in results], ids)


# ─── save_results / load_history ──────────────────────────────────────────────

class TestPersistence(unittest.TestCase):

    def _make_estimate(self, tid="T1") -> PriceImpactEstimate:
        return PriceImpactEstimate(
            trade_id=tid,
            token="USDC",
            direction="BUY",
            trade_size_usd=1_000.0,
            price_impact_bps=20.0,
            fee_cost_bps=30.0,
            total_slippage_bps=50.0,
            execution_quality="FAIR",
            expected_fill_pct=95.0,
            split_recommendation=2,
            warnings=[],
        )

    def test_save_creates_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            est = _estimator(tmp)
            est.save_results([self._make_estimate()])
            self.assertTrue(est.data_file.exists())

    def test_save_stores_entry(self):
        with tempfile.TemporaryDirectory() as tmp:
            est = _estimator(tmp)
            est.save_results([self._make_estimate("TX1")])
            history = est.load_history()
            self.assertEqual(len(history), 1)
            self.assertEqual(history[0]["trade_id"], "TX1")

    def test_save_appends_entries(self):
        with tempfile.TemporaryDirectory() as tmp:
            est = _estimator(tmp)
            est.save_results([self._make_estimate("A")])
            est.save_results([self._make_estimate("B")])
            history = est.load_history()
            self.assertEqual(len(history), 2)

    def test_save_ring_buffer_cap(self):
        with tempfile.TemporaryDirectory() as tmp:
            est = _estimator(tmp)
            # Write MAX_ENTRIES + 10 entries
            for i in range(MAX_ENTRIES + 10):
                est.save_results([self._make_estimate(f"T{i}")])
            history = est.load_history()
            self.assertEqual(len(history), MAX_ENTRIES)

    def test_save_ring_buffer_keeps_latest(self):
        with tempfile.TemporaryDirectory() as tmp:
            est = _estimator(tmp)
            for i in range(MAX_ENTRIES + 5):
                est.save_results([self._make_estimate(f"T{i}")])
            history = est.load_history()
            last_id = history[-1]["trade_id"]
            self.assertEqual(last_id, f"T{MAX_ENTRIES + 4}")

    def test_save_atomic_write_no_tmp_left(self):
        with tempfile.TemporaryDirectory() as tmp:
            est = _estimator(tmp)
            est.save_results([self._make_estimate()])
            tmp_file = est.data_file.with_suffix(".tmp")
            self.assertFalse(tmp_file.exists())

    def test_load_missing_file_returns_empty(self):
        with tempfile.TemporaryDirectory() as tmp:
            est = _estimator(tmp)
            # No file created yet
            result = est.load_history()
            self.assertEqual(result, [])

    def test_load_corrupt_file_returns_empty(self):
        with tempfile.TemporaryDirectory() as tmp:
            est = _estimator(tmp)
            est.data_file.parent.mkdir(parents=True, exist_ok=True)
            est.data_file.write_text("NOT JSON {{{")
            result = est.load_history()
            self.assertEqual(result, [])

    def test_save_serialises_warnings(self):
        with tempfile.TemporaryDirectory() as tmp:
            est = _estimator(tmp)
            e = self._make_estimate()
            e.warnings = ["⚠️ test warning"]
            est.save_results([e])
            history = est.load_history()
            self.assertEqual(history[0]["warnings"], ["⚠️ test warning"])

    def test_save_batch_multiple(self):
        with tempfile.TemporaryDirectory() as tmp:
            est = _estimator(tmp)
            estimates = [self._make_estimate(f"T{i}") for i in range(5)]
            est.save_results(estimates)
            history = est.load_history()
            self.assertEqual(len(history), 5)


if __name__ == "__main__":
    unittest.main()
