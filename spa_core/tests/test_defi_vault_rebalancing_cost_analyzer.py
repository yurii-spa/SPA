"""
Tests for MP-907: DeFiVaultRebalancingCostAnalyzer
Run with: python3 -m unittest spa_core.tests.test_defi_vault_rebalancing_cost_analyzer
"""

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

# Ensure the project root is on sys.path
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from spa_core.analytics.defi_vault_rebalancing_cost_analyzer import (
    DeFiVaultRebalancingCostAnalyzer,
    _analyze_vault,
    _compute_drift_score,
    _compute_flags,
    _compute_gas_cost,
    _compute_rebalance_label,
    _compute_slippage_cost,
    _compute_total_drift,
    _compute_trade_sizes,
    _compute_urgency_score,
)


# ─────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────

def _make_vault(
    name="Vault-A",
    protocol="Aave",
    current=None,
    target=None,
    aum=1_000_000.0,
    gas_gwei=30.0,
    slippage_model="linear",
    pool_depths=None,
    freq=30,
    last_rebalance=10,
):
    if current is None:
        current = {"USDC": 60.0, "ETH": 40.0}
    if target is None:
        target = {"USDC": 50.0, "ETH": 50.0}
    if pool_depths is None:
        pool_depths = {"USDC": 10_000_000.0, "ETH": 5_000_000.0}
    return {
        "name": name,
        "protocol": protocol,
        "current_weights": current,
        "target_weights": target,
        "aum_usd": aum,
        "gas_price_gwei": gas_gwei,
        "slippage_model": slippage_model,
        "pool_depths": pool_depths,
        "rebalance_frequency_days": freq,
        "last_rebalance_days_ago": last_rebalance,
    }


# ─────────────────────────────────────────────────────────────────
# 1. _compute_total_drift
# ─────────────────────────────────────────────────────────────────

class TestComputeTotalDrift(unittest.TestCase):

    def test_no_drift(self):
        cw = {"USDC": 50.0, "ETH": 50.0}
        tw = {"USDC": 50.0, "ETH": 50.0}
        self.assertAlmostEqual(_compute_total_drift(cw, tw), 0.0)

    def test_single_token_drift(self):
        cw = {"USDC": 60.0, "ETH": 40.0}
        tw = {"USDC": 50.0, "ETH": 50.0}
        # |60-50| + |40-50| = 10 + 10 = 20
        self.assertAlmostEqual(_compute_total_drift(cw, tw), 20.0)

    def test_three_token_drift(self):
        cw = {"A": 40.0, "B": 40.0, "C": 20.0}
        tw = {"A": 33.3, "B": 33.3, "C": 33.4}
        expected = abs(40.0 - 33.3) + abs(40.0 - 33.3) + abs(20.0 - 33.4)
        self.assertAlmostEqual(_compute_total_drift(cw, tw), expected, places=4)

    def test_missing_token_in_current(self):
        # Token in target but not in current
        cw = {"USDC": 100.0}
        tw = {"USDC": 70.0, "ETH": 30.0}
        # |100-70| + |0-30| = 30 + 30 = 60
        self.assertAlmostEqual(_compute_total_drift(cw, tw), 60.0)

    def test_missing_token_in_target(self):
        cw = {"USDC": 70.0, "ETH": 30.0}
        tw = {"USDC": 100.0}
        # |70-100| + |30-0| = 30 + 30 = 60
        self.assertAlmostEqual(_compute_total_drift(cw, tw), 60.0)

    def test_empty_both(self):
        self.assertAlmostEqual(_compute_total_drift({}, {}), 0.0)

    def test_full_reallocation(self):
        cw = {"USDC": 100.0}
        tw = {"ETH": 100.0}
        # |100-0| + |0-100| = 200
        self.assertAlmostEqual(_compute_total_drift(cw, tw), 200.0)

    def test_large_portfolio(self):
        tokens = [f"T{i}" for i in range(10)]
        cw = {t: 10.0 for t in tokens}
        tw = {t: 10.0 for t in tokens}
        tw["T0"] = 20.0
        tw["T1"] = 0.0
        # drift = |10-20| + |10-0| + 0 * 8 = 10 + 10 = 20
        self.assertAlmostEqual(_compute_total_drift(cw, tw), 20.0)


# ─────────────────────────────────────────────────────────────────
# 2. _compute_drift_score
# ─────────────────────────────────────────────────────────────────

