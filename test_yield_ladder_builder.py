"""
Tests for MP-764: YieldLadderBuilder  (≥65 tests)
Pure stdlib unittest — no pytest dependency.
"""
import json
import os
import tempfile
import time
import unittest
from pathlib import Path

from spa_core.analytics.yield_ladder_builder import (
    LadderRung,
    LadderSnapshot,
    YieldLadderBuilder,
    TIER_RISK_WEIGHTS,
    KNOWN_TIERS,
    MAX_ENTRIES,
)

EPS = 1e-6


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _builder() -> YieldLadderBuilder:
    """Create a builder with an isolated temp file."""
    fd, path = tempfile.mkstemp(suffix=".json")
    os.close(fd)
    os.unlink(path)
    return YieldLadderBuilder(data_file=Path(path))


def _proto(protocol: str, tier: str, apy: float) -> dict:
    return {"protocol": protocol, "tier": tier, "apy": apy}


SAMPLE_PROTOCOLS = [
    _proto("Aave V3",    "T1", 0.035),
    _proto("Compound V3","T1", 0.048),
    _proto("Morpho",     "T2", 0.065),
    _proto("Euler V2",   "T2", 0.072),
    _proto("Pendle PT",  "T3", 0.120),
]
SAMPLE_ALLOC   = {"T1": 0.50, "T2": 0.30, "T3": 0.20}
SAMPLE_CAPITAL = 100_000.0


# ===========================================================================
# 1. Basic build_ladder behaviour
# ===========================================================================

class TestBuildLadderBasic(unittest.TestCase):

    def setUp(self):
        self.b = _builder()

    def test_returns_ladder_snapshot(self):
        s = self.b.build_ladder(SAMPLE_PROTOCOLS, SAMPLE_CAPITAL, SAMPLE_ALLOC)
        self.assertIsInstance(s, LadderSnapshot)

    def test_timestamp_is_set(self):
        before = time.time()
        s = self.b.build_ladder(SAMPLE_PROTOCOLS, SAMPLE_CAPITAL, SAMPLE_ALLOC)
        self.assertGreaterEqual(s.timestamp, before)

    def test_capital_preserved(self):
        s = self.b.build_ladder(SAMPLE_PROTOCOLS, SAMPLE_CAPITAL, SAMPLE_ALLOC)
        self.assertAlmostEqual(s.capital, SAMPLE_CAPITAL, places=6)

    def test_target_allocation_preserved(self):
        s = self.b.build_ladder(SAMPLE_PROTOCOLS, SAMPLE_CAPITAL, SAMPLE_ALLOC)
        self.assertEqual(s.target_allocation, SAMPLE_ALLOC)

    def test_correct_rung_count(self):
        # 2 T1 + 2 T2 + 1 T3 = 5 rungs
        s = self.b.build_ladder(SAMPLE_PROTOCOLS, SAMPLE_CAPITAL, SAMPLE_ALLOC)
        self.assertEqual(len(s.rungs), 5)

    def test_blended_apy_positive(self):
        s = self.b.build_ladder(SAMPLE_PROTOCOLS, SAMPLE_CAPITAL, SAMPLE_ALLOC)
        self.assertGreater(s.blended_apy, 0.0)

    def test_blended_apy_not_exceed_max_apy(self):
        max_apy = max(p["apy"] for p in SAMPLE_PROTOCOLS)
        s = self.b.build_ladder(SAMPLE_PROTOCOLS, SAMPLE_CAPITAL, SAMPLE_ALLOC)
        self.assertLessEqual(s.blended_apy, max_apy + EPS)

    def test_ladder_score_in_range(self):
        s = self.b.build_ladder(SAMPLE_PROTOCOLS, SAMPLE_CAPITAL, SAMPLE_ALLOC)
        self.assertGreaterEqual(s.ladder_score, 0.0)
        self.assertLessEqual(s.ladder_score, 100.0)

    def test_tier_risk_adjusted_yield_positive(self):
        s = self.b.build_ladder(SAMPLE_PROTOCOLS, SAMPLE_CAPITAL, SAMPLE_ALLOC)
        self.assertGreater(s.tier_risk_adjusted_yield, 0.0)

    def test_risk_adjusted_lte_blended(self):
        # With T2/T3 present (weight <1.0), RAY ≤ blended_apy
        s = self.b.build_ladder(SAMPLE_PROTOCOLS, SAMPLE_CAPITAL, SAMPLE_ALLOC)
        self.assertLessEqual(s.tier_risk_adjusted_yield, s.blended_apy + EPS)

    def test_t1_only_risk_adjusted_equals_blended(self):
        protos = [_proto("Aave", "T1", 0.05), _proto("Comp", "T1", 0.04)]
        s = self.b.build_ladder(protos, 10_000, {"T1": 1.0})
        self.assertAlmostEqual(s.tier_risk_adjusted_yield, s.blended_apy, places=6)

    def test_single_protocol_t1(self):
        protos = [_proto("Aave", "T1", 0.05)]
        s = self.b.build_ladder(protos, 10_000, {"T1": 1.0})
        self.assertEqual(len(s.rungs), 1)
        self.assertAlmostEqual(s.rungs[0].allocated_amount, 10_000.0, places=3)
        self.assertAlmostEqual(s.rungs[0].expected_yield,    500.0,   places=3)

    def test_rungs_are_ladder_rung_instances(self):
        s = self.b.build_ladder(SAMPLE_PROTOCOLS, SAMPLE_CAPITAL, SAMPLE_ALLOC)
        for r in s.rungs:
            self.assertIsInstance(r, LadderRung)


