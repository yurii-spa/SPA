"""
Tests for spa_core/strategies/s_basis.py — S_BASIS basis trade strategy.

Tests cover ENTER/SKIP/MONITOR signal mapping, stale data handling,
allocation capping, and integration with BasisTradeAnalyzer.
"""
import json
import tempfile
import time
import unittest
from pathlib import Path

from spa_core.strategies.s_basis import (
    ALLOCATION,
    MAX_BTS_WEIGHT,
    STRATEGY_ID,
    STRATEGY_NAME,
    TARGET_APY_MAX,
    TARGET_APY_MIN,
    TIER,
    BasisSignal,
    SBasisStrategy,
)


def _write_funding_data(data_dir, assets, stale=False):
    """Write test perp_funding_rates.json."""
    data = {
        "timestamp": "2026-06-21T15:00:00+00:00",
        "fetched_at": time.time(),
        "stale": stale,
        "assets": assets,
    }
    path = data_dir / "perp_funding_rates.json"
    with open(path, "w") as f:
        json.dump(data, f)


def _write_adapter_status(data_dir, adapters):
    """Write test adapter_status.json."""
    path = data_dir / "adapter_status.json"
    with open(path, "w") as f:
        json.dump(adapters, f)


def _default_eth_funding(annual=0.10512, oi=500_000_000.0):
    return {
        "funding_rate_1h": annual / 8760,
        "funding_rate_8h": annual / 8760 * 8,
        "funding_rate_annual": annual,
        "open_interest_usd": oi,
        "mark_price": 3200.5,
        "premium": 0.00008,
    }


def _default_btc_funding(annual=0.08, oi=1_000_000_000.0):
    return {
        "funding_rate_1h": annual / 8760,
        "funding_rate_8h": annual / 8760 * 8,
        "funding_rate_annual": annual,
        "open_interest_usd": oi,
        "mark_price": 65000.0,
        "premium": 0.0001,
    }


class TestStrategyConstants(unittest.TestCase):
    """Test exported module constants."""

    def test_strategy_id(self):
        self.assertEqual(STRATEGY_ID, "S_BASIS")

    def test_strategy_name(self):
        self.assertIn("Basis", STRATEGY_NAME)

    def test_tier(self):
        self.assertEqual(TIER, "T2")

    def test_target_apy_range(self):
        self.assertEqual(TARGET_APY_MIN, 0.0)
        self.assertEqual(TARGET_APY_MAX, 24.0)

    def test_allocation_keys(self):
        self.assertIn("usdc_lend_leg", ALLOCATION)
        self.assertIn("perp_short_leg", ALLOCATION)
        self.assertAlmostEqual(sum(ALLOCATION.values()), 1.0, places=2)

    def test_max_weight_cap(self):
        self.assertLessEqual(MAX_BTS_WEIGHT, 0.20)


class TestBasisSignal(unittest.TestCase):
    """Test BasisSignal dataclass."""

    def test_to_dict(self):
        sig = BasisSignal(
            asset="ETH",
            structure="explicit_long_usdc_short_perp",
            net_spread_bps=125.5,
            edge_quality="EXCELLENT",
            recommended_action="ENTER",
            target_weight=0.15,
            annual_pnl_usd=2510.0,
        )
        d = sig.to_dict()
        self.assertEqual(d["asset"], "ETH")
        self.assertEqual(d["edge_quality"], "EXCELLENT")
        self.assertEqual(d["recommended_action"], "ENTER")
        self.assertAlmostEqual(d["net_spread_bps"], 125.5)

    def test_to_dict_keys(self):
        sig = BasisSignal("ETH", "x", 50.0, "GOOD", "ENTER", 0.1, 100.0)
        keys = set(sig.to_dict().keys())
        expected = {
            "asset", "structure", "net_spread_bps", "edge_quality",
            "recommended_action", "target_weight", "annual_pnl_usd",
        }
        self.assertEqual(keys, expected)