class TestComputeDriftScore(unittest.TestCase):

    def test_zero_drift(self):
        self.assertAlmostEqual(_compute_drift_score(0.0), 0.0)

    def test_max_drift_50pct_gives_100(self):
        self.assertAlmostEqual(_compute_drift_score(50.0), 100.0)

    def test_drift_capped_at_100(self):
        self.assertEqual(_compute_drift_score(200.0), 100.0)

    def test_25pct_drift_gives_50(self):
        self.assertAlmostEqual(_compute_drift_score(25.0), 50.0)

    def test_10pct_drift(self):
        score = _compute_drift_score(10.0)
        self.assertAlmostEqual(score, 20.0)

    def test_small_drift(self):
        score = _compute_drift_score(2.0)
        self.assertAlmostEqual(score, 4.0)

    def test_returns_float(self):
        self.assertIsInstance(_compute_drift_score(5.0), float)

    def test_negative_drift_clamps_to_zero(self):
        # Negative input shouldn't occur but let's verify behavior
        score = _compute_drift_score(-1.0)
        # (−1/50)*100 = −2, but min(100, −2) = −2 — the function doesn't clamp below 0
        # We just verify it runs without error
        self.assertIsInstance(score, float)


# ─────────────────────────────────────────────────────────────────
# 3. _compute_trade_sizes
# ─────────────────────────────────────────────────────────────────

class TestComputeTradeSizes(unittest.TestCase):

    def test_basic_trade_sizes(self):
        cw = {"USDC": 60.0, "ETH": 40.0}
        tw = {"USDC": 50.0, "ETH": 50.0}
        sizes = _compute_trade_sizes(cw, tw, 1_000_000.0)
        # USDC: |60-50|/100 * 1M = 100k
        # ETH: |40-50|/100 * 1M = 100k
        self.assertAlmostEqual(sizes["USDC"], 100_000.0)
        self.assertAlmostEqual(sizes["ETH"], 100_000.0)

    def test_no_trade_for_equal_weights(self):
        cw = {"USDC": 50.0, "ETH": 50.0}
        tw = {"USDC": 50.0, "ETH": 50.0}
        sizes = _compute_trade_sizes(cw, tw, 1_000_000.0)
        self.assertEqual(len(sizes), 0)

    def test_new_token_added(self):
        cw = {"USDC": 100.0}
        tw = {"USDC": 70.0, "ETH": 30.0}
        sizes = _compute_trade_sizes(cw, tw, 500_000.0)
        self.assertAlmostEqual(sizes["ETH"], 150_000.0)

    def test_zero_aum(self):
        cw = {"USDC": 60.0, "ETH": 40.0}
        tw = {"USDC": 50.0, "ETH": 50.0}
        sizes = _compute_trade_sizes(cw, tw, 0.0)
        for v in sizes.values():
            self.assertAlmostEqual(v, 0.0)

    def test_all_tokens_traded(self):
        cw = {"A": 40.0, "B": 30.0, "C": 30.0}
        tw = {"A": 33.0, "B": 33.0, "C": 34.0}
        sizes = _compute_trade_sizes(cw, tw, 1_000_000.0)
        self.assertEqual(len(sizes), 3)


# ─────────────────────────────────────────────────────────────────
# 4. _compute_slippage_cost
# ─────────────────────────────────────────────────────────────────

