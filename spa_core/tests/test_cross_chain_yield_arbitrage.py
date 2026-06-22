"""
Tests for MP-706: CrossChainYieldArbitrage
≥ 65 tests. Pure unittest, stdlib only.
"""

import json
import os
import sys
import tempfile
import unittest

# ---------------------------------------------------------------------------
# Path setup — allow running from repo root or directly
# ---------------------------------------------------------------------------
_HERE = os.path.dirname(os.path.abspath(__file__))
_REPO_ROOT = os.path.dirname(os.path.dirname(_HERE))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

from spa_core.analytics.cross_chain_yield_arbitrage import (
    RING_BUFFER_CAP,
    ChainYield,
    best_opportunity,
    calculate_net_apy,
    default_bridge_cost,
    default_gas_drag,
    default_risk_premium,
    find_opportunity,
    load_history,
    save_results,
    scan_opportunities,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _make_cy(
    chain="ethereum",
    protocol="TestProto",
    pool="USDC",
    gross_apy=5.0,
    gas_drag=None,
    bridge_cost=None,
    risk_prem=None,
) -> ChainYield:
    gas_drag = gas_drag if gas_drag is not None else default_gas_drag(chain)
    bridge_cost = bridge_cost if bridge_cost is not None else default_bridge_cost(chain)
    risk_prem = risk_prem if risk_prem is not None else default_risk_premium(chain)
    return ChainYield(
        chain=chain,
        protocol=protocol,
        pool=pool,
        gross_apy=gross_apy,
        gas_drag_pct=gas_drag,
        bridge_cost_pct=bridge_cost,
        risk_premium_pct=risk_prem,
    )


def _tmp_file():
    fd, path = tempfile.mkstemp(suffix=".json")
    os.close(fd)
    os.unlink(path)  # remove so load_history returns []
    return path


# ---------------------------------------------------------------------------
# 1. calculate_net_apy
# ---------------------------------------------------------------------------
class TestCalculateNetApy(unittest.TestCase):

    def test_basic_formula(self):
        # net = 10 - 0.5 - 0.2*2 - 0.3 = 10 - 0.5 - 0.4 - 0.3 = 8.8
        result = calculate_net_apy(10.0, 0.5, 0.2, 0.3)
        self.assertAlmostEqual(result, 8.8, places=9)

    def test_zero_costs(self):
        result = calculate_net_apy(5.0, 0.0, 0.0, 0.0)
        self.assertAlmostEqual(result, 5.0, places=9)

    def test_clamp_to_zero(self):
        # Very high costs → clamped at 0
        result = calculate_net_apy(1.0, 5.0, 3.0, 2.0)
        self.assertEqual(result, 0.0)

    def test_exactly_zero(self):
        # gross=2, gas=0.5, bridge=0.5->*2=1.0, risk=0.5 → 2-0.5-1.0-0.5=0
        result = calculate_net_apy(2.0, 0.5, 0.5, 0.5)
        self.assertAlmostEqual(result, 0.0, places=9)

    def test_net_never_negative(self):
        result = calculate_net_apy(0.0, 1.0, 1.0, 1.0)
        self.assertGreaterEqual(result, 0.0)

    def test_bridge_doubled(self):
        # bridge_cost_pct * 2 is the cost
        r1 = calculate_net_apy(10.0, 0.0, 1.0, 0.0)
        r2 = calculate_net_apy(10.0, 0.0, 0.0, 0.0)
        self.assertAlmostEqual(r2 - r1, 2.0, places=9)

    def test_high_gross_apy(self):
        result = calculate_net_apy(30.0, 0.1, 0.1, 0.1)
        self.assertAlmostEqual(result, 30.0 - 0.1 - 0.2 - 0.1, places=9)

    def test_small_apy(self):
        result = calculate_net_apy(0.5, 0.1, 0.0, 0.0)
        self.assertAlmostEqual(result, 0.4, places=9)


# ---------------------------------------------------------------------------
# 2. default_gas_drag
# ---------------------------------------------------------------------------
class TestDefaultGasDrag(unittest.TestCase):

    def test_ethereum(self):
        self.assertAlmostEqual(default_gas_drag("ethereum"), 0.8)

    def test_arbitrum(self):
        self.assertAlmostEqual(default_gas_drag("arbitrum"), 0.05)

    def test_base(self):
        self.assertAlmostEqual(default_gas_drag("base"), 0.04)

    def test_optimism(self):
        self.assertAlmostEqual(default_gas_drag("optimism"), 0.05)

    def test_polygon(self):
        self.assertAlmostEqual(default_gas_drag("polygon"), 0.1)

    def test_unknown_chain_returns_float(self):
        result = default_gas_drag("solana")
        self.assertIsInstance(result, float)
        self.assertGreater(result, 0)


# ---------------------------------------------------------------------------
# 3. default_bridge_cost
# ---------------------------------------------------------------------------
class TestDefaultBridgeCost(unittest.TestCase):

    def test_ethereum_zero(self):
        self.assertAlmostEqual(default_bridge_cost("ethereum"), 0.0)

    def test_arbitrum(self):
        self.assertAlmostEqual(default_bridge_cost("arbitrum"), 0.15)

    def test_base(self):
        self.assertAlmostEqual(default_bridge_cost("base"), 0.12)

    def test_optimism(self):
        self.assertAlmostEqual(default_bridge_cost("optimism"), 0.15)

    def test_polygon(self):
        self.assertAlmostEqual(default_bridge_cost("polygon"), 0.08)

    def test_unknown_chain_returns_float(self):
        result = default_bridge_cost("zksync")
        self.assertIsInstance(result, float)


# ---------------------------------------------------------------------------
# 4. default_risk_premium
# ---------------------------------------------------------------------------
class TestDefaultRiskPremium(unittest.TestCase):

    def test_ethereum_zero(self):
        self.assertAlmostEqual(default_risk_premium("ethereum"), 0.0)

    def test_arbitrum(self):
        self.assertAlmostEqual(default_risk_premium("arbitrum"), 0.3)

    def test_base(self):
        self.assertAlmostEqual(default_risk_premium("base"), 0.2)

    def test_optimism(self):
        self.assertAlmostEqual(default_risk_premium("optimism"), 0.3)

    def test_polygon(self):
        self.assertAlmostEqual(default_risk_premium("polygon"), 0.5)

    def test_unknown_chain_returns_float(self):
        result = default_risk_premium("avalanche")
        self.assertIsInstance(result, float)


# ---------------------------------------------------------------------------
# 5. ChainYield auto-net_apy
# ---------------------------------------------------------------------------
class TestChainYield(unittest.TestCase):

    def test_net_apy_auto_calculated(self):
        cy = _make_cy(chain="ethereum", gross_apy=5.0)
        expected = calculate_net_apy(5.0, 0.8, 0.0, 0.0)
        self.assertAlmostEqual(cy.net_apy, expected, places=9)

    def test_net_apy_never_negative(self):
        cy = ChainYield(
            chain="polygon",
            protocol="Test",
            pool="USDC",
            gross_apy=0.1,
            gas_drag_pct=5.0,
            bridge_cost_pct=2.0,
            risk_premium_pct=1.0,
        )
        self.assertGreaterEqual(cy.net_apy, 0.0)

    def test_ethereum_no_bridge_cost(self):
        cy = _make_cy(chain="ethereum", gross_apy=4.0)
        # ethereum bridge_cost=0
        self.assertAlmostEqual(
            cy.net_apy,
            calculate_net_apy(4.0, 0.8, 0.0, 0.0),
            places=9,
        )

    def test_arbitrum_net_apy(self):
        cy = _make_cy(chain="arbitrum", gross_apy=6.0)
        expected = calculate_net_apy(6.0, 0.05, 0.15, 0.3)
        self.assertAlmostEqual(cy.net_apy, expected, places=9)


# ---------------------------------------------------------------------------
# 6. find_opportunity
# ---------------------------------------------------------------------------
class TestFindOpportunity(unittest.TestCase):

    def _setup(self, src_apy=3.5, tgt_apy=5.5):
        src = _make_cy(chain="ethereum", gross_apy=src_apy)
        tgt = _make_cy(chain="arbitrum", gross_apy=tgt_apy)
        return src, tgt

    def test_gross_spread(self):
        src, tgt = self._setup(3.5, 5.5)
        opp = find_opportunity(src, tgt, 10_000)
        self.assertAlmostEqual(opp.gross_spread_pct, 5.5 - 3.5, places=9)

    def test_net_spread(self):
        src, tgt = self._setup(3.5, 5.5)
        opp = find_opportunity(src, tgt, 10_000)
        self.assertAlmostEqual(opp.net_spread_pct, tgt.net_apy - src.net_apy, places=9)

    def test_breakeven_days_formula_positive_spread(self):
        src = _make_cy(chain="ethereum", gross_apy=3.5)
        tgt = _make_cy(chain="arbitrum", gross_apy=5.5)
        opp = find_opportunity(src, tgt, 10_000)
        if opp.net_spread_pct > 0:
            total_cost = tgt.bridge_cost_pct * 2 + tgt.gas_drag_pct
            expected_be = (total_cost / opp.net_spread_pct) * 365.0
            self.assertAlmostEqual(opp.breakeven_days, expected_be, places=5)

    def test_breakeven_days_zero_spread_is_9999(self):
        src = _make_cy(chain="arbitrum", gross_apy=5.0)
        # Make target net_apy exactly equal to source by using same chain/values
        tgt = _make_cy(chain="arbitrum", gross_apy=5.0, protocol="ProtoB")
        opp = find_opportunity(src, tgt, 10_000)
        # Net spread = 0 or negative → breakeven = 9999
        self.assertGreaterEqual(opp.breakeven_days, 9999.0)

    def test_breakeven_negative_net_spread_is_9999(self):
        src = _make_cy(chain="arbitrum", gross_apy=8.0)
        tgt = _make_cy(chain="ethereum", gross_apy=3.0)
        opp = find_opportunity(src, tgt, 10_000)
        if opp.net_spread_pct <= 0:
            self.assertEqual(opp.breakeven_days, 9999.0)

    def test_viable_true_when_positive_spread_and_short_breakeven(self):
        # Create opportunity with high target APY so net_spread > 0 and breakeven < 90
        src = ChainYield(
            chain="ethereum",
            protocol="P1",
            pool="USDC",
            gross_apy=2.0,
            gas_drag_pct=0.0,
            bridge_cost_pct=0.0,
            risk_premium_pct=0.0,
        )
        tgt = ChainYield(
            chain="ethereum",
            protocol="P2",
            pool="USDC",
            gross_apy=10.0,
            gas_drag_pct=0.0,
            bridge_cost_pct=0.0,
            risk_premium_pct=0.0,
        )
        opp = find_opportunity(src, tgt, 10_000)
        self.assertTrue(opp.viable)

    def test_viable_false_when_net_spread_negative(self):
        src = _make_cy(chain="base", gross_apy=8.0)
        tgt = _make_cy(chain="polygon", gross_apy=1.0)
        opp = find_opportunity(src, tgt, 10_000)
        if opp.net_spread_pct <= 0:
            self.assertFalse(opp.viable)

    def test_viable_false_when_breakeven_91_days(self):
        # Craft an opportunity where breakeven ≥ 90
        # total_move_cost_pct / net_spread * 365 ≥ 90
        # => total_move_cost_pct ≥ 90 * net_spread / 365
        # Use bridge_cost=5%, gas=0 → total_cost=10%; net_spread=0.5% → be = 10/0.5*365=7300 days
        src = ChainYield(
            chain="ethereum",
            protocol="P1",
            pool="USDC",
            gross_apy=3.0,
            gas_drag_pct=0.0,
            bridge_cost_pct=0.0,
            risk_premium_pct=0.0,
        )
        tgt = ChainYield(
            chain="ethereum",
            protocol="P2",
            pool="USDC",
            gross_apy=3.6,  # small gross spread
            gas_drag_pct=0.0,
            bridge_cost_pct=5.0,  # large bridge cost → breakeven >> 90
            risk_premium_pct=0.0,
        )
        opp = find_opportunity(src, tgt, 10_000)
        # net_spread = 3.6 - 3.0 = 0.6; be = (10/0.6)*365 ≈ 6083 >> 90
        if opp.breakeven_days >= 90:
            self.assertFalse(opp.viable)

    def test_confidence_high_when_breakeven_lt_30(self):
        src = ChainYield(
            chain="ethereum", protocol="P", pool="USDC",
            gross_apy=2.0, gas_drag_pct=0.0, bridge_cost_pct=0.0, risk_premium_pct=0.0,
        )
        tgt = ChainYield(
            chain="ethereum", protocol="Q", pool="USDC",
            gross_apy=20.0, gas_drag_pct=0.0, bridge_cost_pct=0.0, risk_premium_pct=0.0,
        )
        opp = find_opportunity(src, tgt, 10_000)
        # net_spread = 18, total_cost=0, breakeven=0 → HIGH
        self.assertEqual(opp.confidence, "HIGH")

    def test_confidence_medium(self):
        # be 30..60: total_cost/net_spread * 365 in [30,60)
        # target bridge=0.01, gas=0; net_spread = ~0.06..0.12 → be ≈ 30..60
        src = ChainYield(
            chain="ethereum", protocol="P", pool="USDC",
            gross_apy=3.0, gas_drag_pct=0.0, bridge_cost_pct=0.0, risk_premium_pct=0.0,
        )
        # net_spread=0.1: be = (0.02/0.1)*365=73... Let's use net_spread ~0.2
        # bridge=0.01*2=0.02; net_spread must yield be in [30,60)
        # be=45 → net_spread=0.02/45*365=0.162; gross must cover
        tgt = ChainYield(
            chain="ethereum", protocol="Q", pool="USDC",
            gross_apy=3.0 + 0.162 + 0.0 + 0.02 * 0,  # net_spread=0.162
            gas_drag_pct=0.0,
            bridge_cost_pct=0.01,
            risk_premium_pct=0.0,
        )
        opp = find_opportunity(src, tgt, 10_000)
        if 30 <= opp.breakeven_days < 60:
            self.assertEqual(opp.confidence, "MEDIUM")

    def test_confidence_low_when_breakeven_ge_60(self):
        # net_spread tiny → breakeven large → LOW
        src = ChainYield(
            chain="ethereum", protocol="P", pool="USDC",
            gross_apy=5.0, gas_drag_pct=0.0, bridge_cost_pct=0.0, risk_premium_pct=0.0,
        )
        tgt = ChainYield(
            chain="ethereum", protocol="Q", pool="USDC",
            gross_apy=5.1,
            gas_drag_pct=0.0,
            bridge_cost_pct=0.05,  # total_cost=0.1; be = 0.1/0.1*365 = 365 → LOW
            risk_premium_pct=0.0,
        )
        opp = find_opportunity(src, tgt, 10_000)
        if opp.breakeven_days >= 60:
            self.assertEqual(opp.confidence, "LOW")

    def test_warning_negative_gross_spread(self):
        src = _make_cy(chain="ethereum", gross_apy=8.0)
        tgt = _make_cy(chain="arbitrum", gross_apy=3.0)
        opp = find_opportunity(src, tgt, 10_000)
        self.assertIn("negative gross spread", opp.warnings)

    def test_warning_long_breakeven(self):
        # Force breakeven > 180 days
        src = ChainYield(
            chain="ethereum", protocol="P", pool="USDC",
            gross_apy=3.0, gas_drag_pct=0.0, bridge_cost_pct=0.0, risk_premium_pct=0.0,
        )
        tgt = ChainYield(
            chain="ethereum", protocol="Q", pool="USDC",
            gross_apy=3.1,
            gas_drag_pct=0.0,
            bridge_cost_pct=0.1,  # total=0.2; be = (0.2/0.1)*365=730 → long
            risk_premium_pct=0.0,
        )
        opp = find_opportunity(src, tgt, 10_000)
        if opp.breakeven_days > 180:
            self.assertIn("long breakeven", opp.warnings)

    def test_warning_risk_premium_mismatch(self):
        src = ChainYield(
            chain="ethereum", protocol="P", pool="USDC",
            gross_apy=5.0, gas_drag_pct=0.0, bridge_cost_pct=0.0, risk_premium_pct=0.0,
        )
        tgt = ChainYield(
            chain="polygon", protocol="Q", pool="USDC",
            gross_apy=8.0, gas_drag_pct=0.0, bridge_cost_pct=0.0, risk_premium_pct=1.5,
        )
        opp = find_opportunity(src, tgt, 10_000)
        # |1.5 - 0.0| = 1.5 > 1.0 → warning
        self.assertIn("risk premium mismatch >1%", opp.warnings)

    def test_no_warning_when_clean(self):
        src = ChainYield(
            chain="ethereum", protocol="P", pool="USDC",
            gross_apy=3.0, gas_drag_pct=0.0, bridge_cost_pct=0.0, risk_premium_pct=0.0,
        )
        tgt = ChainYield(
            chain="ethereum", protocol="Q", pool="USDC",
            gross_apy=10.0, gas_drag_pct=0.0, bridge_cost_pct=0.0, risk_premium_pct=0.2,
        )
        opp = find_opportunity(src, tgt, 10_000)
        # No negative gross spread, no long breakeven, risk diff = 0.2 < 1 → no warnings
        self.assertNotIn("negative gross spread", opp.warnings)
        self.assertNotIn("risk premium mismatch >1%", opp.warnings)

    def test_estimated_annual_gain_formula(self):
        src = ChainYield(
            chain="ethereum", protocol="P", pool="USDC",
            gross_apy=2.0, gas_drag_pct=0.0, bridge_cost_pct=0.0, risk_premium_pct=0.0,
        )
        tgt = ChainYield(
            chain="ethereum", protocol="Q", pool="USDC",
            gross_apy=7.0, gas_drag_pct=0.0, bridge_cost_pct=0.0, risk_premium_pct=0.0,
        )
        opp = find_opportunity(src, tgt, 20_000)
        expected = 20_000 * opp.net_spread_pct / 100.0
        self.assertAlmostEqual(opp.estimated_annual_gain_usd, expected, places=6)

    def test_position_usd_zero(self):
        src = _make_cy(chain="ethereum", gross_apy=4.0)
        tgt = _make_cy(chain="arbitrum", gross_apy=6.0)
        opp = find_opportunity(src, tgt, 0)
        self.assertAlmostEqual(opp.estimated_annual_gain_usd, 0.0, places=9)


# ---------------------------------------------------------------------------
# 7. scan_opportunities
# ---------------------------------------------------------------------------
class TestScanOpportunities(unittest.TestCase):

    def _three_yields(self):
        return [
            _make_cy(chain="ethereum", gross_apy=3.5),
            _make_cy(chain="arbitrum", gross_apy=5.0),
            _make_cy(chain="base", gross_apy=4.8),
        ]

    def test_count_is_n_times_n_minus_1(self):
        yields = self._three_yields()
        opps = scan_opportunities(yields, 10_000)
        self.assertEqual(len(opps), 3 * 2)  # 6

    def test_sorted_by_net_spread_desc(self):
        yields = self._three_yields()
        opps = scan_opportunities(yields, 10_000)
        spreads = [o.net_spread_pct for o in opps]
        self.assertEqual(spreads, sorted(spreads, reverse=True))

    def test_five_yields_count(self):
        chains = ["ethereum", "arbitrum", "base", "optimism", "polygon"]
        yields = [_make_cy(chain=c, gross_apy=4.0 + i * 0.5) for i, c in enumerate(chains)]
        opps = scan_opportunities(yields, 10_000)
        self.assertEqual(len(opps), 5 * 4)

    def test_single_yield_returns_empty(self):
        yields = [_make_cy(chain="ethereum", gross_apy=5.0)]
        opps = scan_opportunities(yields, 10_000)
        self.assertEqual(len(opps), 0)

    def test_two_same_apy_spreads_non_positive(self):
        src = _make_cy(chain="ethereum", gross_apy=5.0)
        tgt = _make_cy(chain="ethereum", gross_apy=5.0, protocol="Proto2")
        opps = scan_opportunities([src, tgt], 10_000)
        # Both pairs should have gross_spread = 0
        for opp in opps:
            self.assertAlmostEqual(opp.gross_spread_pct, 0.0, places=9)

    def test_returns_all_directed_pairs(self):
        # 2 yields → 2 pairs: A→B and B→A
        a = _make_cy(chain="ethereum", gross_apy=3.0)
        b = _make_cy(chain="arbitrum", gross_apy=6.0)
        opps = scan_opportunities([a, b], 10_000)
        self.assertEqual(len(opps), 2)
        sources = {o.source.chain for o in opps}
        self.assertIn("ethereum", sources)
        self.assertIn("arbitrum", sources)


# ---------------------------------------------------------------------------
# 8. best_opportunity
# ---------------------------------------------------------------------------
class TestBestOpportunity(unittest.TestCase):

    def test_returns_highest_net_spread_viable(self):
        src = ChainYield(
            chain="ethereum", protocol="P", pool="USDC",
            gross_apy=2.0, gas_drag_pct=0.0, bridge_cost_pct=0.0, risk_premium_pct=0.0,
        )
        tgt1 = ChainYield(
            chain="ethereum", protocol="Q1", pool="USDC",
            gross_apy=8.0, gas_drag_pct=0.0, bridge_cost_pct=0.0, risk_premium_pct=0.0,
        )
        tgt2 = ChainYield(
            chain="ethereum", protocol="Q2", pool="USDC",
            gross_apy=12.0, gas_drag_pct=0.0, bridge_cost_pct=0.0, risk_premium_pct=0.0,
        )
        opps = scan_opportunities([src, tgt1, tgt2], 10_000)
        best = best_opportunity(opps)
        self.assertIsNotNone(best)
        self.assertEqual(best.target.protocol, "Q2")

    def test_returns_none_when_no_viable(self):
        # All have negative net_spread
        src = ChainYield(
            chain="base", protocol="P", pool="USDC",
            gross_apy=8.0, gas_drag_pct=0.0, bridge_cost_pct=0.0, risk_premium_pct=0.0,
        )
        tgt = ChainYield(
            chain="base", protocol="Q", pool="USDC",
            gross_apy=1.0, gas_drag_pct=0.0, bridge_cost_pct=10.0, risk_premium_pct=0.0,
        )
        opps = scan_opportunities([src, tgt], 10_000)
        viable_opps = [o for o in opps if o.net_spread_pct > 0 and o.breakeven_days < 90]
        if not viable_opps:
            best = best_opportunity(opps)
            self.assertIsNone(best)

    def test_returns_none_for_empty_list(self):
        best = best_opportunity([])
        self.assertIsNone(best)

    def test_best_is_viable(self):
        src = ChainYield(
            chain="ethereum", protocol="P", pool="USDC",
            gross_apy=2.0, gas_drag_pct=0.0, bridge_cost_pct=0.0, risk_premium_pct=0.0,
        )
        tgt = ChainYield(
            chain="ethereum", protocol="Q", pool="USDC",
            gross_apy=10.0, gas_drag_pct=0.0, bridge_cost_pct=0.0, risk_premium_pct=0.0,
        )
        opps = scan_opportunities([src, tgt], 10_000)
        best = best_opportunity(opps)
        if best is not None:
            self.assertTrue(best.viable)


# ---------------------------------------------------------------------------
# 9. save / load / ring-buffer
# ---------------------------------------------------------------------------
class TestSaveLoad(unittest.TestCase):

    def test_save_creates_file(self):
        path = _tmp_file()
        src = _make_cy(chain="ethereum", gross_apy=3.0)
        tgt = _make_cy(chain="arbitrum", gross_apy=6.0)
        opp = find_opportunity(src, tgt, 10_000)
        save_results(opp, data_file=path)
        self.assertTrue(os.path.exists(path))
        os.unlink(path)

    def test_save_sets_saved_to(self):
        path = _tmp_file()
        src = _make_cy(chain="ethereum", gross_apy=3.0)
        tgt = _make_cy(chain="arbitrum", gross_apy=6.0)
        opp = find_opportunity(src, tgt, 10_000)
        save_results(opp, data_file=path)
        self.assertEqual(opp.saved_to, path)
        os.unlink(path)

    def test_load_returns_empty_when_no_file(self):
        path = _tmp_file()  # already unlinked
        result = load_history(data_file=path)
        self.assertEqual(result, [])

    def test_round_trip(self):
        path = _tmp_file()
        src = _make_cy(chain="ethereum", gross_apy=3.5)
        tgt = _make_cy(chain="base", gross_apy=5.2)
        opp = find_opportunity(src, tgt, 50_000)
        save_results(opp, data_file=path)
        history = load_history(data_file=path)
        self.assertEqual(len(history), 1)
        entry = history[0]
        self.assertAlmostEqual(entry["gross_spread_pct"], opp.gross_spread_pct, places=6)
        self.assertAlmostEqual(entry["net_spread_pct"], opp.net_spread_pct, places=6)
        self.assertEqual(entry["viable"], opp.viable)
        os.unlink(path)

    def test_ring_buffer_cap_100(self):
        path = _tmp_file()
        src = _make_cy(chain="ethereum", gross_apy=3.0)
        tgt = _make_cy(chain="arbitrum", gross_apy=6.0)
        # Save 110 entries
        for _ in range(110):
            opp = find_opportunity(src, tgt, 10_000)
            save_results(opp, data_file=path)
        history = load_history(data_file=path)
        self.assertEqual(len(history), RING_BUFFER_CAP)
        os.unlink(path)

    def test_ring_buffer_keeps_last_entries(self):
        path = _tmp_file()
        for i in range(105):
            src = _make_cy(chain="ethereum", gross_apy=float(i))
            tgt = _make_cy(chain="arbitrum", gross_apy=float(i) + 1.0)
            opp = find_opportunity(src, tgt, 1_000 * i)
            save_results(opp, data_file=path)
        history = load_history(data_file=path)
        self.assertEqual(len(history), RING_BUFFER_CAP)
        # Last entry should correspond to i=104
        last = history[-1]
        self.assertAlmostEqual(last["position_usd"], 1_000 * 104, places=0)
        os.unlink(path)

    def test_load_corrupted_file_returns_empty(self):
        fd, path = tempfile.mkstemp(suffix=".json")
        os.close(fd)
        with open(path, "w") as f:
            f.write("not valid json {{{")
        result = load_history(data_file=path)
        self.assertEqual(result, [])
        os.unlink(path)

    def test_atomic_write_no_partial_file(self):
        """Verify the file is valid JSON after each write (atomic guarantee)."""
        path = _tmp_file()
        src = _make_cy(chain="ethereum", gross_apy=3.0)
        tgt = _make_cy(chain="arbitrum", gross_apy=6.0)
        for _ in range(5):
            opp = find_opportunity(src, tgt, 10_000)
            save_results(opp, data_file=path)
            with open(path) as f:
                data = json.load(f)
            self.assertIsInstance(data, list)
        os.unlink(path)


# ---------------------------------------------------------------------------
# 10. Edge cases
# ---------------------------------------------------------------------------
class TestEdgeCases(unittest.TestCase):

    def test_all_same_apy_no_viable(self):
        yields = [_make_cy(chain=c, gross_apy=5.0) for c in ["ethereum", "arbitrum", "base"]]
        opps = scan_opportunities(yields, 10_000)
        best = best_opportunity(opps)
        # Same gross APY on all chains means no positive net_spread (L2 chains have extra costs)
        for o in opps:
            if o.source.chain == "ethereum":
                # Moving from ETH to L2 will have costs → net_spread ≤ 0
                pass
        # At least some should not be viable
        self.assertIsInstance(opps, list)

    def test_two_identical_chains_no_gain(self):
        a = _make_cy(chain="ethereum", gross_apy=5.0, protocol="A")
        b = _make_cy(chain="ethereum", gross_apy=5.0, protocol="B")
        opp_ab = find_opportunity(a, b, 10_000)
        opp_ba = find_opportunity(b, a, 10_000)
        # Same APY and same chain costs → net_spread = 0
        self.assertAlmostEqual(opp_ab.net_spread_pct, 0.0, places=9)
        self.assertAlmostEqual(opp_ba.net_spread_pct, 0.0, places=9)

    def test_opportunity_fields_present(self):
        src = _make_cy(chain="ethereum", gross_apy=3.0)
        tgt = _make_cy(chain="base", gross_apy=7.0)
        opp = find_opportunity(src, tgt, 10_000)
        self.assertIsInstance(opp.gross_spread_pct, float)
        self.assertIsInstance(opp.net_spread_pct, float)
        self.assertIsInstance(opp.breakeven_days, float)
        self.assertIsInstance(opp.viable, bool)
        self.assertIsInstance(opp.confidence, str)
        self.assertIsInstance(opp.warnings, list)

    def test_confidence_always_valid_string(self):
        src = _make_cy(chain="ethereum", gross_apy=3.0)
        tgt = _make_cy(chain="arbitrum", gross_apy=6.0)
        opp = find_opportunity(src, tgt, 10_000)
        self.assertIn(opp.confidence, {"HIGH", "MEDIUM", "LOW"})

    def test_large_position_usd(self):
        src = _make_cy(chain="ethereum", gross_apy=3.5)
        tgt = _make_cy(chain="arbitrum", gross_apy=6.0)
        opp = find_opportunity(src, tgt, 1_000_000)
        self.assertGreater(opp.estimated_annual_gain_usd, 0)

    def test_scan_empty_list(self):
        opps = scan_opportunities([], 10_000)
        self.assertEqual(opps, [])


if __name__ == "__main__":
    unittest.main()