# ===========================================================================
# 2. Edge cases
# ===========================================================================

class TestBuildLadderEdgeCases(unittest.TestCase):

    def setUp(self):
        self.b = _builder()

    def test_empty_protocols_returns_snapshot(self):
        s = self.b.build_ladder([], SAMPLE_CAPITAL, SAMPLE_ALLOC)
        self.assertIsInstance(s, LadderSnapshot)

    def test_empty_protocols_zero_blended_apy(self):
        s = self.b.build_ladder([], SAMPLE_CAPITAL, SAMPLE_ALLOC)
        self.assertEqual(s.blended_apy, 0.0)

    def test_empty_protocols_zero_score(self):
        s = self.b.build_ladder([], SAMPLE_CAPITAL, SAMPLE_ALLOC)
        self.assertEqual(s.ladder_score, 0.0)

    def test_empty_protocols_empty_rungs(self):
        s = self.b.build_ladder([], SAMPLE_CAPITAL, SAMPLE_ALLOC)
        self.assertEqual(s.rungs, [])

    def test_zero_capital_returns_snapshot(self):
        s = self.b.build_ladder(SAMPLE_PROTOCOLS, 0.0, SAMPLE_ALLOC)
        self.assertIsInstance(s, LadderSnapshot)

    def test_zero_capital_empty_rungs(self):
        s = self.b.build_ladder(SAMPLE_PROTOCOLS, 0.0, SAMPLE_ALLOC)
        self.assertEqual(s.rungs, [])

    def test_negative_capital_treated_as_zero(self):
        s = self.b.build_ladder(SAMPLE_PROTOCOLS, -1_000.0, SAMPLE_ALLOC)
        self.assertEqual(s.rungs, [])

    def test_allocation_only_t1_excludes_others(self):
        s = self.b.build_ladder(SAMPLE_PROTOCOLS, SAMPLE_CAPITAL, {"T1": 1.0})
        tiers = {r.tier for r in s.rungs}
        self.assertEqual(tiers, {"T1"})

    def test_empty_target_allocation_no_rungs(self):
        s = self.b.build_ladder(SAMPLE_PROTOCOLS, SAMPLE_CAPITAL, {})
        self.assertEqual(s.rungs, [])

    def test_zero_fraction_tier_excluded(self):
        alloc = {"T1": 1.0, "T2": 0.0}
        protos = [_proto("Aave", "T1", 0.05), _proto("Morpho", "T2", 0.07)]
        s = self.b.build_ladder(protos, 10_000, alloc)
        tiers = {r.tier for r in s.rungs}
        self.assertNotIn("T2", tiers)

    def test_unknown_tier_in_protocols_ignored(self):
        protos = [_proto("Aave", "T1", 0.05), _proto("Exotic", "T9", 0.20)]
        s = self.b.build_ladder(protos, 10_000, {"T1": 1.0, "T9": 0.0})
        tiers = {r.tier for r in s.rungs}
        self.assertNotIn("T9", tiers)

    def test_extreme_high_apy(self):
        protos = [_proto("HighYield", "T3", 5.00)]
        s = self.b.build_ladder(protos, 10_000, {"T3": 1.0})
        self.assertAlmostEqual(s.blended_apy, 5.00, places=4)

    def test_zero_apy_protocol_zero_yield(self):
        protos = [_proto("Zero", "T1", 0.0)]
        s = self.b.build_ladder(protos, 10_000, {"T1": 1.0})
        self.assertAlmostEqual(s.blended_apy,            0.0, places=6)
        self.assertAlmostEqual(s.rungs[0].expected_yield, 0.0, places=6)

    def test_very_small_capital(self):
        protos = [_proto("A", "T1", 0.05)]
        s = self.b.build_ladder(protos, 0.01, {"T1": 1.0})
        self.assertAlmostEqual(s.rungs[0].allocated_amount, 0.01, places=6)