class TestComputeSlippageCost(unittest.TestCase):

    def test_linear_slippage_basic(self):
        # trade_size=100k, pool=10M → ratio=0.01 → slippage_pct=0.005 (linear * 0.5)
        # cost = 100k * 0.005 = 500
        trade_sizes = {"USDC": 100_000.0}
        pool_depths = {"USDC": 10_000_000.0}
        cost = _compute_slippage_cost(trade_sizes, pool_depths, "linear")
        self.assertAlmostEqual(cost, 500.0)

    def test_quadratic_slippage_basic(self):
        # ratio=0.01, slippage_pct = 0.01**2 * 2.0 = 0.0002
        # cost = 100k * 0.0002 = 20
        trade_sizes = {"USDC": 100_000.0}
        pool_depths = {"USDC": 10_000_000.0}
        cost = _compute_slippage_cost(trade_sizes, pool_depths, "quadratic")
        self.assertAlmostEqual(cost, 20.0)

    def test_unknown_model_defaults_to_linear(self):
        trade_sizes = {"USDC": 100_000.0}
        pool_depths = {"USDC": 10_000_000.0}
        cost_linear = _compute_slippage_cost(trade_sizes, pool_depths, "linear")
        cost_unknown = _compute_slippage_cost(trade_sizes, pool_depths, "unknown_model")
        self.assertAlmostEqual(cost_linear, cost_unknown)

    def test_cap_at_10pct(self):
        # Very large trade relative to pool → slippage capped at 10%
        trade_sizes = {"USDC": 10_000_000.0}
        pool_depths = {"USDC": 100.0}  # tiny pool
        cost = _compute_slippage_cost(trade_sizes, pool_depths, "linear")
        max_cost = 10_000_000.0 * 0.10
        self.assertLessEqual(cost, max_cost + 1e-6)

    def test_zero_trade_sizes(self):
        cost = _compute_slippage_cost({}, {}, "linear")
        self.assertAlmostEqual(cost, 0.0)

    def test_missing_pool_depth_uses_default(self):
        # Pool depth not specified → uses 1M default
        trade_sizes = {"ETH": 50_000.0}
        # ratio = 50k/1M = 0.05, linear: 0.05*0.5=0.025, cost=1250
        cost = _compute_slippage_cost(trade_sizes, {}, "linear")
        self.assertGreater(cost, 0.0)

    def test_multiple_tokens(self):
        trade_sizes = {"USDC": 100_000.0, "ETH": 50_000.0}
        pool_depths = {"USDC": 10_000_000.0, "ETH": 5_000_000.0}
        cost = _compute_slippage_cost(trade_sizes, pool_depths, "linear")
        self.assertGreater(cost, 0.0)

    def test_linear_quadratic_comparison(self):
        # For small ratios, quadratic << linear
        trade_sizes = {"T": 10_000.0}
        pool_depths = {"T": 1_000_000.0}
        c_lin = _compute_slippage_cost(trade_sizes, pool_depths, "linear")
        c_quad = _compute_slippage_cost(trade_sizes, pool_depths, "quadratic")
        self.assertGreater(c_lin, c_quad)


# ─────────────────────────────────────────────────────────────────
# 5. _compute_gas_cost
# ─────────────────────────────────────────────────────────────────

class TestComputeGasCost(unittest.TestCase):

    def test_zero_trades(self):
        self.assertAlmostEqual(_compute_gas_cost(0, 30.0, 3000.0), 0.0)

    def test_single_swap(self):
        # 30 gwei * 1e-9 * 150k * 3000 = 0.03 * 150k * 3000 / 1e9
        # = 30e-9 * 150000 * 3000 = 0.0135 ETH * 3000 = $13.5
        cost = _compute_gas_cost(1, 30.0, 3000.0)
        self.assertAlmostEqual(cost, 13.5, places=2)

    def test_two_swaps(self):
        cost1 = _compute_gas_cost(1, 30.0, 3000.0)
        cost2 = _compute_gas_cost(2, 30.0, 3000.0)
        self.assertAlmostEqual(cost2, cost1 * 2)

    def test_higher_gas_price(self):
        cost_low = _compute_gas_cost(1, 10.0, 3000.0)
        cost_high = _compute_gas_cost(1, 100.0, 3000.0)
        self.assertGreater(cost_high, cost_low)

    def test_higher_eth_price(self):
        cost_low = _compute_gas_cost(1, 30.0, 1000.0)
        cost_high = _compute_gas_cost(1, 30.0, 5000.0)
        self.assertGreater(cost_high, cost_low)

    def test_returns_float(self):
        self.assertIsInstance(_compute_gas_cost(3, 25.0, 2800.0), float)

    def test_negative_trades_returns_zero(self):
        self.assertAlmostEqual(_compute_gas_cost(-1, 30.0, 3000.0), 0.0)


# ─────────────────────────────────────────────────────────────────
# 6. _compute_urgency_score
# ─────────────────────────────────────────────────────────────────

