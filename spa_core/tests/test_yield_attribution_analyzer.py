"""
Tests for MP-740: YieldAttributionAnalyzer
≥65 unittest tests. Pure stdlib.
"""

import json
import os
import sys
import tempfile
import unittest

# ---------------------------------------------------------------------------
# Path setup
# ---------------------------------------------------------------------------

ROOT = os.path.join(os.path.dirname(__file__), "..", "..")
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from spa_core.analytics.yield_attribution_analyzer import (
    SUSTAINABILITY_MAP,
    SUSTAINABILITY_NOTES,
    YieldComponent,
    PositionAttribution,
    YieldAttributionResult,
    build_component,
    compute_sustainability_label,
    attribute_position,
    analyze_portfolio,
    save_results,
    load_history,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _simple_position(total_apy=10.0, allocation_pct=50.0, components=None):
    if components is None:
        components = [{"name": "BASE_RATE", "apy_contribution": 10.0}]
    return attribute_position(
        position_name="TestPos",
        protocol="TestProto",
        total_apy=total_apy,
        allocation_pct=allocation_pct,
        components_data=components,
    )


def _make_positions_data():
    return [
        {
            "position_name": "Aave USDC",
            "protocol": "Aave",
            "total_apy": 5.0,
            "allocation_pct": 60.0,
            "components": [
                {"name": "BASE_RATE", "apy_contribution": 4.0},
                {"name": "INCENTIVE_TOKENS", "apy_contribution": 1.0},
            ],
        },
        {
            "position_name": "Curve Pool",
            "protocol": "Curve",
            "total_apy": 10.0,
            "allocation_pct": 40.0,
            "components": [
                {"name": "TRADING_FEES", "apy_contribution": 2.0},
                {"name": "INCENTIVE_TOKENS", "apy_contribution": 8.0},
            ],
        },
    ]


# ===========================================================================
# 1. build_component — pct_of_total formula
# ===========================================================================

class TestBuildComponent(unittest.TestCase):

    def test_pct_of_total_formula(self):
        c = build_component("BASE_RATE", 4.0, 8.0)
        self.assertAlmostEqual(c.pct_of_total, 50.0)

    def test_pct_of_total_zero_total(self):
        c = build_component("BASE_RATE", 4.0, 0.0)
        self.assertEqual(c.pct_of_total, 0.0)

    def test_pct_of_total_full_contribution(self):
        c = build_component("BASE_RATE", 10.0, 10.0)
        self.assertAlmostEqual(c.pct_of_total, 100.0)

    def test_base_rate_is_sustainable(self):
        c = build_component("BASE_RATE", 5.0, 10.0)
        self.assertTrue(c.is_sustainable)

    def test_incentive_tokens_not_sustainable(self):
        c = build_component("INCENTIVE_TOKENS", 5.0, 10.0)
        self.assertFalse(c.is_sustainable)

    def test_leverage_not_sustainable(self):
        c = build_component("LEVERAGE", 5.0, 10.0)
        self.assertFalse(c.is_sustainable)

    def test_real_yield_is_sustainable(self):
        c = build_component("REAL_YIELD", 3.0, 10.0)
        self.assertTrue(c.is_sustainable)

    def test_trading_fees_is_sustainable(self):
        c = build_component("TRADING_FEES", 2.0, 10.0)
        self.assertTrue(c.is_sustainable)

    def test_name_preserved(self):
        c = build_component("LEVERAGE", 2.0, 4.0)
        self.assertEqual(c.name, "LEVERAGE")

    def test_apy_contribution_preserved(self):
        c = build_component("BASE_RATE", 3.5, 7.0)
        self.assertAlmostEqual(c.apy_contribution, 3.5)

    def test_sustainability_note_base_rate(self):
        c = build_component("BASE_RATE", 1.0, 5.0)
        self.assertIn("Organic", c.sustainability_note)

    def test_sustainability_note_incentive_tokens(self):
        c = build_component("INCENTIVE_TOKENS", 1.0, 5.0)
        self.assertIn("emission", c.sustainability_note)

    def test_sustainability_note_leverage(self):
        c = build_component("LEVERAGE", 1.0, 5.0)
        self.assertIn("Funding", c.sustainability_note)

    def test_sustainability_note_trading_fees(self):
        c = build_component("TRADING_FEES", 1.0, 5.0)
        self.assertIn("DEX", c.sustainability_note)

    def test_sustainability_note_real_yield(self):
        c = build_component("REAL_YIELD", 1.0, 5.0)
        self.assertIn("revenue", c.sustainability_note)

    def test_unknown_component_not_sustainable(self):
        c = build_component("UNKNOWN", 1.0, 5.0)
        self.assertFalse(c.is_sustainable)

    def test_unknown_component_note(self):
        c = build_component("UNKNOWN", 1.0, 5.0)
        self.assertEqual(c.sustainability_note, "Unknown source")

    def test_pct_partial(self):
        c = build_component("TRADING_FEES", 2.5, 10.0)
        self.assertAlmostEqual(c.pct_of_total, 25.0)

    def test_zero_contribution_zero_pct(self):
        c = build_component("BASE_RATE", 0.0, 10.0)
        self.assertAlmostEqual(c.pct_of_total, 0.0)


# ===========================================================================
# 2. compute_sustainability_label
# ===========================================================================

class TestComputeSustainabilityLabel(unittest.TestCase):

    def test_sustainable_above_70(self):
        self.assertEqual(compute_sustainability_label(80.0), "SUSTAINABLE")

    def test_sustainable_exactly_70_is_not(self):
        # >70 is SUSTAINABLE, so 70 is MIXED
        self.assertEqual(compute_sustainability_label(70.0), "MIXED")

    def test_mixed_at_55(self):
        self.assertEqual(compute_sustainability_label(55.0), "MIXED")

    def test_mixed_at_40(self):
        self.assertEqual(compute_sustainability_label(40.0), "MIXED")

    def test_fragile_below_40(self):
        self.assertEqual(compute_sustainability_label(39.9), "FRAGILE")

    def test_fragile_at_zero(self):
        self.assertEqual(compute_sustainability_label(0.0), "FRAGILE")

    def test_fragile_at_20(self):
        self.assertEqual(compute_sustainability_label(20.0), "FRAGILE")

    def test_sustainable_at_100(self):
        self.assertEqual(compute_sustainability_label(100.0), "SUSTAINABLE")

    def test_sustainable_at_71(self):
        self.assertEqual(compute_sustainability_label(71.0), "SUSTAINABLE")


# ===========================================================================
# 3. attribute_position
# ===========================================================================

class TestAttributePosition(unittest.TestCase):

    def test_sustainable_apy_sum(self):
        pos = attribute_position(
            "P1", "Proto",
            total_apy=10.0, allocation_pct=50.0,
            components_data=[
                {"name": "BASE_RATE", "apy_contribution": 7.0},
                {"name": "INCENTIVE_TOKENS", "apy_contribution": 3.0},
            ],
        )
        self.assertAlmostEqual(pos.sustainable_apy, 7.0)

    def test_unsustainable_apy_sum(self):
        pos = attribute_position(
            "P1", "Proto",
            total_apy=10.0, allocation_pct=50.0,
            components_data=[
                {"name": "BASE_RATE", "apy_contribution": 7.0},
                {"name": "INCENTIVE_TOKENS", "apy_contribution": 3.0},
            ],
        )
        self.assertAlmostEqual(pos.unsustainable_apy, 3.0)

    def test_sustainability_ratio_formula(self):
        pos = attribute_position(
            "P1", "Proto",
            total_apy=10.0, allocation_pct=50.0,
            components_data=[
                {"name": "BASE_RATE", "apy_contribution": 8.0},
                {"name": "LEVERAGE", "apy_contribution": 2.0},
            ],
        )
        self.assertAlmostEqual(pos.sustainability_ratio, 80.0)

    def test_weighted_contribution(self):
        pos = attribute_position(
            "P1", "Proto",
            total_apy=10.0, allocation_pct=30.0,
            components_data=[{"name": "BASE_RATE", "apy_contribution": 10.0}],
        )
        self.assertAlmostEqual(pos.weighted_contribution, 3.0)

    def test_sustainability_label_sustainable(self):
        pos = attribute_position(
            "P1", "Proto",
            total_apy=10.0, allocation_pct=100.0,
            components_data=[{"name": "BASE_RATE", "apy_contribution": 10.0}],
        )
        self.assertEqual(pos.sustainability_label, "SUSTAINABLE")

    def test_sustainability_label_fragile(self):
        pos = attribute_position(
            "P1", "Proto",
            total_apy=10.0, allocation_pct=100.0,
            components_data=[
                {"name": "INCENTIVE_TOKENS", "apy_contribution": 9.0},
                {"name": "BASE_RATE", "apy_contribution": 1.0},
            ],
        )
        self.assertEqual(pos.sustainability_label, "FRAGILE")

    def test_sustainability_label_mixed(self):
        pos = attribute_position(
            "P1", "Proto",
            total_apy=10.0, allocation_pct=100.0,
            components_data=[
                {"name": "BASE_RATE", "apy_contribution": 5.0},
                {"name": "INCENTIVE_TOKENS", "apy_contribution": 5.0},
            ],
        )
        self.assertEqual(pos.sustainability_label, "MIXED")

    def test_zero_total_apy_sustainability_ratio(self):
        pos = attribute_position(
            "P1", "Proto",
            total_apy=0.0, allocation_pct=100.0,
            components_data=[],
        )
        self.assertAlmostEqual(pos.sustainability_ratio, 100.0)

    def test_position_name_preserved(self):
        pos = _simple_position()
        self.assertEqual(pos.position_name, "TestPos")

    def test_protocol_preserved(self):
        pos = _simple_position()
        self.assertEqual(pos.protocol, "TestProto")

    def test_components_count(self):
        pos = attribute_position(
            "P1", "Proto", 10.0, 50.0,
            [
                {"name": "BASE_RATE", "apy_contribution": 5.0},
                {"name": "TRADING_FEES", "apy_contribution": 3.0},
                {"name": "INCENTIVE_TOKENS", "apy_contribution": 2.0},
            ],
        )
        self.assertEqual(len(pos.components), 3)

    def test_all_leverage_fragile(self):
        pos = attribute_position(
            "P1", "Proto", 20.0, 25.0,
            [{"name": "LEVERAGE", "apy_contribution": 20.0}],
        )
        self.assertEqual(pos.sustainability_label, "FRAGILE")

    def test_all_real_yield_sustainable(self):
        pos = attribute_position(
            "P1", "Proto", 8.0, 100.0,
            [{"name": "REAL_YIELD", "apy_contribution": 8.0}],
        )
        self.assertEqual(pos.sustainability_label, "SUSTAINABLE")

    def test_weighted_contribution_zero_alloc(self):
        pos = attribute_position("P1", "Proto", 10.0, 0.0, [])
        self.assertAlmostEqual(pos.weighted_contribution, 0.0)


# ===========================================================================
# 4. analyze_portfolio
# ===========================================================================

class TestAnalyzePortfolio(unittest.TestCase):

    def setUp(self):
        self.positions_data = _make_positions_data()

    def test_portfolio_total_apy_weighted_sum(self):
        result = analyze_portfolio(self.positions_data)
        # Aave: 5.0 * 0.6 = 3.0; Curve: 10.0 * 0.4 = 4.0; total = 7.0
        self.assertAlmostEqual(result.portfolio_total_apy, 7.0)

    def test_position_count(self):
        result = analyze_portfolio(self.positions_data)
        self.assertEqual(len(result.positions), 2)

    def test_portfolio_sustainability_ratio_formula(self):
        result = analyze_portfolio(self.positions_data)
        self.assertGreaterEqual(result.portfolio_sustainability_ratio, 0.0)
        self.assertLessEqual(result.portfolio_sustainability_ratio, 100.0)

    def test_source_breakdown_keys_present(self):
        result = analyze_portfolio(self.positions_data)
        self.assertIn("BASE_RATE", result.source_breakdown)
        self.assertIn("INCENTIVE_TOKENS", result.source_breakdown)
        self.assertIn("TRADING_FEES", result.source_breakdown)

    def test_source_breakdown_base_rate_value(self):
        result = analyze_portfolio(self.positions_data)
        # BASE_RATE: 4.0 * 0.6 = 2.4
        self.assertAlmostEqual(result.source_breakdown["BASE_RATE"], 2.4)

    def test_source_breakdown_trading_fees_value(self):
        result = analyze_portfolio(self.positions_data)
        # TRADING_FEES: 2.0 * 0.4 = 0.8
        self.assertAlmostEqual(result.source_breakdown["TRADING_FEES"], 0.8)

    def test_fragile_positions_identified(self):
        # Curve pool: 80% incentive → FRAGILE
        result = analyze_portfolio(self.positions_data)
        self.assertIn("Curve Pool", result.fragile_positions)

    def test_non_fragile_not_in_fragile_list(self):
        result = analyze_portfolio(self.positions_data)
        # Aave: 80% BASE_RATE → SUSTAINABLE
        self.assertNotIn("Aave USDC", result.fragile_positions)

    def test_portfolio_sustainability_label_type(self):
        result = analyze_portfolio(self.positions_data)
        self.assertIn(
            result.portfolio_sustainability_label,
            ["SUSTAINABLE", "MIXED", "FRAGILE"],
        )

    def test_recommendations_high_fragile_trigger(self):
        # Curve has 40% allocation, sustainability <40% → fragile_alloc = 40 > 30
        result = analyze_portfolio(self.positions_data)
        texts = " ".join(result.recommendations)
        self.assertIn("fragile", texts.lower())

    def test_recommendations_portfolio_heavy_unsustainable(self):
        # Force portfolio sustainability < 40%
        data = [
            {
                "position_name": "AllIncentive",
                "protocol": "Proto",
                "total_apy": 20.0,
                "allocation_pct": 100.0,
                "components": [{"name": "INCENTIVE_TOKENS", "apy_contribution": 20.0}],
            }
        ]
        result = analyze_portfolio(data)
        texts = " ".join(result.recommendations)
        self.assertIn("unsustainable", texts.lower())

    def test_single_position_portfolio(self):
        data = [
            {
                "position_name": "Solo",
                "protocol": "AaveV3",
                "total_apy": 6.0,
                "allocation_pct": 100.0,
                "components": [{"name": "BASE_RATE", "apy_contribution": 6.0}],
            }
        ]
        result = analyze_portfolio(data)
        self.assertAlmostEqual(result.portfolio_total_apy, 6.0)
        self.assertEqual(result.fragile_positions, [])

    def test_all_sustainable_no_fragile(self):
        data = [
            {
                "position_name": f"P{i}",
                "protocol": "A",
                "total_apy": 5.0,
                "allocation_pct": 50.0,
                "components": [{"name": "BASE_RATE", "apy_contribution": 5.0}],
            }
            for i in range(2)
        ]
        result = analyze_portfolio(data)
        self.assertEqual(result.fragile_positions, [])

    def test_all_incentive_all_fragile(self):
        data = [
            {
                "position_name": f"P{i}",
                "protocol": "A",
                "total_apy": 20.0,
                "allocation_pct": 50.0,
                "components": [{"name": "INCENTIVE_TOKENS", "apy_contribution": 20.0}],
            }
            for i in range(2)
        ]
        result = analyze_portfolio(data)
        self.assertEqual(len(result.fragile_positions), 2)

    def test_empty_portfolio(self):
        result = analyze_portfolio([])
        self.assertAlmostEqual(result.portfolio_total_apy, 0.0)
        self.assertEqual(result.fragile_positions, [])

    def test_portfolio_sustainable_apy_positive(self):
        result = analyze_portfolio(self.positions_data)
        self.assertGreaterEqual(result.portfolio_sustainable_apy, 0.0)

    def test_portfolio_unsustainable_apy_positive(self):
        result = analyze_portfolio(self.positions_data)
        self.assertGreaterEqual(result.portfolio_unsustainable_apy, 0.0)

    def test_fragile_no_recommendation_when_below_30pct(self):
        # Single position, 30% allocation but it's fragile → fragile_alloc = 30% NOT > 30
        data = [
            {
                "position_name": "SmallFragile",
                "protocol": "A",
                "total_apy": 20.0,
                "allocation_pct": 30.0,
                "components": [{"name": "INCENTIVE_TOKENS", "apy_contribution": 20.0}],
            },
            {
                "position_name": "LargeSafe",
                "protocol": "B",
                "total_apy": 4.0,
                "allocation_pct": 70.0,
                "components": [{"name": "BASE_RATE", "apy_contribution": 4.0}],
            },
        ]
        result = analyze_portfolio(data)
        # fragile_alloc = 30, which is NOT > 30, so no "fragile" recommendation
        fragile_texts = [r for r in result.recommendations if "fragile" in r.lower()]
        self.assertEqual(len(fragile_texts), 0)


# ===========================================================================
# 5. Persistence — save/load / ring-buffer
# ===========================================================================

class TestPersistence(unittest.TestCase):

    def setUp(self):
        self.tmp_dir = tempfile.mkdtemp()

    def _analyze_and_save(self):
        data = [
            {
                "position_name": "Solo",
                "protocol": "AaveV3",
                "total_apy": 6.0,
                "allocation_pct": 100.0,
                "components": [{"name": "BASE_RATE", "apy_contribution": 6.0}],
            }
        ]
        result = analyze_portfolio(data)
        save_results(result, self.tmp_dir)
        return result

    def test_save_creates_file(self):
        self._analyze_and_save()
        path = os.path.join(self.tmp_dir, "yield_attribution_log.json")
        self.assertTrue(os.path.exists(path))

    def test_load_empty_on_missing_file(self):
        history = load_history(self.tmp_dir)
        self.assertEqual(history, [])

    def test_save_load_round_trip(self):
        self._analyze_and_save()
        history = load_history(self.tmp_dir)
        self.assertEqual(len(history), 1)

    def test_multiple_saves(self):
        for _ in range(3):
            self._analyze_and_save()
        history = load_history(self.tmp_dir)
        self.assertEqual(len(history), 3)

    def test_ring_buffer_cap_100(self):
        for _ in range(110):
            self._analyze_and_save()
        history = load_history(self.tmp_dir)
        self.assertEqual(len(history), 100)

    def test_ring_buffer_keeps_latest(self):
        for i in range(105):
            data = [
                {
                    "position_name": f"P{i}",
                    "protocol": "A",
                    "total_apy": float(i),
                    "allocation_pct": 100.0,
                    "components": [{"name": "BASE_RATE", "apy_contribution": float(i)}],
                }
            ]
            result = analyze_portfolio(data)
            save_results(result, self.tmp_dir)
        history = load_history(self.tmp_dir)
        self.assertEqual(len(history), 100)

    def test_saved_to_set_after_save(self):
        result = self._analyze_and_save()
        self.assertTrue(result.saved_to.endswith("yield_attribution_log.json"))

    def test_save_returns_path(self):
        data = [
            {
                "position_name": "Solo",
                "protocol": "AaveV3",
                "total_apy": 6.0,
                "allocation_pct": 100.0,
                "components": [{"name": "BASE_RATE", "apy_contribution": 6.0}],
            }
        ]
        result = analyze_portfolio(data)
        path = save_results(result, self.tmp_dir)
        self.assertTrue(path.endswith("yield_attribution_log.json"))

    def test_load_corrupt_returns_empty(self):
        path = os.path.join(self.tmp_dir, "yield_attribution_log.json")
        with open(path, "w") as fh:
            fh.write("NOT JSON {{{")
        history = load_history(self.tmp_dir)
        self.assertEqual(history, [])

    def test_history_contains_timestamp(self):
        self._analyze_and_save()
        history = load_history(self.tmp_dir)
        self.assertIn("timestamp", history[0])

    def test_history_contains_portfolio_total_apy(self):
        self._analyze_and_save()
        history = load_history(self.tmp_dir)
        self.assertIn("portfolio_total_apy", history[0])

    def test_atomic_write_no_tmp_left(self):
        self._analyze_and_save()
        tmp = os.path.join(self.tmp_dir, "yield_attribution_log.json.tmp")
        self.assertFalse(os.path.exists(tmp))


if __name__ == "__main__":
    unittest.main()