# ===========================================================================
# 3. Rung-level values
# ===========================================================================

class TestRungValues(unittest.TestCase):

    def setUp(self):
        self.b = _builder()

    def test_t1_equal_split(self):
        # T1 gets 50 % of 100 k = 50 k; 2 protocols → 25 k each
        s = self.b.build_ladder(SAMPLE_PROTOCOLS, SAMPLE_CAPITAL, SAMPLE_ALLOC)
        t1 = [r for r in s.rungs if r.tier == "T1"]
        for r in t1:
            self.assertAlmostEqual(r.allocated_amount, 25_000.0, places=3)

    def test_rung_expected_yield_product(self):
        protos = [_proto("Aave", "T1", 0.10)]
        s = self.b.build_ladder(protos, 10_000, {"T1": 1.0})
        self.assertAlmostEqual(s.rungs[0].expected_yield, 1_000.0, places=3)

    def test_rung_tier_is_known(self):
        s = self.b.build_ladder(SAMPLE_PROTOCOLS, SAMPLE_CAPITAL, SAMPLE_ALLOC)
        for r in s.rungs:
            self.assertIn(r.tier, KNOWN_TIERS)

    def test_rung_apy_nonnegative(self):
        s = self.b.build_ladder(SAMPLE_PROTOCOLS, SAMPLE_CAPITAL, SAMPLE_ALLOC)
        for r in s.rungs:
            self.assertGreaterEqual(r.apy, 0.0)

    def test_rung_protocol_name_nonempty(self):
        s = self.b.build_ladder(SAMPLE_PROTOCOLS, SAMPLE_CAPITAL, SAMPLE_ALLOC)
        for r in s.rungs:
            self.assertTrue(r.protocol)

    def test_t2_allocation_correct(self):
        # T2 gets 30 % of 100 k = 30 k; 2 protocols → 15 k each
        s = self.b.build_ladder(SAMPLE_PROTOCOLS, SAMPLE_CAPITAL, SAMPLE_ALLOC)
        t2 = [r for r in s.rungs if r.tier == "T2"]
        for r in t2:
            self.assertAlmostEqual(r.allocated_amount, 15_000.0, places=3)

    def test_t3_allocation_correct(self):
        # T3 gets 20 % of 100 k = 20 k; 1 protocol → 20 k
        s = self.b.build_ladder(SAMPLE_PROTOCOLS, SAMPLE_CAPITAL, SAMPLE_ALLOC)
        t3 = [r for r in s.rungs if r.tier == "T3"]
        self.assertEqual(len(t3), 1)
        self.assertAlmostEqual(t3[0].allocated_amount, 20_000.0, places=3)


# ===========================================================================
# 4. get_blended_apy()
# ===========================================================================