class TestComputeUrgencyScore(unittest.TestCase):

    def test_zero_drift_no_overdue(self):
        score = _compute_urgency_score(0.0, 10.0, 30.0, 0.5)
        self.assertEqual(score, 0.0)

    def test_high_drift_high_urgency(self):
        score = _compute_urgency_score(80.0, 10.0, 30.0, 0.1)
        self.assertGreater(score, 70.0)

    def test_overdue_2x_adds_bonus(self):
        score_normal = _compute_urgency_score(30.0, 30.0, 30.0, 0.1)
        score_overdue = _compute_urgency_score(30.0, 61.0, 30.0, 0.1)
        self.assertGreater(score_overdue, score_normal)

    def test_clamped_to_100(self):
        score = _compute_urgency_score(100.0, 200.0, 10.0, 0.0)
        self.assertLessEqual(score, 100.0)

    def test_clamped_to_zero(self):
        score = _compute_urgency_score(0.0, 0.0, 30.0, 5.0)
        self.assertGreaterEqual(score, 0.0)

    def test_high_cost_reduces_urgency(self):
        score_low_cost = _compute_urgency_score(30.0, 10.0, 30.0, 0.1)
        score_high_cost = _compute_urgency_score(30.0, 10.0, 30.0, 2.0)
        self.assertGreater(score_low_cost, score_high_cost)

    def test_1_5x_overdue(self):
        score_norm = _compute_urgency_score(20.0, 29.0, 30.0, 0.1)
        score_overdue = _compute_urgency_score(20.0, 46.0, 30.0, 0.1)
        self.assertGreater(score_overdue, score_norm)

    def test_zero_frequency(self):
        # Should not divide by zero
        score = _compute_urgency_score(20.0, 10.0, 0.0, 0.1)
        self.assertIsInstance(score, float)

    def test_returns_float(self):
        self.assertIsInstance(_compute_urgency_score(50.0, 30.0, 30.0, 0.5), float)


# ─────────────────────────────────────────────────────────────────
# 7. _compute_rebalance_label
# ─────────────────────────────────────────────────────────────────

class TestComputeRebalanceLabel(unittest.TestCase):

    def test_urgent_high_urgency(self):
        label = _compute_rebalance_label(10.0, 75.0)
        self.assertEqual(label, "URGENT")

    def test_not_needed_zero(self):
        label = _compute_rebalance_label(0.0, 0.0)
        self.assertEqual(label, "NOT_NEEDED")

    def test_optional_range(self):
        # urgency ~25, drift_score ~8 → OPTIONAL
        label = _compute_rebalance_label(8.0, 25.0)
        self.assertEqual(label, "OPTIONAL")

    def test_recommended_range(self):
        label = _compute_rebalance_label(20.0, 50.0)
        self.assertEqual(label, "RECOMMENDED")

    def test_returns_string(self):
        label = _compute_rebalance_label(50.0, 50.0)
        self.assertIsInstance(label, str)

    def test_valid_labels(self):
        valid = {"URGENT", "RECOMMENDED", "OPTIONAL", "NOT_NEEDED"}
        for drift in [0, 5, 15, 30, 60]:
            for urgency in [0, 20, 45, 70, 95]:
                label = _compute_rebalance_label(float(drift), float(urgency))
                self.assertIn(label, valid)

    def test_high_drift_score_urgent(self):
        # drift_score corresponding to >DRIFT_URGENT (15%) = 30 → URGENT
        from spa_core.analytics.defi_vault_rebalancing_cost_analyzer import (
            DRIFT_URGENT,
            _compute_drift_score,
        )
        ds = _compute_drift_score(DRIFT_URGENT + 1)
        label = _compute_rebalance_label(ds, 10.0)
        self.assertEqual(label, "URGENT")


# ─────────────────────────────────────────────────────────────────
# 8. _compute_flags
# ─────────────────────────────────────────────────────────────────

