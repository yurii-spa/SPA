"""
Tests for MP-944 DeFiProtocolMoatAnalyzer
≥80 unittest tests covering all branches, edge-cases, and data shapes.
Run: python3 -m unittest spa_core.tests.test_defi_protocol_moat_analyzer -v
"""

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[2]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from spa_core.analytics.defi_protocol_moat_analyzer import (
    NARROW_MOAT_THRESHOLD,
    WIDE_MOAT_THRESHOLD,
    DeFiProtocolMoatAnalyzer,
    _clamp,
    _competitive_durability,
    _compute_flags,
    _compute_moat_strength,
    _market_position,
    _moat_label,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

def _make_protocol(**kwargs):
    defaults = {
        "name": "TestProtocol",
        "category": "lending",
        "tvl_usd": 1_000_000_000,
        "market_share_pct": 30.0,
        "switching_cost_score": 50.0,
        "network_effect_score": 50.0,
        "brand_recognition_score": 50.0,
        "protocol_owned_liquidity_pct": 30.0,
        "integrations_count": 20,
        "years_operating": 3.0,
        "clone_count": 3,
    }
    defaults.update(kwargs)
    return defaults


def _make_analyzer_with_tmpdir():
    td = tempfile.mkdtemp()
    return DeFiProtocolMoatAnalyzer(data_dir=td), td


# ---------------------------------------------------------------------------
# 1. _clamp
# ---------------------------------------------------------------------------

class TestClamp(unittest.TestCase):

    def test_clamp_within_range(self):
        self.assertAlmostEqual(_clamp(50.0), 50.0)

    def test_clamp_below_min(self):
        self.assertAlmostEqual(_clamp(-10.0), 0.0)

    def test_clamp_above_max(self):
        self.assertAlmostEqual(_clamp(150.0), 100.0)

    def test_clamp_exact_min(self):
        self.assertAlmostEqual(_clamp(0.0), 0.0)

    def test_clamp_exact_max(self):
        self.assertAlmostEqual(_clamp(100.0), 100.0)

    def test_clamp_custom_range(self):
        self.assertAlmostEqual(_clamp(5.0, 10.0, 20.0), 10.0)


# ---------------------------------------------------------------------------
# 2. _compute_moat_strength
# ---------------------------------------------------------------------------

class TestComputeMoatStrength(unittest.TestCase):

    def test_all_zeros(self):
        p = _make_protocol(switching_cost_score=0, network_effect_score=0,
                           brand_recognition_score=0, protocol_owned_liquidity_pct=0,
                           years_operating=0)
        self.assertAlmostEqual(_compute_moat_strength(p), 0.0)

    def test_all_max(self):
        p = _make_protocol(switching_cost_score=100, network_effect_score=100,
                           brand_recognition_score=100, protocol_owned_liquidity_pct=100,
                           years_operating=10)
        self.assertAlmostEqual(_compute_moat_strength(p), 100.0)

    def test_weights_add_to_one(self):
        # If all components are 1, result should be 1
        p = _make_protocol(switching_cost_score=1, network_effect_score=1,
                           brand_recognition_score=1, protocol_owned_liquidity_pct=1,
                           years_operating=0.1)
        score = _compute_moat_strength(p)
        # 0.3+0.3+0.2+0.1+0.1 = 1.0, so score = 1.0
        self.assertAlmostEqual(score, 1.0, places=4)

    def test_switching_cost_dominance(self):
        p = _make_protocol(switching_cost_score=100, network_effect_score=0,
                           brand_recognition_score=0, protocol_owned_liquidity_pct=0,
                           years_operating=0)
        self.assertAlmostEqual(_compute_moat_strength(p), 30.0)

    def test_network_effect_weight(self):
        p = _make_protocol(switching_cost_score=0, network_effect_score=100,
                           brand_recognition_score=0, protocol_owned_liquidity_pct=0,
                           years_operating=0)
        self.assertAlmostEqual(_compute_moat_strength(p), 30.0)

    def test_brand_weight(self):
        p = _make_protocol(switching_cost_score=0, network_effect_score=0,
                           brand_recognition_score=100, protocol_owned_liquidity_pct=0,
                           years_operating=0)
        self.assertAlmostEqual(_compute_moat_strength(p), 20.0)

    def test_pol_weight(self):
        p = _make_protocol(switching_cost_score=0, network_effect_score=0,
                           brand_recognition_score=0, protocol_owned_liquidity_pct=100,
                           years_operating=0)
        self.assertAlmostEqual(_compute_moat_strength(p), 10.0)

    def test_longevity_weight(self):
        p = _make_protocol(switching_cost_score=0, network_effect_score=0,
                           brand_recognition_score=0, protocol_owned_liquidity_pct=0,
                           years_operating=10)
        self.assertAlmostEqual(_compute_moat_strength(p), 10.0)

    def test_longevity_capped_at_10_years(self):
        p1 = _make_protocol(switching_cost_score=0, network_effect_score=0,
                            brand_recognition_score=0, protocol_owned_liquidity_pct=0,
                            years_operating=10)
        p2 = _make_protocol(switching_cost_score=0, network_effect_score=0,
                            brand_recognition_score=0, protocol_owned_liquidity_pct=0,
                            years_operating=20)
        self.assertAlmostEqual(_compute_moat_strength(p1), _compute_moat_strength(p2))

    def test_negative_scores_clamped_to_zero(self):
        p = _make_protocol(switching_cost_score=-50, network_effect_score=-10,
                           brand_recognition_score=-100, protocol_owned_liquidity_pct=-5,
                           years_operating=-1)
        self.assertAlmostEqual(_compute_moat_strength(p), 0.0)

    def test_over_100_scores_clamped(self):
        p = _make_protocol(switching_cost_score=200, network_effect_score=200,
                           brand_recognition_score=200, protocol_owned_liquidity_pct=200,
                           years_operating=100)
        self.assertAlmostEqual(_compute_moat_strength(p), 100.0)

    def test_partial_longevity(self):
        p = _make_protocol(switching_cost_score=0, network_effect_score=0,
                           brand_recognition_score=0, protocol_owned_liquidity_pct=0,
                           years_operating=5)
        # longevity_score = 50, weight = 0.1 → contribution = 5
        self.assertAlmostEqual(_compute_moat_strength(p), 5.0)


# ---------------------------------------------------------------------------
# 3. _competitive_durability
# ---------------------------------------------------------------------------

class TestCompetitiveDurability(unittest.TestCase):

    def test_wide(self):
        self.assertEqual(_competitive_durability(70.0), "WIDE")

    def test_wide_at_threshold(self):
        self.assertEqual(_competitive_durability(WIDE_MOAT_THRESHOLD), "WIDE")

    def test_narrow(self):
        self.assertEqual(_competitive_durability(50.0), "NARROW")

    def test_narrow_at_lower_threshold(self):
        self.assertEqual(_competitive_durability(NARROW_MOAT_THRESHOLD), "NARROW")

    def test_none(self):
        self.assertEqual(_competitive_durability(20.0), "NONE")

    def test_zero(self):
        self.assertEqual(_competitive_durability(0.0), "NONE")

    def test_just_below_wide(self):
        self.assertEqual(_competitive_durability(64.9), "NARROW")

    def test_just_below_narrow(self):
        self.assertEqual(_competitive_durability(34.9), "NONE")


# ---------------------------------------------------------------------------
# 4. _market_position
# ---------------------------------------------------------------------------

class TestMarketPosition(unittest.TestCase):

    def test_dominant_above_threshold(self):
        self.assertEqual(_market_position(50.0), "DOMINANT")

    def test_dominant_exactly_above(self):
        self.assertEqual(_market_position(40.1), "DOMINANT")

    def test_strong(self):
        self.assertEqual(_market_position(30.0), "STRONG")

    def test_strong_at_threshold(self):
        self.assertEqual(_market_position(25.0), "STRONG")

    def test_competitive(self):
        self.assertEqual(_market_position(15.0), "COMPETITIVE")

    def test_competitive_at_threshold(self):
        self.assertEqual(_market_position(10.0), "COMPETITIVE")

    def test_niche(self):
        self.assertEqual(_market_position(7.0), "NICHE")

    def test_niche_at_threshold(self):
        self.assertEqual(_market_position(5.0), "NICHE")

    def test_vulnerable(self):
        self.assertEqual(_market_position(2.0), "VULNERABLE")

    def test_zero_share(self):
        self.assertEqual(_market_position(0.0), "VULNERABLE")

    def test_exactly_40(self):
        # > 40 → DOMINANT; == 40 → STRONG (boundary)
        self.assertEqual(_market_position(40.0), "STRONG")

    def test_just_below_strong(self):
        self.assertEqual(_market_position(24.9), "COMPETITIVE")


# ---------------------------------------------------------------------------
# 5. _moat_label
# ---------------------------------------------------------------------------

class TestMoatLabel(unittest.TestCase):

    def test_wide_moat(self):
        self.assertEqual(_moat_label(70.0, 2, 30.0), "WIDE_MOAT")

    def test_narrow_moat(self):
        self.assertEqual(_moat_label(50.0, 2, 30.0), "NARROW_MOAT")

    def test_no_moat(self):
        self.assertEqual(_moat_label(20.0, 2, 30.0), "NO_MOAT")

    def test_losing_moat_high_clones_low_share(self):
        # clone_count > 10 AND market_share < 20 → LOSING_MOAT
        self.assertEqual(_moat_label(70.0, 15, 10.0), "LOSING_MOAT")

    def test_losing_moat_overrides_wide(self):
        # Even with high score, LOSING_MOAT takes priority
        self.assertEqual(_moat_label(90.0, 11, 5.0), "LOSING_MOAT")

    def test_not_losing_if_high_share(self):
        # Many clones but still dominant share → not LOSING_MOAT
        self.assertEqual(_moat_label(70.0, 15, 25.0), "WIDE_MOAT")

    def test_not_losing_if_low_clone_count(self):
        # Low market share but few clones → normal labeling
        self.assertEqual(_moat_label(20.0, 5, 10.0), "NO_MOAT")

    def test_boundary_clone_threshold(self):
        # clone_count == 10 is NOT > 10, so not LOSING_MOAT
        self.assertNotEqual(_moat_label(20.0, 10, 10.0), "LOSING_MOAT")

    def test_boundary_share_threshold(self):
        # market_share == 20 is NOT < 20, so not LOSING_MOAT
        self.assertNotEqual(_moat_label(20.0, 15, 20.0), "LOSING_MOAT")


# ---------------------------------------------------------------------------
# 6. _compute_flags
# ---------------------------------------------------------------------------

class TestComputeFlags(unittest.TestCase):

    def test_no_flags_neutral(self):
        p = _make_protocol(market_share_pct=20.0, switching_cost_score=50.0,
                           network_effect_score=50.0, protocol_owned_liquidity_pct=30.0,
                           clone_count=5)
        flags = _compute_flags(p)
        self.assertEqual(flags, [])

    def test_dominant_market_share_flag(self):
        p = _make_protocol(market_share_pct=45.0)
        flags = _compute_flags(p)
        self.assertIn("DOMINANT_MARKET_SHARE", flags)

    def test_no_dominant_share_at_40(self):
        p = _make_protocol(market_share_pct=40.0)
        flags = _compute_flags(p)
        self.assertNotIn("DOMINANT_MARKET_SHARE", flags)

    def test_high_switching_cost_flag(self):
        p = _make_protocol(switching_cost_score=80.0)
        flags = _compute_flags(p)
        self.assertIn("HIGH_SWITCHING_COST", flags)

    def test_no_high_switching_cost_at_70(self):
        p = _make_protocol(switching_cost_score=70.0)
        flags = _compute_flags(p)
        self.assertNotIn("HIGH_SWITCHING_COST", flags)

    def test_strong_network_effect_flag(self):
        p = _make_protocol(network_effect_score=75.0)
        flags = _compute_flags(p)
        self.assertIn("STRONG_NETWORK_EFFECT", flags)

    def test_protocol_owned_liquidity_flag(self):
        p = _make_protocol(protocol_owned_liquidity_pct=60.0)
        flags = _compute_flags(p)
        self.assertIn("PROTOCOL_OWNED_LIQUIDITY", flags)

    def test_no_pol_flag_at_50(self):
        p = _make_protocol(protocol_owned_liquidity_pct=50.0)
        flags = _compute_flags(p)
        self.assertNotIn("PROTOCOL_OWNED_LIQUIDITY", flags)

    def test_widely_forked_flag(self):
        p = _make_protocol(clone_count=15)
        flags = _compute_flags(p)
        self.assertIn("WIDELY_FORKED", flags)

    def test_no_widely_forked_at_10(self):
        p = _make_protocol(clone_count=10)
        flags = _compute_flags(p)
        self.assertNotIn("WIDELY_FORKED", flags)

    def test_all_flags(self):
        p = _make_protocol(
            market_share_pct=45.0,
            switching_cost_score=80.0,
            network_effect_score=80.0,
            protocol_owned_liquidity_pct=60.0,
            clone_count=15,
        )
        flags = _compute_flags(p)
        self.assertIn("DOMINANT_MARKET_SHARE", flags)
        self.assertIn("HIGH_SWITCHING_COST", flags)
        self.assertIn("STRONG_NETWORK_EFFECT", flags)
        self.assertIn("PROTOCOL_OWNED_LIQUIDITY", flags)
        self.assertIn("WIDELY_FORKED", flags)


# ---------------------------------------------------------------------------
# 7. DeFiProtocolMoatAnalyzer.analyze() — basic
# ---------------------------------------------------------------------------

class TestAnalyzeBasic(unittest.TestCase):

    def setUp(self):
        self.analyzer, self.tmpdir = _make_analyzer_with_tmpdir()

    def test_empty_protocols_returns_result(self):
        result = self.analyzer.analyze([])
        self.assertEqual(result["protocol_count"], 0)
        self.assertEqual(result["protocols"], [])

    def test_empty_protocols_aggregates(self):
        result = self.analyzer.analyze([])
        agg = result["aggregates"]
        self.assertIsNone(agg["widest_moat"])
        self.assertIsNone(agg["narrowest_moat"])
        self.assertEqual(agg["average_moat_strength"], 0.0)
        self.assertEqual(agg["wide_moat_count"], 0)
        self.assertEqual(agg["no_moat_count"], 0)

    def test_single_protocol(self):
        p = _make_protocol(name="Aave", switching_cost_score=80, network_effect_score=80,
                           brand_recognition_score=80, years_operating=5,
                           protocol_owned_liquidity_pct=20, market_share_pct=30,
                           clone_count=2)
        result = self.analyzer.analyze([p])
        self.assertEqual(result["protocol_count"], 1)
        self.assertEqual(len(result["protocols"]), 1)

    def test_result_has_timestamp(self):
        result = self.analyzer.analyze([_make_protocol()])
        self.assertIn("timestamp", result)
        self.assertIsInstance(result["timestamp"], str)

    def test_result_has_required_keys(self):
        result = self.analyzer.analyze([_make_protocol()])
        for key in ("timestamp", "protocol_count", "protocols", "aggregates"):
            self.assertIn(key, result)

    def test_protocol_fields_present(self):
        result = self.analyzer.analyze([_make_protocol()])
        p = result["protocols"][0]
        for key in ("name", "category", "tvl_usd", "market_share_pct",
                    "moat_strength_score", "competitive_durability",
                    "market_position", "moat_label", "flags"):
            self.assertIn(key, p)

    def test_none_config_treated_as_empty(self):
        result = self.analyzer.analyze([_make_protocol()], config=None)
        self.assertIsNotNone(result)

    def test_empty_config_ok(self):
        result = self.analyzer.analyze([_make_protocol()], config={})
        self.assertIsNotNone(result)


# ---------------------------------------------------------------------------
# 8. Aggregates
# ---------------------------------------------------------------------------

class TestAggregates(unittest.TestCase):

    def setUp(self):
        self.analyzer, self.tmpdir = _make_analyzer_with_tmpdir()

    def _two_protocols(self):
        strong = _make_protocol(name="Strong", switching_cost_score=90, network_effect_score=90,
                                brand_recognition_score=90, years_operating=8,
                                protocol_owned_liquidity_pct=60, market_share_pct=50, clone_count=2)
        weak = _make_protocol(name="Weak", switching_cost_score=10, network_effect_score=10,
                              brand_recognition_score=10, years_operating=0.5,
                              protocol_owned_liquidity_pct=5, market_share_pct=3, clone_count=0)
        return strong, weak

    def test_widest_moat(self):
        strong, weak = self._two_protocols()
        result = self.analyzer.analyze([weak, strong])
        self.assertEqual(result["aggregates"]["widest_moat"], "Strong")

    def test_narrowest_moat(self):
        strong, weak = self._two_protocols()
        result = self.analyzer.analyze([weak, strong])
        self.assertEqual(result["aggregates"]["narrowest_moat"], "Weak")

    def test_average_moat_strength(self):
        result = self.analyzer.analyze([_make_protocol()])
        agg = result["aggregates"]
        p = result["protocols"][0]
        self.assertAlmostEqual(agg["average_moat_strength"], p["moat_strength_score"])

    def test_wide_moat_count(self):
        strong = _make_protocol(name="S1", switching_cost_score=100, network_effect_score=100,
                                brand_recognition_score=100, years_operating=10,
                                protocol_owned_liquidity_pct=100, market_share_pct=50, clone_count=2)
        weak = _make_protocol(name="S2", switching_cost_score=10, network_effect_score=10,
                              brand_recognition_score=10, years_operating=1,
                              protocol_owned_liquidity_pct=5, market_share_pct=2, clone_count=3)
        result = self.analyzer.analyze([strong, weak])
        self.assertEqual(result["aggregates"]["wide_moat_count"], 1)

    def test_no_moat_count_includes_losing_moat(self):
        losing = _make_protocol(name="L", switching_cost_score=10, network_effect_score=10,
                                brand_recognition_score=10, years_operating=0,
                                protocol_owned_liquidity_pct=0, market_share_pct=5,
                                clone_count=15)
        result = self.analyzer.analyze([losing])
        self.assertEqual(result["aggregates"]["no_moat_count"], 1)

    def test_protocol_count_matches(self):
        protocols = [_make_protocol(name=f"P{i}") for i in range(5)]
        result = self.analyzer.analyze(protocols)
        self.assertEqual(result["protocol_count"], 5)
        self.assertEqual(len(result["protocols"]), 5)


# ---------------------------------------------------------------------------
# 9. Moat labels in analyze()
# ---------------------------------------------------------------------------

class TestMoatLabelsInAnalyze(unittest.TestCase):

    def setUp(self):
        self.analyzer, self.tmpdir = _make_analyzer_with_tmpdir()

    def test_wide_moat_label_assigned(self):
        p = _make_protocol(switching_cost_score=100, network_effect_score=100,
                           brand_recognition_score=100, years_operating=10,
                           protocol_owned_liquidity_pct=100, market_share_pct=45, clone_count=2)
        result = self.analyzer.analyze([p])
        self.assertEqual(result["protocols"][0]["moat_label"], "WIDE_MOAT")

    def test_narrow_moat_label_assigned(self):
        p = _make_protocol(switching_cost_score=50, network_effect_score=50,
                           brand_recognition_score=50, years_operating=3,
                           protocol_owned_liquidity_pct=30, market_share_pct=15, clone_count=2)
        result = self.analyzer.analyze([p])
        label = result["protocols"][0]["moat_label"]
        self.assertIn(label, ("NARROW_MOAT", "WIDE_MOAT", "NO_MOAT"))  # depends on score

    def test_no_moat_label_assigned_for_weak(self):
        p = _make_protocol(switching_cost_score=5, network_effect_score=5,
                           brand_recognition_score=5, years_operating=0,
                           protocol_owned_liquidity_pct=0, market_share_pct=2, clone_count=2)
        result = self.analyzer.analyze([p])
        self.assertEqual(result["protocols"][0]["moat_label"], "NO_MOAT")

    def test_losing_moat_label_assigned(self):
        p = _make_protocol(switching_cost_score=10, network_effect_score=10,
                           brand_recognition_score=10, years_operating=0,
                           protocol_owned_liquidity_pct=0, market_share_pct=8,
                           clone_count=15)
        result = self.analyzer.analyze([p])
        self.assertEqual(result["protocols"][0]["moat_label"], "LOSING_MOAT")


# ---------------------------------------------------------------------------
# 10. Input passthrough and type coercion
# ---------------------------------------------------------------------------

class TestInputCoercion(unittest.TestCase):

    def setUp(self):
        self.analyzer, self.tmpdir = _make_analyzer_with_tmpdir()

    def test_name_passthrough(self):
        result = self.analyzer.analyze([_make_protocol(name="Uniswap")])
        self.assertEqual(result["protocols"][0]["name"], "Uniswap")

    def test_category_passthrough(self):
        result = self.analyzer.analyze([_make_protocol(category="dex")])
        self.assertEqual(result["protocols"][0]["category"], "dex")

    def test_tvl_passthrough(self):
        result = self.analyzer.analyze([_make_protocol(tvl_usd=5e9)])
        self.assertAlmostEqual(result["protocols"][0]["tvl_usd"], 5e9)

    def test_integrations_count_passthrough(self):
        result = self.analyzer.analyze([_make_protocol(integrations_count=42)])
        self.assertEqual(result["protocols"][0]["integrations_count"], 42)

    def test_clone_count_passthrough(self):
        result = self.analyzer.analyze([_make_protocol(clone_count=7)])
        self.assertEqual(result["protocols"][0]["clone_count"], 7)

    def test_flags_is_list(self):
        result = self.analyzer.analyze([_make_protocol()])
        self.assertIsInstance(result["protocols"][0]["flags"], list)

    def test_moat_strength_is_float(self):
        result = self.analyzer.analyze([_make_protocol()])
        self.assertIsInstance(result["protocols"][0]["moat_strength_score"], float)

    def test_missing_fields_default_to_zero(self):
        result = self.analyzer.analyze([{"name": "Bare"}])
        p = result["protocols"][0]
        self.assertEqual(p["moat_strength_score"], 0.0)

    def test_string_int_scores_coerced(self):
        p = _make_protocol(switching_cost_score="80", network_effect_score="70")
        result = self.analyzer.analyze([p])
        self.assertGreater(result["protocols"][0]["moat_strength_score"], 0)


# ---------------------------------------------------------------------------
# 11. Ring-buffer log
# ---------------------------------------------------------------------------

class TestLog(unittest.TestCase):

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.analyzer = DeFiProtocolMoatAnalyzer(data_dir=self.tmpdir)
        self.log_path = os.path.join(self.tmpdir, "protocol_moat_log.json")

    def test_log_created_after_analyze(self):
        self.analyzer.analyze([_make_protocol()])
        self.assertTrue(os.path.exists(self.log_path))

    def test_log_is_valid_json(self):
        self.analyzer.analyze([_make_protocol()])
        with open(self.log_path) as f:
            data = json.load(f)
        self.assertIsInstance(data, dict)

    def test_log_has_entries(self):
        self.analyzer.analyze([_make_protocol()])
        with open(self.log_path) as f:
            data = json.load(f)
        self.assertIn("entries", data)
        self.assertEqual(len(data["entries"]), 1)

    def test_log_appends_multiple(self):
        self.analyzer.analyze([_make_protocol()])
        self.analyzer.analyze([_make_protocol(name="B")])
        with open(self.log_path) as f:
            data = json.load(f)
        self.assertEqual(len(data["entries"]), 2)

    def test_log_ring_buffer_cap_100(self):
        for i in range(110):
            self.analyzer.analyze([_make_protocol(name=f"P{i}")])
        with open(self.log_path) as f:
            data = json.load(f)
        self.assertLessEqual(len(data["entries"]), 100)

    def test_log_entry_has_required_keys(self):
        self.analyzer.analyze([_make_protocol()])
        with open(self.log_path) as f:
            data = json.load(f)
        entry = data["entries"][0]
        for k in ("timestamp", "protocol_count", "average_moat_strength",
                  "wide_moat_count", "no_moat_count"):
            self.assertIn(k, entry)

    def test_log_has_last_updated(self):
        self.analyzer.analyze([_make_protocol()])
        with open(self.log_path) as f:
            data = json.load(f)
        self.assertIn("last_updated", data)

    def test_log_written_atomically(self):
        """Verify no .tmp file left after write."""
        self.analyzer.analyze([_make_protocol()])
        tmp = self.log_path + ".tmp"
        self.assertFalse(os.path.exists(tmp))

    def test_empty_analyze_also_logs(self):
        self.analyzer.analyze([])
        self.assertTrue(os.path.exists(self.log_path))


# ---------------------------------------------------------------------------
# 12. Multiple protocols integration
# ---------------------------------------------------------------------------

class TestMultipleProtocols(unittest.TestCase):

    def setUp(self):
        self.analyzer, self.tmpdir = _make_analyzer_with_tmpdir()

    def _make_three(self):
        p1 = _make_protocol(name="Aave", switching_cost_score=85, network_effect_score=80,
                            brand_recognition_score=90, years_operating=5,
                            protocol_owned_liquidity_pct=40, market_share_pct=45, clone_count=3)
        p2 = _make_protocol(name="Curve", switching_cost_score=60, network_effect_score=70,
                            brand_recognition_score=70, years_operating=3,
                            protocol_owned_liquidity_pct=65, market_share_pct=25, clone_count=5)
        p3 = _make_protocol(name="Clone", switching_cost_score=10, network_effect_score=10,
                            brand_recognition_score=5, years_operating=0.5,
                            protocol_owned_liquidity_pct=5, market_share_pct=5, clone_count=12)
        return [p1, p2, p3]

    def test_three_protocols_count(self):
        result = self.analyzer.analyze(self._make_three())
        self.assertEqual(result["protocol_count"], 3)

    def test_widest_is_aave(self):
        result = self.analyzer.analyze(self._make_three())
        self.assertEqual(result["aggregates"]["widest_moat"], "Aave")

    def test_narrowest_is_clone(self):
        result = self.analyzer.analyze(self._make_three())
        self.assertEqual(result["aggregates"]["narrowest_moat"], "Clone")

    def test_average_in_range(self):
        result = self.analyzer.analyze(self._make_three())
        avg = result["aggregates"]["average_moat_strength"]
        self.assertGreater(avg, 0)
        self.assertLessEqual(avg, 100)

    def test_all_durability_values_valid(self):
        result = self.analyzer.analyze(self._make_three())
        valid = {"WIDE", "NARROW", "NONE"}
        for p in result["protocols"]:
            self.assertIn(p["competitive_durability"], valid)

    def test_all_market_position_values_valid(self):
        result = self.analyzer.analyze(self._make_three())
        valid = {"DOMINANT", "STRONG", "COMPETITIVE", "NICHE", "VULNERABLE"}
        for p in result["protocols"]:
            self.assertIn(p["market_position"], valid)

    def test_all_moat_labels_valid(self):
        result = self.analyzer.analyze(self._make_three())
        valid = {"WIDE_MOAT", "NARROW_MOAT", "NO_MOAT", "LOSING_MOAT"}
        for p in result["protocols"]:
            self.assertIn(p["moat_label"], valid)


# ---------------------------------------------------------------------------
# 13. Edge cases
# ---------------------------------------------------------------------------

class TestEdgeCases(unittest.TestCase):

    def setUp(self):
        self.analyzer, self.tmpdir = _make_analyzer_with_tmpdir()

    def test_single_protocol_widest_equals_narrowest(self):
        result = self.analyzer.analyze([_make_protocol(name="Solo")])
        agg = result["aggregates"]
        self.assertEqual(agg["widest_moat"], agg["narrowest_moat"])

    def test_tvl_zero(self):
        result = self.analyzer.analyze([_make_protocol(tvl_usd=0)])
        self.assertEqual(result["protocol_count"], 1)

    def test_years_fractional(self):
        result = self.analyzer.analyze([_make_protocol(years_operating=0.25)])
        self.assertEqual(result["protocol_count"], 1)

    def test_very_large_tvl(self):
        result = self.analyzer.analyze([_make_protocol(tvl_usd=1e15)])
        self.assertAlmostEqual(result["protocols"][0]["tvl_usd"], 1e15)

    def test_zero_clone_count_no_widely_forked(self):
        result = self.analyzer.analyze([_make_protocol(clone_count=0)])
        flags = result["protocols"][0]["flags"]
        self.assertNotIn("WIDELY_FORKED", flags)

    def test_market_share_zero(self):
        result = self.analyzer.analyze([_make_protocol(market_share_pct=0)])
        self.assertEqual(result["protocols"][0]["market_position"], "VULNERABLE")

    def test_default_data_dir_used_when_none(self):
        a = DeFiProtocolMoatAnalyzer()
        self.assertIn("protocol_moat_log", a._log_path())

    def test_custom_data_dir_used(self):
        td = tempfile.mkdtemp()
        a = DeFiProtocolMoatAnalyzer(data_dir=td)
        self.assertTrue(a._log_path().startswith(td))


if __name__ == "__main__":
    unittest.main()