class TestGetBlendedApy(unittest.TestCase):

    def setUp(self):
        self.b = _builder()

    def test_returns_zero_before_build(self):
        self.assertEqual(self.b.get_blended_apy(), 0.0)

    def test_matches_snapshot_value_after_build(self):
        s = self.b.build_ladder(SAMPLE_PROTOCOLS, SAMPLE_CAPITAL, SAMPLE_ALLOC)
        self.assertAlmostEqual(self.b.get_blended_apy(), s.blended_apy, places=8)

    def test_single_protocol_blended_equals_apy(self):
        protos = [_proto("Aave", "T1", 0.035)]
        s = self.b.build_ladder(protos, 10_000, {"T1": 1.0})
        self.assertAlmostEqual(s.get_blended_apy(), 0.035, places=6)

    def test_two_equal_allocations(self):
        protos = [_proto("A", "T1", 0.04), _proto("B", "T1", 0.06)]
        s = self.b.build_ladder(protos, 10_000, {"T1": 1.0})
        # Each gets 5 k; yield = 200 + 300 = 500; blended = 500/10000 = 5 %
        self.assertAlmostEqual(s.get_blended_apy(), 0.05, places=6)

    def test_snapshot_get_blended_apy_method(self):
        s = self.b.build_ladder(SAMPLE_PROTOCOLS, SAMPLE_CAPITAL, SAMPLE_ALLOC)
        self.assertEqual(s.get_blended_apy(), s.blended_apy)

    def test_empty_protocols_blended_zero(self):
        s = self.b.build_ladder([], SAMPLE_CAPITAL, SAMPLE_ALLOC)
        self.assertEqual(s.get_blended_apy(), 0.0)

    def test_updates_after_rebuild(self):
        self.b.build_ladder([_proto("A", "T1", 0.05)], 10_000, {"T1": 1.0})
        apy1 = self.b.get_blended_apy()
        self.b.build_ladder([_proto("A", "T1", 0.10)], 10_000, {"T1": 1.0})
        apy2 = self.b.get_blended_apy()
        self.assertGreater(apy2, apy1)


# ===========================================================================
# 5. get_tier_summary()
# ===========================================================================

class TestGetTierSummary(unittest.TestCase):

    def setUp(self):
        self.b = _builder()

    def test_returns_empty_before_build(self):
        self.assertEqual(self.b.get_tier_summary(), {})

    def test_has_t1_t2_t3_with_full_allocation(self):
        s = self.b.build_ladder(SAMPLE_PROTOCOLS, SAMPLE_CAPITAL, SAMPLE_ALLOC)
        self.assertIn("T1", s.tier_summary)
        self.assertIn("T2", s.tier_summary)
        self.assertIn("T3", s.tier_summary)

    def test_t1_rung_count(self):
        s = self.b.build_ladder(SAMPLE_PROTOCOLS, SAMPLE_CAPITAL, SAMPLE_ALLOC)
        self.assertEqual(s.tier_summary["T1"]["rung_count"], 2)

    def test_t2_rung_count(self):
        s = self.b.build_ladder(SAMPLE_PROTOCOLS, SAMPLE_CAPITAL, SAMPLE_ALLOC)
        self.assertEqual(s.tier_summary["T2"]["rung_count"], 2)

    def test_t3_rung_count(self):
        s = self.b.build_ladder(SAMPLE_PROTOCOLS, SAMPLE_CAPITAL, SAMPLE_ALLOC)
        self.assertEqual(s.tier_summary["T3"]["rung_count"], 1)

    def test_t1_allocated_amount(self):
        s = self.b.build_ladder(SAMPLE_PROTOCOLS, SAMPLE_CAPITAL, SAMPLE_ALLOC)
        self.assertAlmostEqual(s.tier_summary["T1"]["allocated"], 50_000.0, places=3)

    def test_t2_allocated_amount(self):
        s = self.b.build_ladder(SAMPLE_PROTOCOLS, SAMPLE_CAPITAL, SAMPLE_ALLOC)
        self.assertAlmostEqual(s.tier_summary["T2"]["allocated"], 30_000.0, places=3)

    def test_avg_apy_in_valid_range(self):
        s = self.b.build_ladder(SAMPLE_PROTOCOLS, SAMPLE_CAPITAL, SAMPLE_ALLOC)
        for tier, info in s.tier_summary.items():
            self.assertGreaterEqual(info["avg_apy"], 0.0)

    def test_expected_yield_nonnegative(self):
        s = self.b.build_ladder(SAMPLE_PROTOCOLS, SAMPLE_CAPITAL, SAMPLE_ALLOC)
        for tier, info in s.tier_summary.items():
            self.assertGreaterEqual(info["expected_yield"], 0.0)

    def test_tier_absent_when_not_allocated(self):
        protos = [_proto("Aave", "T1", 0.05)]
        s = self.b.build_ladder(protos, 10_000, {"T1": 1.0})
        self.assertNotIn("T2", s.tier_summary)
        self.assertNotIn("T3", s.tier_summary)

    def test_builder_get_tier_summary_matches_snapshot(self):
        s = self.b.build_ladder(SAMPLE_PROTOCOLS, SAMPLE_CAPITAL, SAMPLE_ALLOC)
        self.assertEqual(self.b.get_tier_summary(), s.tier_summary)

    def test_summary_keys_structure(self):
        s = self.b.build_ladder(SAMPLE_PROTOCOLS, SAMPLE_CAPITAL, SAMPLE_ALLOC)
        for info in s.tier_summary.values():
            self.assertIn("allocated", info)
            self.assertIn("expected_yield", info)
            self.assertIn("avg_apy", info)
            self.assertIn("rung_count", info)