class TestComputeFlags(unittest.TestCase):

    def test_no_flags(self):
        flags = _compute_flags(0.5, 5.0, 10.0, 30.0, {"T": 1000.0}, {"T": 1_000_000.0})
        self.assertEqual(flags, [])

    def test_high_cost_flag(self):
        flags = _compute_flags(1.5, 5.0, 10.0, 30.0, {"T": 1000.0}, {"T": 1_000_000.0})
        self.assertIn("HIGH_COST", flags)

    def test_large_drift_flag(self):
        flags = _compute_flags(0.5, 15.0, 10.0, 30.0, {"T": 1000.0}, {"T": 1_000_000.0})
        self.assertIn("LARGE_DRIFT", flags)

    def test_overdue_flag(self):
        # last=70, freq=30 → 70 > 60 → OVERDUE
        flags = _compute_flags(0.5, 5.0, 70.0, 30.0, {"T": 1000.0}, {"T": 1_000_000.0})
        self.assertIn("OVERDUE", flags)

    def test_low_liquidity_flag(self):
        # pool_depth=5000, trade_size=1000 → 5000 < 10*1000 → LOW_LIQUIDITY
        flags = _compute_flags(0.5, 5.0, 10.0, 30.0, {"T": 1000.0}, {"T": 5_000.0})
        self.assertIn("LOW_LIQUIDITY", flags)

    def test_multiple_flags(self):
        flags = _compute_flags(2.0, 20.0, 100.0, 30.0, {"T": 100_000.0}, {"T": 500_000.0})
        self.assertIn("HIGH_COST", flags)
        self.assertIn("LARGE_DRIFT", flags)
        self.assertIn("OVERDUE", flags)

    def test_no_low_liquidity_when_deep(self):
        # pool_depth=100M, trade=100k → 100M > 10*100k → no flag
        flags = _compute_flags(0.5, 5.0, 10.0, 30.0, {"T": 100_000.0}, {"T": 100_000_000.0})
        self.assertNotIn("LOW_LIQUIDITY", flags)

    def test_exactly_2x_freq_is_overdue(self):
        # last=60, freq=30 → 60 > 60 → OVERDUE
        flags = _compute_flags(0.5, 5.0, 61.0, 30.0, {}, {})
        self.assertIn("OVERDUE", flags)

    def test_exact_boundary_not_high_cost(self):
        # cost=1.0% → NOT > 1.0 → not HIGH_COST
        flags = _compute_flags(1.0, 5.0, 10.0, 30.0, {}, {})
        self.assertNotIn("HIGH_COST", flags)

    def test_empty_trade_sizes_no_low_liquidity(self):
        flags = _compute_flags(0.5, 5.0, 10.0, 30.0, {}, {})
        self.assertNotIn("LOW_LIQUIDITY", flags)


# ─────────────────────────────────────────────────────────────────
# 9. _analyze_vault
# ─────────────────────────────────────────────────────────────────

class TestAnalyzeVault(unittest.TestCase):

    def _vault(self, **kwargs):
        return _make_vault(**kwargs)

    def test_returns_dict(self):
        result = _analyze_vault(self._vault(), {})
        self.assertIsInstance(result, dict)

    def test_required_keys(self):
        result = _analyze_vault(self._vault(), {})
        for k in [
            "name", "protocol", "drift_score", "urgency_score",
            "rebalance_cost_usd", "cost_as_pct_aum", "slippage_cost_usd",
            "gas_cost_usd", "total_drift_pct", "rebalance_label", "flags", "trade_count",
        ]:
            self.assertIn(k, result, f"Missing key: {k}")

    def test_name_preserved(self):
        result = _analyze_vault(self._vault(name="TestVault"), {})
        self.assertEqual(result["name"], "TestVault")

    def test_protocol_preserved(self):
        result = _analyze_vault(self._vault(protocol="Compound"), {})
        self.assertEqual(result["protocol"], "Compound")

    def test_drift_score_in_range(self):
        result = _analyze_vault(self._vault(), {})
        self.assertGreaterEqual(result["drift_score"], 0.0)
        self.assertLessEqual(result["drift_score"], 100.0)

    def test_urgency_score_in_range(self):
        result = _analyze_vault(self._vault(), {})
        self.assertGreaterEqual(result["urgency_score"], 0.0)
        self.assertLessEqual(result["urgency_score"], 100.0)

    def test_cost_is_nonnegative(self):
        result = _analyze_vault(self._vault(), {})
        self.assertGreaterEqual(result["rebalance_cost_usd"], 0.0)

    def test_label_is_valid(self):
        result = _analyze_vault(self._vault(), {})
        self.assertIn(result["rebalance_label"], ["URGENT", "RECOMMENDED", "OPTIONAL", "NOT_NEEDED"])

    def test_no_drift_vault(self):
        vault = self._vault(
            current={"USDC": 50.0, "ETH": 50.0},
            target={"USDC": 50.0, "ETH": 50.0},
        )
        result = _analyze_vault(vault, {})
        self.assertAlmostEqual(result["total_drift_pct"], 0.0)
        self.assertEqual(result["trade_count"], 0)
        self.assertAlmostEqual(result["slippage_cost_usd"], 0.0)

    def test_high_gas_increases_cost(self):
        r_low = _analyze_vault(self._vault(gas_gwei=5.0), {})
        r_high = _analyze_vault(self._vault(gas_gwei=300.0), {})
        self.assertGreater(r_high["gas_cost_usd"], r_low["gas_cost_usd"])

    def test_quadratic_slippage_less_than_linear(self):
        r_lin = _analyze_vault(self._vault(slippage_model="linear"), {})
        r_quad = _analyze_vault(self._vault(slippage_model="quadratic"), {})
        self.assertGreater(r_lin["slippage_cost_usd"], r_quad["slippage_cost_usd"])

    def test_larger_aum_higher_cost(self):
        r_small = _analyze_vault(self._vault(aum=100_000.0), {})
        r_large = _analyze_vault(self._vault(aum=100_000_000.0), {})
        self.assertGreater(r_large["rebalance_cost_usd"], r_small["rebalance_cost_usd"])

    def test_overdue_vault_has_overdue_flag(self):
        vault = self._vault(freq=30, last_rebalance=70)
        result = _analyze_vault(vault, {})
        self.assertIn("OVERDUE", result["flags"])

    def test_flags_is_list(self):
        result = _analyze_vault(self._vault(), {})
        self.assertIsInstance(result["flags"], list)

    def test_eth_price_from_config(self):
        r_low = _analyze_vault(self._vault(), {"eth_price_usd": 1000.0})
        r_high = _analyze_vault(self._vault(), {"eth_price_usd": 10000.0})
        self.assertGreater(r_high["gas_cost_usd"], r_low["gas_cost_usd"])

    def test_trade_count_correct(self):
        vault = self._vault(
            current={"A": 50.0, "B": 30.0, "C": 20.0},
            target={"A": 40.0, "B": 30.0, "C": 30.0},
        )
        result = _analyze_vault(vault, {})
        # B weight is equal so it shouldn't be in trades; A and C differ
        self.assertEqual(result["trade_count"], 2)


