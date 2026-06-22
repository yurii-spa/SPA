"""
Tests for spa_core/analytics/rs001_live_apy_engine.py — MP-1316 (Sprint v9.32)

Groups:
    TestInstantiation            (3  tests)
    TestSlotAPYs                 (6  tests)
    TestBlendedAPY               (5  tests)
    TestCleanVsResearch          (4  tests)
    TestAPYBreakdownReport       (8  tests)
    TestSaveAtomic               (5  tests)
    TestWeightSum                (2  tests)
    TestEdgeCases                (2  tests)

Total: 35 tests
"""
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock

# ---------------------------------------------------------------------------
# Path setup
# ---------------------------------------------------------------------------
_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from spa_core.analytics.rs001_live_apy_engine import (
    RS001LiveAPYEngine,
    _SLOT_DEFS,
    _DEFAULT_DATA_PATH,
)


# ── Helpers ────────────────────────────────────────────────────────────────────

def _engine_with_placeholder_adapters():
    """Engine with all adapters replaced by fixed-value mocks.

    Stablecoin → 4.0% (decimal 0.04), GMX → 15.0%, gold → 8.5%.
    """
    engine = RS001LiveAPYEngine.__new__(RS001LiveAPYEngine)
    engine._repo_root = Path(tempfile.mkdtemp())

    # Stablecoin mock (returns decimal, e.g. 0.04 = 4%)
    stablecoin_mock = MagicMock()
    stablecoin_mock.get_apy.return_value = 0.04
    engine._stablecoin_adapter = stablecoin_mock
    engine._stablecoin_source = "mock_stablecoin_clean"

    # GMX mock (returns pct, e.g. 15.0)
    gmx_mock = MagicMock()
    gmx_mock.btc_exposure_apy.return_value = 15.0
    gmx_mock.eth_exposure_apy.return_value = 15.0
    engine._gmx_adapter = gmx_mock

    # Gold mock (returns pct, e.g. 8.5)
    gold_mock = MagicMock()
    gold_mock.gold_proxy_apy.return_value = 8.5
    engine._gold_adapter = gold_mock

    return engine


def _engine_no_adapters():
    """Engine with no live adapters at all (pure placeholders)."""
    engine = RS001LiveAPYEngine.__new__(RS001LiveAPYEngine)
    engine._repo_root = Path(tempfile.mkdtemp())
    engine._stablecoin_adapter = None
    engine._stablecoin_source = "placeholder_fallback"
    engine._gmx_adapter = None
    engine._gold_adapter = None
    return engine


# ── TestInstantiation ──────────────────────────────────────────────────────────

class TestInstantiation(unittest.TestCase):
    """3 tests: engine creation."""

    def test_engine_instantiates(self):
        engine = RS001LiveAPYEngine()
        self.assertIsNotNone(engine)

    def test_engine_has_slot_defs(self):
        self.assertEqual(len(_SLOT_DEFS), 6)

    def test_default_data_path_is_string(self):
        self.assertIsInstance(_DEFAULT_DATA_PATH, str)
        self.assertIn("rs001_apy_breakdown", _DEFAULT_DATA_PATH)


# ── TestSlotAPYs ──────────────────────────────────────────────────────────────

class TestSlotAPYs(unittest.TestCase):
    """6 tests: slot_apys() structure."""

    def setUp(self):
        self.engine = _engine_with_placeholder_adapters()

    def test_slot_apys_returns_list(self):
        result = self.engine.slot_apys()
        self.assertIsInstance(result, list)

    def test_slot_apys_count(self):
        result = self.engine.slot_apys()
        self.assertEqual(len(result), 6)

    def test_each_slot_has_slot_id(self):
        for slot in self.engine.slot_apys():
            self.assertIn("slot_id", slot)
            self.assertIsInstance(slot["slot_id"], str)

    def test_each_slot_has_apy_positive(self):
        for slot in self.engine.slot_apys():
            self.assertGreater(slot["apy"], 0,
                               f"Slot {slot['slot_id']} has non-positive APY")

    def test_each_slot_has_source_quality(self):
        valid_qualities = {"CLEAN", "RESEARCH", "PLACEHOLDER"}
        for slot in self.engine.slot_apys():
            self.assertIn(slot["source_quality"], valid_qualities,
                          f"Slot {slot['slot_id']} has invalid source_quality")

    def test_each_slot_has_weight(self):
        for slot in self.engine.slot_apys():
            self.assertIn("weight", slot)
            self.assertGreater(slot["weight"], 0)