class TestSBasisStrategyEvaluate(unittest.TestCase):
    """Test SBasisStrategy.evaluate()."""

    def setUp(self):
        self.tmp_dir = tempfile.mkdtemp()
        self.data_dir = Path(self.tmp_dir)

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmp_dir, ignore_errors=True)

    def test_enter_signal_when_funding_high(self):
        _write_funding_data(self.data_dir, {
            "ETH": _default_eth_funding(annual=0.15),
            "BTC": _default_btc_funding(annual=0.12),
        })
        _write_adapter_status(self.data_dir, {
            "aave_v3": {"apy": 0.031},
        })
        strategy = SBasisStrategy(data_dir=self.data_dir)
        signals = strategy.evaluate()
        self.assertGreater(len(signals), 0)
        enter_signals = [s for s in signals if s.recommended_action == "ENTER"]
        self.assertGreater(len(enter_signals), 0)

    def test_no_signal_when_data_stale(self):
        _write_funding_data(self.data_dir, {
            "ETH": _default_eth_funding(annual=0.15),
        }, stale=True)
        strategy = SBasisStrategy(data_dir=self.data_dir)
        signals = strategy.evaluate()
        self.assertEqual(len(signals), 0)

    def test_no_signal_when_no_data(self):
        strategy = SBasisStrategy(data_dir=self.data_dir)
        signals = strategy.evaluate()
        self.assertEqual(len(signals), 0)

    def test_skip_when_funding_low(self):
        # Net spread < 50 bps requires gross < 70 bps (exec_cost=20).
        # With spot_yield ~0.031, funding must be < -0.024 to pull gross below 70 bps.
        _write_funding_data(self.data_dir, {
            "ETH": _default_eth_funding(annual=-0.028),
            "BTC": _default_btc_funding(annual=-0.028),
        })
        _write_adapter_status(self.data_dir, {
            "aave_v3": {"apy": 0.031},
        })
        strategy = SBasisStrategy(data_dir=self.data_dir)
        signals = strategy.evaluate()
        enter_signals = [s for s in signals if s.recommended_action == "ENTER"]
        self.assertEqual(len(enter_signals), 0)

    def test_skip_when_funding_negative(self):
        _write_funding_data(self.data_dir, {
            "ETH": _default_eth_funding(annual=-0.05),
            "BTC": _default_btc_funding(annual=-0.03),
        })
        _write_adapter_status(self.data_dir, {
            "aave_v3": {"apy": 0.031},
        })
        strategy = SBasisStrategy(data_dir=self.data_dir)
        signals = strategy.evaluate()
        enter_signals = [s for s in signals if s.recommended_action == "ENTER"]
        self.assertEqual(len(enter_signals), 0)

    def test_skip_when_oi_too_low(self):
        _write_funding_data(self.data_dir, {
            "ETH": _default_eth_funding(annual=0.15, oi=10_000_000.0),
            "BTC": _default_btc_funding(annual=0.12, oi=10_000_000.0),
        })
        _write_adapter_status(self.data_dir, {
            "aave_v3": {"apy": 0.031},
        })
        strategy = SBasisStrategy(data_dir=self.data_dir)
        signals = strategy.evaluate()
        self.assertEqual(len(signals), 0)

    def test_signals_sorted_by_net_spread(self):
        _write_funding_data(self.data_dir, {
            "ETH": _default_eth_funding(annual=0.10),
            "BTC": _default_btc_funding(annual=0.20),
        })
        _write_adapter_status(self.data_dir, {
            "aave_v3": {"apy": 0.031},
        })
        strategy = SBasisStrategy(data_dir=self.data_dir)
        signals = strategy.evaluate()
        if len(signals) >= 2:
            self.assertGreaterEqual(
                signals[0].net_spread_bps, signals[1].net_spread_bps
            )

    def test_structure_is_explicit(self):
        _write_funding_data(self.data_dir, {
            "ETH": _default_eth_funding(annual=0.15),
        })
        _write_adapter_status(self.data_dir, {"aave_v3": {"apy": 0.031}})
        strategy = SBasisStrategy(data_dir=self.data_dir)
        signals = strategy.evaluate()
        for sig in signals:
            self.assertEqual(sig.structure, "explicit_long_usdc_short_perp")

    def test_edge_quality_excellent(self):
        _write_funding_data(self.data_dir, {
            "ETH": _default_eth_funding(annual=0.20),
        })
        _write_adapter_status(self.data_dir, {"aave_v3": {"apy": 0.031}})
        strategy = SBasisStrategy(data_dir=self.data_dir)
        signals = strategy.evaluate()
        eth = next((s for s in signals if s.asset == "ETH"), None)
        self.assertIsNotNone(eth)
        self.assertIn(eth.edge_quality, ("EXCELLENT", "GOOD"))

    def test_monitor_signal_not_allocated(self):
        _write_funding_data(self.data_dir, {
            "ETH": _default_eth_funding(annual=0.005),
        })
        _write_adapter_status(self.data_dir, {"aave_v3": {"apy": 0.031}})
        strategy = SBasisStrategy(data_dir=self.data_dir)
        signals = strategy.evaluate()
        for sig in signals:
            if sig.recommended_action == "MONITOR":
                self.assertEqual(sig.target_weight, 0.0)