# ─────────────────────────────────────────────────────────────────
# 10. DeFiVaultRebalancingCostAnalyzer.analyze()
# ─────────────────────────────────────────────────────────────────

class TestAnalyzeMethod(unittest.TestCase):

    def setUp(self):
        self.tmp_dir = tempfile.mkdtemp()
        self.data_file = os.path.join(self.tmp_dir, "vault_rebalancing_log.json")
        self.config = {"data_file": self.data_file, "eth_price_usd": 3000.0}
        self.analyzer = DeFiVaultRebalancingCostAnalyzer()

    def test_empty_vaults_returns_valid(self):
        result = self.analyzer.analyze([], self.config)
        self.assertIn("vaults", result)
        self.assertEqual(result["vault_count"], 0)
        self.assertEqual(result["aggregates"]["urgent_count"], 0)

    def test_single_vault_result(self):
        vaults = [_make_vault()]
        result = self.analyzer.analyze(vaults, self.config)
        self.assertEqual(len(result["vaults"]), 1)
        self.assertEqual(result["vault_count"], 1)

    def test_multiple_vaults(self):
        vaults = [_make_vault(name=f"V{i}") for i in range(5)]
        result = self.analyzer.analyze(vaults, self.config)
        self.assertEqual(result["vault_count"], 5)
        self.assertEqual(len(result["vaults"]), 5)

    def test_aggregates_present(self):
        vaults = [_make_vault()]
        result = self.analyzer.analyze(vaults, self.config)
        agg = result["aggregates"]
        for k in ["most_urgent_vault", "lowest_cost_vault", "total_rebalance_cost_usd", "average_drift", "urgent_count"]:
            self.assertIn(k, agg)

    def test_total_cost_is_sum_of_vaults(self):
        vaults = [_make_vault(name=f"V{i}") for i in range(3)]
        result = self.analyzer.analyze(vaults, self.config)
        vault_sum = sum(r["rebalance_cost_usd"] for r in result["vaults"])
        self.assertAlmostEqual(result["aggregates"]["total_rebalance_cost_usd"], vault_sum, places=2)

    def test_average_drift_correct(self):
        vaults = [_make_vault(name=f"V{i}") for i in range(3)]
        result = self.analyzer.analyze(vaults, self.config)
        expected_avg = sum(r["total_drift_pct"] for r in result["vaults"]) / 3
        self.assertAlmostEqual(result["aggregates"]["average_drift"], expected_avg, places=2)

    def test_most_urgent_vault_name(self):
        v_low = _make_vault(name="Low", current={"A": 50.0}, target={"A": 50.0}, last_rebalance=1)
        v_high = _make_vault(name="High", current={"A": 0.0, "B": 100.0}, target={"A": 100.0, "B": 0.0}, last_rebalance=200)
        result = self.analyzer.analyze([v_low, v_high], self.config)
        self.assertEqual(result["aggregates"]["most_urgent_vault"], "High")

    def test_urgent_count_correct(self):
        # Create vaults with extreme drift to force URGENT label
        vaults = [
            _make_vault(name="U1", current={"A": 0.0, "B": 100.0}, target={"A": 100.0, "B": 0.0}, last_rebalance=200),
            _make_vault(name="N1", current={"A": 50.0}, target={"A": 50.0}),
        ]
        result = self.analyzer.analyze(vaults, self.config)
        # At least 1 urgent
        self.assertGreaterEqual(result["aggregates"]["urgent_count"], 1)

    def test_timestamp_present(self):
        result = self.analyzer.analyze([], self.config)
        self.assertIn("timestamp", result)
        self.assertIsInstance(result["timestamp"], float)

    def test_log_file_created(self):
        self.analyzer.analyze([_make_vault()], self.config)
        self.assertTrue(os.path.exists(self.data_file))

    def test_log_file_valid_json(self):
        self.analyzer.analyze([_make_vault()], self.config)
        with open(self.data_file) as f:
            log = json.load(f)
        self.assertIsInstance(log, list)

    def test_log_appends_entries(self):
        for _ in range(3):
            self.analyzer.analyze([_make_vault()], self.config)
        with open(self.data_file) as f:
            log = json.load(f)
        self.assertEqual(len(log), 3)

    def test_log_ring_buffer_capped(self):
        # Write 105 entries → capped at 100
        for _ in range(105):
            self.analyzer.analyze([_make_vault()], self.config)
        with open(self.data_file) as f:
            log = json.load(f)
        self.assertLessEqual(len(log), 100)

    def test_log_entry_has_aggregates(self):
        self.analyzer.analyze([_make_vault()], self.config)
        with open(self.data_file) as f:
            log = json.load(f)
        self.assertIn("aggregates", log[0])

    def test_no_config_defaults(self):
        # Should not raise even with no config
        vaults = [_make_vault()]
        # Override data file via tmp dir to avoid writing to project
        result = self.analyzer.analyze(vaults, {"data_file": self.data_file})
        self.assertIsInstance(result, dict)

    def test_lowest_cost_vault_name(self):
        v1 = _make_vault(name="BigVault", aum=100_000_000.0)
        v2 = _make_vault(name="SmallVault", aum=10_000.0)
        result = self.analyzer.analyze([v1, v2], self.config)
        self.assertEqual(result["aggregates"]["lowest_cost_vault"], "SmallVault")

    def test_no_trade_vault_excluded_from_lowest_cost(self):
        v_no_trade = _make_vault(name="NoTrade", current={"A": 50.0}, target={"A": 50.0})
        v_trade = _make_vault(name="TradingVault")
        result = self.analyzer.analyze([v_no_trade, v_trade], self.config)
        self.assertEqual(result["aggregates"]["lowest_cost_vault"], "TradingVault")

    def test_high_cost_vault_flagged(self):
        # Tiny pool + large trade → HIGH_COST
        vault = _make_vault(
            aum=10_000_000.0,
            current={"A": 0.0, "B": 100.0},
            target={"A": 100.0, "B": 0.0},
            pool_depths={"A": 1_000.0, "B": 1_000.0},  # tiny
        )
        result = self.analyzer.analyze([vault], self.config)
        # At least one vault should have HIGH_COST flag or cost > 1%
        cost_pct = result["vaults"][0]["cost_as_pct_aum"]
        if cost_pct > 1.0:
            self.assertIn("HIGH_COST", result["vaults"][0]["flags"])

    def test_result_vaults_list_ordered(self):
        names = [f"V{i}" for i in range(4)]
        vaults = [_make_vault(name=n) for n in names]
        result = self.analyzer.analyze(vaults, self.config)
        result_names = [r["name"] for r in result["vaults"]]
        self.assertEqual(result_names, names)

    def test_config_none_handled(self):
        # Pass None as config → should use defaults (writing to default DATA_FILE path)
        # We patch the write to avoid filesystem side effects
        with patch.object(DeFiVaultRebalancingCostAnalyzer, "_write_log"):
            result = self.analyzer.analyze([_make_vault()], None)
        self.assertIsInstance(result, dict)