# ===========================================================================
# 6. ladder_score
# ===========================================================================

class TestLadderScore(unittest.TestCase):

    def setUp(self):
        self.b = _builder()

    def test_score_in_range_basic(self):
        s = self.b.build_ladder(SAMPLE_PROTOCOLS, SAMPLE_CAPITAL, SAMPLE_ALLOC)
        self.assertGreaterEqual(s.ladder_score, 0.0)
        self.assertLessEqual(s.ladder_score, 100.0)

    def test_score_zero_when_empty(self):
        s = self.b.build_ladder([], SAMPLE_CAPITAL, SAMPLE_ALLOC)
        self.assertEqual(s.ladder_score, 0.0)

    def test_higher_apy_gives_higher_score(self):
        low  = self.b.build_ladder([_proto("A", "T1", 0.01)], 10_000, {"T1": 1.0})
        high = self.b.build_ladder([_proto("A", "T1", 0.20)], 10_000, {"T1": 1.0})
        self.assertGreater(high.ladder_score, low.ladder_score)

    def test_more_diverse_protocols_higher_or_equal_score(self):
        one  = self.b.build_ladder([_proto("A", "T1", 0.05)],
                                   10_000, {"T1": 1.0})
        many = self.b.build_ladder([_proto(f"P{i}", "T1", 0.05) for i in range(6)],
                                   10_000, {"T1": 1.0})
        self.assertGreaterEqual(many.ladder_score, one.ladder_score)

    def test_score_cannot_exceed_100(self):
        protos = [_proto(f"P{i}", "T1", 5.0) for i in range(20)]
        s = self.b.build_ladder(protos, 1_000_000, {"T1": 1.0})
        self.assertLessEqual(s.ladder_score, 100.0)

    def test_score_nonnegative_with_zero_apy(self):
        protos = [_proto("A", "T1", 0.0)]
        s = self.b.build_ladder(protos, 10_000, {"T1": 1.0})
        self.assertGreaterEqual(s.ladder_score, 0.0)

    def test_score_positive_with_full_three_tier_allocation(self):
        s = self.b.build_ladder(SAMPLE_PROTOCOLS, SAMPLE_CAPITAL, SAMPLE_ALLOC)
        self.assertGreater(s.ladder_score, 0.0)


# ===========================================================================
# 7. tier_risk_adjusted_yield
# ===========================================================================

class TestTierRiskAdjustedYield(unittest.TestCase):

    def setUp(self):
        self.b = _builder()

    def test_t1_weight_one_so_ray_equals_blended(self):
        protos = [_proto("Aave", "T1", 0.10)]
        s = self.b.build_ladder(protos, 10_000, {"T1": 1.0})
        self.assertAlmostEqual(s.tier_risk_adjusted_yield, 0.10, places=6)

    def test_t2_discount_applied(self):
        protos = [_proto("Morpho", "T2", 0.10)]
        s = self.b.build_ladder(protos, 10_000, {"T2": 1.0})
        # T2 weight = 0.85 → RAY = 0.10 * 0.85 = 0.085
        self.assertAlmostEqual(s.tier_risk_adjusted_yield, 0.085, places=6)

    def test_t3_discount_applied(self):
        protos = [_proto("Pendle", "T3", 0.10)]
        s = self.b.build_ladder(protos, 10_000, {"T3": 1.0})
        # T3 weight = 0.70 → RAY = 0.10 * 0.70 = 0.07
        self.assertAlmostEqual(s.tier_risk_adjusted_yield, 0.07, places=6)

    def test_ray_nonnegative(self):
        s = self.b.build_ladder(SAMPLE_PROTOCOLS, SAMPLE_CAPITAL, SAMPLE_ALLOC)
        self.assertGreaterEqual(s.tier_risk_adjusted_yield, 0.0)

    def test_ray_zero_when_empty(self):
        s = self.b.build_ladder([], SAMPLE_CAPITAL, SAMPLE_ALLOC)
        self.assertEqual(s.tier_risk_adjusted_yield, 0.0)

    def test_ray_zero_when_zero_apy(self):
        protos = [_proto("A", "T2", 0.0)]
        s = self.b.build_ladder(protos, 10_000, {"T2": 1.0})
        self.assertAlmostEqual(s.tier_risk_adjusted_yield, 0.0, places=8)

    def test_tier_risk_weights_constants(self):
        self.assertAlmostEqual(TIER_RISK_WEIGHTS["T1"], 1.00, places=6)
        self.assertAlmostEqual(TIER_RISK_WEIGHTS["T2"], 0.85, places=6)
        self.assertAlmostEqual(TIER_RISK_WEIGHTS["T3"], 0.70, places=6)