class TestSBasisStrategyAllocate(unittest.TestCase):
    """Test SBasisStrategy.allocate()."""

    def setUp(self):
        self.tmp_dir = tempfile.mkdtemp()
        self.data_dir = Path(self.tmp_dir)

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmp_dir, ignore_errors=True)

    def test_allocation_capped_at_20_percent(self):
        _write_funding_data(self.data_dir, {
            "ETH": _default_eth_funding(annual=0.50),
            "BTC": _default_btc_funding(annual=0.50),
        })
        _write_adapter_status(self.data_dir, {"aave_v3": {"apy": 0.031}})
        strategy = SBasisStrategy(data_dir=self.data_dir, capital=100_000.0)
        alloc = strategy.allocate()
        total = sum(alloc.values())
        self.assertLessEqual(total, 100_000 * MAX_BTS_WEIGHT + 1.0)

    def test_no_allocation_when_skip(self):
        _write_funding_data(self.data_dir, {
            "ETH": _default_eth_funding(annual=-0.05),
        })
        _write_adapter_status(self.data_dir, {"aave_v3": {"apy": 0.031}})
        strategy = SBasisStrategy(data_dir=self.data_dir)
        alloc = strategy.allocate()
        self.assertEqual(alloc, {})

    def test_no_allocation_when_stale(self):
        _write_funding_data(self.data_dir, {
            "ETH": _default_eth_funding(annual=0.15),
        }, stale=True)
        strategy = SBasisStrategy(data_dir=self.data_dir)
        alloc = strategy.allocate()
        self.assertEqual(alloc, {})

    def test_allocation_has_lend_and_short_legs(self):
        _write_funding_data(self.data_dir, {
            "ETH": _default_eth_funding(annual=0.15),
        })
        _write_adapter_status(self.data_dir, {"aave_v3": {"apy": 0.031}})
        strategy = SBasisStrategy(data_dir=self.data_dir)
        alloc = strategy.allocate()
        if alloc:
            has_lend = any("lend" in k for k in alloc)
            has_short = any("short" in k for k in alloc)
            self.assertTrue(has_lend)
            self.assertTrue(has_short)

    def test_allocation_delta_neutral_split(self):
        _write_funding_data(self.data_dir, {
            "ETH": _default_eth_funding(annual=0.15),
        })
        _write_adapter_status(self.data_dir, {"aave_v3": {"apy": 0.031}})
        strategy = SBasisStrategy(data_dir=self.data_dir)
        alloc = strategy.allocate()
        if alloc:
            lend_val = alloc.get("basis_eth_lend", 0)
            short_val = alloc.get("basis_eth_short", 0)
            self.assertAlmostEqual(lend_val, short_val, places=0)

    def test_no_allocation_when_no_data(self):
        strategy = SBasisStrategy(data_dir=self.data_dir)
        alloc = strategy.allocate()
        self.assertEqual(alloc, {})

    def test_allocation_with_sleeve_capital(self):
        _write_funding_data(self.data_dir, {
            "ETH": _default_eth_funding(annual=0.15),
        })
        _write_adapter_status(self.data_dir, {"aave_v3": {"apy": 0.031}})
        strategy = SBasisStrategy(data_dir=self.data_dir, capital=100_000)
        alloc = strategy.allocate(sleeve_capital_usd=10_000.0)
        total = sum(alloc.values())
        self.assertLessEqual(total, 10_000.0 + 1.0)