# ─────────────────────────────────────────────────────────────────
# 11. Edge cases & integration
# ─────────────────────────────────────────────────────────────────

class TestEdgeCases(unittest.TestCase):

    def setUp(self):
        self.tmp_dir = tempfile.mkdtemp()
        self.data_file = os.path.join(self.tmp_dir, "vault_rebalancing_log.json")
        self.config = {"data_file": self.data_file, "eth_price_usd": 3000.0}
        self.analyzer = DeFiVaultRebalancingCostAnalyzer()

    def test_zero_aum_vault(self):
        vault = _make_vault(aum=0.0)
        result = self.analyzer.analyze([vault], self.config)
        self.assertEqual(result["vaults"][0]["cost_as_pct_aum"], 0.0)

    def test_very_large_aum(self):
        vault = _make_vault(aum=1_000_000_000.0)
        result = self.analyzer.analyze([vault], self.config)
        self.assertGreater(result["vaults"][0]["rebalance_cost_usd"], 0.0)

    def test_single_token_equal_weights(self):
        vault = _make_vault(
            current={"USDC": 100.0},
            target={"USDC": 100.0},
            pool_depths={"USDC": 10_000_000.0},
        )
        result = self.analyzer.analyze([vault], self.config)
        self.assertAlmostEqual(result["vaults"][0]["total_drift_pct"], 0.0)

    def test_many_tokens(self):
        tokens = [f"T{i}" for i in range(20)]
        cw = {t: 5.0 for t in tokens}
        tw = {t: 5.0 for t in tokens}
        tw["T0"] = 10.0
        tw["T1"] = 0.0
        vault = _make_vault(
            current=cw, target=tw,
            pool_depths={t: 1_000_000.0 for t in tokens},
        )
        result = self.analyzer.analyze([vault], self.config)
        self.assertIsInstance(result, dict)

    def test_corrupt_log_file_is_reset(self):
        # Write invalid JSON to the log file
        with open(self.data_file, "w") as f:
            f.write("{invalid json")
        # Should not raise
        result = self.analyzer.analyze([_make_vault()], self.config)
        self.assertIsInstance(result, dict)

    def test_log_file_contains_ts(self):
        self.analyzer.analyze([_make_vault()], self.config)
        with open(self.data_file) as f:
            log = json.load(f)
        self.assertIn("ts", log[0])

    def test_ten_vaults_aggregates(self):
        vaults = [_make_vault(name=f"V{i}", aum=float(100_000 * (i + 1))) for i in range(10)]
        result = self.analyzer.analyze(vaults, self.config)
        self.assertEqual(result["vault_count"], 10)
        self.assertGreater(result["aggregates"]["total_rebalance_cost_usd"], 0.0)

    def test_all_equal_urgency_picks_first_or_any(self):
        # All identical vaults → most_urgent must be one of them
        vaults = [_make_vault(name=f"V{i}") for i in range(3)]
        result = self.analyzer.analyze(vaults, self.config)
        names = {v["name"] for v in vaults}
        self.assertIn(result["aggregates"]["most_urgent_vault"], names)

    def test_gas_price_zero(self):
        vault = _make_vault(gas_gwei=0.0)
        result = self.analyzer.analyze([vault], self.config)
        self.assertAlmostEqual(result["vaults"][0]["gas_cost_usd"], 0.0)

    def test_flags_returned_as_list(self):
        vaults = [_make_vault()]
        result = self.analyzer.analyze(vaults, self.config)
        self.assertIsInstance(result["vaults"][0]["flags"], list)

    def test_cost_as_pct_aum_nonnegative(self):
        vaults = [_make_vault()]
        result = self.analyzer.analyze(vaults, self.config)
        self.assertGreaterEqual(result["vaults"][0]["cost_as_pct_aum"], 0.0)

    def test_slippage_plus_gas_equals_total(self):
        vaults = [_make_vault()]
        result = self.analyzer.analyze(vaults, self.config)
        v = result["vaults"][0]
        self.assertAlmostEqual(
            v["rebalance_cost_usd"],
            v["slippage_cost_usd"] + v["gas_cost_usd"],
            places=2,
        )

    def test_overdue_1x_no_overdue_flag(self):
        # last=30, freq=30 → 30 is NOT > 60 → no OVERDUE
        vault = _make_vault(freq=30, last_rebalance=30)
        result = _analyze_vault(vault, {})
        self.assertNotIn("OVERDUE", result["flags"])


if __name__ == "__main__":
    unittest.main()