# ===========================================================================
# 8. save_snapshot() / load_history()
# ===========================================================================

class TestSaveAndLoadHistory(unittest.TestCase):

    def setUp(self):
        fd, path = tempfile.mkstemp(suffix=".json")
        os.close(fd)
        os.unlink(path)
        self.path = Path(path)
        self.b = YieldLadderBuilder(data_file=self.path)

    def tearDown(self):
        for f in [self.path, self.path.with_suffix(".tmp")]:
            try:
                f.unlink()
            except FileNotFoundError:
                pass

    def test_load_history_empty_before_any_save(self):
        self.assertEqual(self.b.load_history(), [])

    def test_save_creates_file(self):
        s = self.b.build_ladder(SAMPLE_PROTOCOLS, SAMPLE_CAPITAL, SAMPLE_ALLOC)
        self.b.save_snapshot(s)
        self.assertTrue(self.path.exists())

    def test_save_and_load_one_entry(self):
        s = self.b.build_ladder(SAMPLE_PROTOCOLS, SAMPLE_CAPITAL, SAMPLE_ALLOC)
        self.b.save_snapshot(s)
        history = self.b.load_history()
        self.assertEqual(len(history), 1)

    def test_saved_entry_has_required_keys(self):
        s = self.b.build_ladder(SAMPLE_PROTOCOLS, SAMPLE_CAPITAL, SAMPLE_ALLOC)
        self.b.save_snapshot(s)
        entry = self.b.load_history()[0]
        for key in ("timestamp", "capital", "rung_count",
                    "blended_apy", "tier_risk_adjusted_yield", "ladder_score"):
            self.assertIn(key, entry)

    def test_multiple_saves_accumulate(self):
        for _ in range(3):
            s = self.b.build_ladder(SAMPLE_PROTOCOLS, SAMPLE_CAPITAL, SAMPLE_ALLOC)
            self.b.save_snapshot(s)
        self.assertEqual(len(self.b.load_history()), 3)

    def test_ring_buffer_does_not_exceed_max_entries(self):
        for i in range(MAX_ENTRIES + 5):
            s = self.b.build_ladder([_proto(f"P{i}", "T1", 0.05)], 10_000, {"T1": 1.0})
            self.b.save_snapshot(s)
        self.assertLessEqual(len(self.b.load_history()), MAX_ENTRIES)

    def test_ring_buffer_keeps_most_recent(self):
        for i in range(MAX_ENTRIES + 2):
            apy = 0.01 * (i + 1)
            s = self.b.build_ladder([_proto(f"P{i}", "T1", apy)], 10_000, {"T1": 1.0})
            self.b.save_snapshot(s)
        history = self.b.load_history()
        # Last entry should be the highest APY saved
        self.assertGreater(history[-1]["blended_apy"], history[0]["blended_apy"])

    def test_no_tmp_file_left_after_save(self):
        s = self.b.build_ladder(SAMPLE_PROTOCOLS, SAMPLE_CAPITAL, SAMPLE_ALLOC)
        self.b.save_snapshot(s)
        self.assertFalse(self.path.with_suffix(".tmp").exists())

    def test_load_history_returns_empty_on_invalid_json(self):
        self.path.write_text("not valid json {{{")
        self.assertEqual(self.b.load_history(), [])

    def test_load_history_returns_empty_on_non_list_json(self):
        self.path.write_text('{"key": "value"}')
        self.assertEqual(self.b.load_history(), [])

    def test_blended_apy_preserved_in_history(self):
        s = self.b.build_ladder(SAMPLE_PROTOCOLS, SAMPLE_CAPITAL, SAMPLE_ALLOC)
        self.b.save_snapshot(s)
        history = self.b.load_history()
        self.assertAlmostEqual(history[0]["blended_apy"], s.blended_apy, places=6)

    def test_rung_count_preserved_in_history(self):
        s = self.b.build_ladder(SAMPLE_PROTOCOLS, SAMPLE_CAPITAL, SAMPLE_ALLOC)
        self.b.save_snapshot(s)
        history = self.b.load_history()
        self.assertEqual(history[0]["rung_count"], 5)