# ── TestBlendedAPY ────────────────────────────────────────────────────────────

class TestBlendedAPY(unittest.TestCase):
    """5 tests: blended_apy()."""

    def test_blended_apy_in_valid_range_with_mocks(self):
        engine = _engine_with_placeholder_adapters()
        result = engine.blended_apy()
        self.assertGreaterEqual(result, 15.0)
        self.assertLessEqual(result, 20.0)

    def test_blended_apy_positive(self):
        engine = _engine_no_adapters()
        result = engine.blended_apy()
        self.assertGreater(result, 0)

    def test_blended_apy_in_range_no_adapters(self):
        """With all-placeholder values, blended should be ~18.2% (target APY)."""
        engine = _engine_no_adapters()
        result = engine.blended_apy()
        # Placeholders: 0.15*3.5 + 0.20*15 + 0.10*15 + 0.35*25 + 0.05*45 + 0.15*8 ≈ 17.225
        self.assertGreaterEqual(result, 14.0)
        self.assertLessEqual(result, 22.0)

    def test_blended_apy_returns_float(self):
        engine = _engine_with_placeholder_adapters()
        result = engine.blended_apy()
        self.assertIsInstance(result, float)

    def test_blended_apy_matches_manual_sum(self):
        engine = _engine_with_placeholder_adapters()
        slots = engine.slot_apys()
        expected = sum(s["weight"] * s["apy"] for s in slots)
        self.assertAlmostEqual(engine.blended_apy(), expected, places=4)


# ── TestCleanVsResearch ───────────────────────────────────────────────────────

class TestCleanVsResearch(unittest.TestCase):
    """4 tests: clean_fraction_apy() < research_fraction_apy()."""

    def setUp(self):
        self.engine = _engine_with_placeholder_adapters()

    def test_clean_fraction_less_than_research(self):
        """Only stablecoin_t1 (15% weight) is CLEAN → much smaller than RESEARCH sum."""
        clean = self.engine.clean_fraction_apy()
        research = self.engine.research_fraction_apy()
        self.assertLess(clean, research,
                        f"Expected clean ({clean:.3f}) < research ({research:.3f})")

    def test_clean_fraction_positive(self):
        clean = self.engine.clean_fraction_apy()
        self.assertGreater(clean, 0)

    def test_research_fraction_positive(self):
        research = self.engine.research_fraction_apy()
        self.assertGreater(research, 0)

    def test_clean_fraction_reflects_single_slot(self):
        """CLEAN is only stablecoin_t1 (weight 0.15)."""
        engine = _engine_with_placeholder_adapters()
        # Stablecoin mock returns 0.04 decimal → 4.0% → contribution = 0.15 * 4.0
        clean = engine.clean_fraction_apy()
        expected = 0.15 * 4.0
        self.assertAlmostEqual(clean, expected, places=3)


# ── TestAPYBreakdownReport ────────────────────────────────────────────────────

class TestAPYBreakdownReport(unittest.TestCase):
    """8 tests: apy_breakdown_report()."""

    def setUp(self):
        self.engine = _engine_with_placeholder_adapters()
        self.report = self.engine.apy_breakdown_report()

    def test_report_is_dict(self):
        self.assertIsInstance(self.report, dict)

    def test_report_has_blended_key(self):
        self.assertIn("blended", self.report)
        self.assertIsInstance(self.report["blended"], float)

    def test_report_has_slots_key(self):
        self.assertIn("slots", self.report)
        self.assertIsInstance(self.report["slots"], list)

    def test_report_status_is_research_dominated(self):
        """Only 15% of capital (stablecoin_t1) is CLEAN → RESEARCH_DOMINATED."""
        self.assertEqual(self.report["status"], "RESEARCH_DOMINATED")

    def test_report_has_clean_pct_of_capital(self):
        self.assertIn("clean_pct_of_capital", self.report)
        # stablecoin_t1 weight = 0.15 → 15.0%
        self.assertAlmostEqual(self.report["clean_pct_of_capital"], 15.0, places=1)

    def test_report_has_required_keys(self):
        required = (
            "blended", "clean_contribution", "research_contribution",
            "placeholder_contribution", "clean_pct_of_capital", "slots",
            "status", "schema_version", "strategy_id", "generated_at",
        )
        for key in required:
            self.assertIn(key, self.report, f"Missing key: {key}")

    def test_report_strategy_id(self):
        self.assertEqual(self.report["strategy_id"], "RS-001")

    def test_contributions_sum_to_blended(self):
        """clean + research + placeholder contributions should equal blended."""
        total = (
            self.report["clean_contribution"]
            + self.report["research_contribution"]
            + self.report["placeholder_contribution"]
        )
        self.assertAlmostEqual(total, self.report["blended"], places=4)