class TestSBasisStrategySpotYield(unittest.TestCase):
    """Test _spot_yield_for method."""

    def setUp(self):
        self.tmp_dir = tempfile.mkdtemp()
        self.data_dir = Path(self.tmp_dir)
        self.strategy = SBasisStrategy(data_dir=self.data_dir)

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmp_dir, ignore_errors=True)

    def test_reads_aave_v3(self):
        adapter = {"aave_v3": {"apy": 0.031}}
        yield_val = self.strategy._spot_yield_for("ETH", adapter)
        self.assertAlmostEqual(yield_val, 0.031, places=3)

    def test_reads_compound_v3(self):
        adapter = {"compound_v3": {"apy": 0.033}}
        yield_val = self.strategy._spot_yield_for("ETH", adapter)
        self.assertAlmostEqual(yield_val, 0.033, places=3)

    def test_picks_best_yield(self):
        adapter = {
            "aave_v3": {"apy": 0.031},
            "compound_v3": {"apy": 0.033},
            "morpho_steakhouse": {"apy": 0.046},
        }
        yield_val = self.strategy._spot_yield_for("ETH", adapter)
        self.assertAlmostEqual(yield_val, 0.046, places=3)

    def test_handles_percent_format(self):
        adapter = {"aave_v3": {"apy": 3.1}}
        yield_val = self.strategy._spot_yield_for("ETH", adapter)
        self.assertAlmostEqual(yield_val, 0.031, places=3)

    def test_fallback_when_no_data(self):
        yield_val = self.strategy._spot_yield_for("ETH", {})
        self.assertEqual(yield_val, 0.03)

    def test_handles_current_apy_key(self):
        adapter = {"aave_v3": {"current_apy": 0.035}}
        yield_val = self.strategy._spot_yield_for("ETH", adapter)
        self.assertAlmostEqual(yield_val, 0.035, places=3)


class TestSBasisStrategySummary(unittest.TestCase):
    """Test get_summary method."""

    def setUp(self):
        self.tmp_dir = tempfile.mkdtemp()
        self.data_dir = Path(self.tmp_dir)

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmp_dir, ignore_errors=True)

    def test_summary_with_data(self):
        _write_funding_data(self.data_dir, {
            "ETH": _default_eth_funding(annual=0.15),
        })
        _write_adapter_status(self.data_dir, {"aave_v3": {"apy": 0.031}})
        strategy = SBasisStrategy(data_dir=self.data_dir)
        summary = strategy.get_summary()
        self.assertEqual(summary["strategy_id"], "S_BASIS")
        self.assertIn("signals_count", summary)

    def test_summary_no_data(self):
        strategy = SBasisStrategy(data_dir=self.data_dir)
        summary = strategy.get_summary()
        self.assertEqual(summary["strategy_id"], "S_BASIS")
        self.assertEqual(summary.get("signals_count", 0), 0)


class TestStrategyRegistration(unittest.TestCase):
    """Test that S_BASIS integrates with the registries."""

    def test_paper_trading_registry_has_s_basis(self):
        try:
            from spa_core.paper_trading.strategy_registry import STRATEGY_REGISTRY
            self.assertIn("S_BASIS", STRATEGY_REGISTRY)
            config = STRATEGY_REGISTRY["S_BASIS"]
            self.assertEqual(config.id, "S_BASIS")
            self.assertEqual(config.tier, "T2")
        except ImportError:
            self.skipTest("strategy_registry not importable")

    def test_strategy_config_allocations(self):
        try:
            from spa_core.paper_trading.strategy_registry import STRATEGY_REGISTRY
            config = STRATEGY_REGISTRY["S_BASIS"]
            self.assertIn("usdc_lend_leg", config.allocations)
            self.assertIn("perp_short_leg", config.allocations)
        except ImportError:
            self.skipTest("strategy_registry not importable")

    def test_strategy_config_gate_condition(self):
        try:
            from spa_core.paper_trading.strategy_registry import STRATEGY_REGISTRY
            config = STRATEGY_REGISTRY["S_BASIS"]
            self.assertTrue(config.gate_condition({"perp_funding_eth": 0.05}))
            self.assertTrue(config.gate_condition({"perp_funding_eth": 0.0}))
            self.assertFalse(config.gate_condition({"perp_funding_eth": -0.01}))
        except ImportError:
            self.skipTest("strategy_registry not importable")


if __name__ == "__main__":
    unittest.main()