# ===========================================================================
# 9. Internal state (_last_snapshot)
# ===========================================================================

class TestLastSnapshotState(unittest.TestCase):

    def test_initial_last_snapshot_is_none(self):
        b = _builder()
        self.assertIsNone(b._last_snapshot)

    def test_last_snapshot_set_after_build(self):
        b = _builder()
        b.build_ladder(SAMPLE_PROTOCOLS, SAMPLE_CAPITAL, SAMPLE_ALLOC)
        self.assertIsNotNone(b._last_snapshot)

    def test_get_blended_apy_reflects_latest_build(self):
        b = _builder()
        b.build_ladder([_proto("A", "T1", 0.05)], 10_000, {"T1": 1.0})
        apy1 = b.get_blended_apy()
        b.build_ladder([_proto("A", "T1", 0.10)], 10_000, {"T1": 1.0})
        apy2 = b.get_blended_apy()
        self.assertGreater(apy2, apy1)

    def test_get_tier_summary_reflects_latest_build(self):
        b = _builder()
        # First build: T1 only
        b.build_ladder([_proto("A", "T1", 0.05)], 10_000, {"T1": 1.0})
        self.assertNotIn("T2", b.get_tier_summary())
        # Second build: T1 + T2
        b.build_ladder(
            [_proto("A", "T1", 0.05), _proto("B", "T2", 0.07)],
            10_000, {"T1": 0.5, "T2": 0.5},
        )
        self.assertIn("T2", b.get_tier_summary())


# ===========================================================================
# 10. Boundary / numeric precision
# ===========================================================================

class TestBoundaryValues(unittest.TestCase):

    def setUp(self):
        self.b = _builder()

    def test_allocation_sum_greater_than_one(self):
        # Fractions sum > 1 is allowed; per-tier capital may exceed total,
        # but ladder should still function without error
        alloc = {"T1": 0.6, "T2": 0.6}
        protos = [_proto("A", "T1", 0.05), _proto("B", "T2", 0.07)]
        s = self.b.build_ladder(protos, 10_000, alloc)
        self.assertIsInstance(s, LadderSnapshot)

    def test_maximum_apy_extreme(self):
        protos = [_proto("Extreme", "T3", 100.0)]
        s = self.b.build_ladder(protos, 1_000, {"T3": 1.0})
        self.assertAlmostEqual(s.blended_apy, 100.0, places=4)

    def test_many_protocols_same_tier(self):
        protos = [_proto(f"P{i}", "T1", 0.05) for i in range(50)]
        s = self.b.build_ladder(protos, 100_000, {"T1": 1.0})
        self.assertEqual(len(s.rungs), 50)
        for r in s.rungs:
            self.assertAlmostEqual(r.allocated_amount, 2_000.0, places=3)

    def test_fractional_capital(self):
        protos = [_proto("A", "T1", 0.05)]
        s = self.b.build_ladder(protos, 1.50, {"T1": 1.0})
        self.assertAlmostEqual(s.rungs[0].allocated_amount, 1.50, places=6)

    def test_blended_apy_non_nan(self):
        s = self.b.build_ladder(SAMPLE_PROTOCOLS, SAMPLE_CAPITAL, SAMPLE_ALLOC)
        self.assertEqual(s.blended_apy, s.blended_apy)  # NaN ≠ NaN check


if __name__ == "__main__":
    unittest.main(verbosity=2)