# ── TestSaveAtomic ────────────────────────────────────────────────────────────

class TestSaveAtomic(unittest.TestCase):
    """5 tests: save() atomic write."""

    def setUp(self):
        self.tmp_dir = tempfile.mkdtemp()
        self.engine = _engine_with_placeholder_adapters()
        self.engine._repo_root = Path(self.tmp_dir)

    def test_save_creates_file(self):
        out = os.path.join(self.tmp_dir, "rs001_apy_breakdown.json")
        self.engine.save(path=out)
        self.assertTrue(os.path.exists(out))

    def test_save_creates_valid_json(self):
        out = os.path.join(self.tmp_dir, "rs001_apy_breakdown.json")
        self.engine.save(path=out)
        with open(out, "r") as fh:
            data = json.load(fh)
        self.assertIsInstance(data, dict)

    def test_save_json_has_blended(self):
        out = os.path.join(self.tmp_dir, "rs001_apy_breakdown.json")
        self.engine.save(path=out)
        with open(out, "r") as fh:
            data = json.load(fh)
        self.assertIn("blended", data)

    def test_save_no_tmp_files_left(self):
        """After save(), no .tmp.json files should remain in the directory."""
        out_dir = os.path.join(self.tmp_dir, "out")
        os.makedirs(out_dir)
        out = os.path.join(out_dir, "rs001_apy_breakdown.json")
        self.engine.save(path=out)
        tmp_files = [f for f in os.listdir(out_dir) if f.endswith(".tmp.json")]
        self.assertEqual(len(tmp_files), 0)

    def test_save_creates_parent_dirs(self):
        """save() should create missing parent directories."""
        out = os.path.join(self.tmp_dir, "deep", "nested", "rs001.json")
        self.engine.save(path=out)
        self.assertTrue(os.path.exists(out))


# ── TestWeightSum ─────────────────────────────────────────────────────────────

class TestWeightSum(unittest.TestCase):
    """2 tests: sum of weights ≈ 1.0."""

    def test_slot_weights_sum_to_one(self):
        engine = _engine_with_placeholder_adapters()
        slots = engine.slot_apys()
        total_weight = sum(s["weight"] for s in slots)
        self.assertAlmostEqual(total_weight, 1.0, places=6)

    def test_slot_def_weights_sum_to_one(self):
        total = sum(s["weight"] for s in _SLOT_DEFS)
        self.assertAlmostEqual(total, 1.0, places=6)


# ── TestEdgeCases ─────────────────────────────────────────────────────────────

class TestEdgeCases(unittest.TestCase):
    """2 tests: edge cases."""

    def test_adapters_raising_do_not_crash_engine(self):
        """If adapters raise, engine falls back gracefully."""
        engine = _engine_with_placeholder_adapters()
        engine._stablecoin_adapter.get_apy.side_effect = RuntimeError("network down")
        engine._gmx_adapter.btc_exposure_apy.side_effect = RuntimeError("gmx down")
        engine._gold_adapter.gold_proxy_apy.side_effect = RuntimeError("gold down")
        try:
            report = engine.apy_breakdown_report()
            self.assertIn("blended", report)
        except Exception as exc:
            self.fail(f"apy_breakdown_report raised unexpectedly: {exc}")

    def test_blended_apy_not_zero_with_failing_adapters(self):
        """Even with all adapters failing, placeholders keep blended_apy > 0."""
        engine = _engine_no_adapters()
        result = engine.blended_apy()
        self.assertGreater(result, 0)


if __name__ == "__main__":
    unittest.main()
