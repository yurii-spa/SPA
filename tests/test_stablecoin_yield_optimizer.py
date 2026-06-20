"""tests/test_stablecoin_yield_optimizer.py

35 unit tests for spa_core.analytics.stablecoin_yield_optimizer.

MP-1341 (v9.57) — StablecoinYieldOptimizer for RS-001 / RS-002 stablecoin slots.

Run:
    python3 -m unittest tests.test_stablecoin_yield_optimizer -v
"""
import json
import os
import unittest
import tempfile

from spa_core.analytics.stablecoin_yield_optimizer import (
    T1_PROTOCOLS,
    StablecoinYieldOptimizer,
    _atomic_write,
    _iso_now,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _default_apys() -> dict:
    """Return fallback APYs for all T1 protocols (deterministic input)."""
    return {pid: spec["fallback_apy"] for pid, spec in T1_PROTOCOLS.items()}


class _FakeOptimizer(StablecoinYieldOptimizer):
    """Subclass that bypasses network calls and always returns fallback APYs."""

    def live_apys(self) -> dict:
        return _default_apys()


# ---------------------------------------------------------------------------
# Group 1: T1_PROTOCOLS catalogue
# ---------------------------------------------------------------------------

class TestT1ProtocolsCatalogue(unittest.TestCase):
    """Tests for the module-level T1_PROTOCOLS constant."""

    def test_catalogue_has_four_protocols(self):
        self.assertEqual(len(T1_PROTOCOLS), 4)

    def test_required_protocols_present(self):
        expected = {"aave_v3_usdc", "morpho_blue_usdc", "sky_susds", "compound_v3_usdc"}
        self.assertEqual(set(T1_PROTOCOLS.keys()), expected)

    def test_all_protocols_have_fallback_apy(self):
        for pid, spec in T1_PROTOCOLS.items():
            with self.subTest(protocol=pid):
                self.assertIn("fallback_apy", spec)
                self.assertGreater(spec["fallback_apy"], 0)

    def test_all_protocols_have_max_allocation_pct(self):
        for pid, spec in T1_PROTOCOLS.items():
            with self.subTest(protocol=pid):
                self.assertIn("max_allocation_pct", spec)
                self.assertGreater(spec["max_allocation_pct"], 0)
                self.assertLessEqual(spec["max_allocation_pct"], 100)

    def test_all_protocols_have_tier_and_chain(self):
        for pid, spec in T1_PROTOCOLS.items():
            with self.subTest(protocol=pid):
                self.assertIn("tier", spec)
                self.assertIn("chain", spec)

    def test_sky_susds_highest_fallback_apy(self):
        apys = {pid: spec["fallback_apy"] for pid, spec in T1_PROTOCOLS.items()}
        self.assertEqual(max(apys, key=apys.get), "sky_susds")

    def test_compound_lowest_fallback_apy(self):
        apys = {pid: spec["fallback_apy"] for pid, spec in T1_PROTOCOLS.items()}
        self.assertEqual(min(apys, key=apys.get), "compound_v3_usdc")


# ---------------------------------------------------------------------------
# Group 2: StablecoinYieldOptimizer construction
# ---------------------------------------------------------------------------

class TestOptimizerConstruction(unittest.TestCase):

    def test_default_capital_fraction(self):
        opt = StablecoinYieldOptimizer()
        self.assertAlmostEqual(opt.capital_fraction, 0.15)

    def test_custom_capital_fraction(self):
        opt = StablecoinYieldOptimizer(capital_fraction=0.16)
        self.assertAlmostEqual(opt.capital_fraction, 0.16)

    def test_invalid_capital_fraction_zero_raises(self):
        with self.assertRaises(ValueError):
            StablecoinYieldOptimizer(capital_fraction=0.0)

    def test_invalid_capital_fraction_above_one_raises(self):
        with self.assertRaises(ValueError):
            StablecoinYieldOptimizer(capital_fraction=1.5)

    def test_capital_fraction_one_valid(self):
        opt = StablecoinYieldOptimizer(capital_fraction=1.0)
        self.assertAlmostEqual(opt.capital_fraction, 1.0)


# ---------------------------------------------------------------------------
# Group 3: live_apys()
# ---------------------------------------------------------------------------

class TestLiveApys(unittest.TestCase):

    def setUp(self):
        self.opt = _FakeOptimizer()

    def test_returns_dict(self):
        result = self.opt.live_apys()
        self.assertIsInstance(result, dict)

    def test_all_protocols_returned(self):
        result = self.opt.live_apys()
        for pid in T1_PROTOCOLS:
            self.assertIn(pid, result)

    def test_all_apy_values_positive(self):
        result = self.opt.live_apys()
        for pid, apy in result.items():
            with self.subTest(protocol=pid):
                self.assertGreater(apy, 0)

    def test_fallback_values_match_catalogue(self):
        result = self.opt.live_apys()
        for pid, spec in T1_PROTOCOLS.items():
            with self.subTest(protocol=pid):
                self.assertAlmostEqual(result[pid], spec["fallback_apy"])


# ---------------------------------------------------------------------------
# Group 4: optimal_allocation()
# ---------------------------------------------------------------------------

class TestOptimalAllocation(unittest.TestCase):

    def setUp(self):
        self.opt = _FakeOptimizer()
        self.apys = _default_apys()
        self.alloc = self.opt.optimal_allocation(apys=self.apys)

    def test_returns_dict(self):
        self.assertIsInstance(self.alloc, dict)

    def test_all_protocols_present(self):
        for pid in T1_PROTOCOLS:
            self.assertIn(pid, self.alloc)

    def test_sum_equals_one(self):
        total = sum(self.alloc.values())
        self.assertAlmostEqual(total, 1.0, places=9,
                               msg="Allocation fractions must sum to 1.0")

    def test_no_negative_allocations(self):
        for pid, frac in self.alloc.items():
            with self.subTest(protocol=pid):
                self.assertGreaterEqual(frac, 0.0)

    def test_no_protocol_exceeds_max_allocation_pct(self):
        for pid, frac in self.alloc.items():
            with self.subTest(protocol=pid):
                cap = T1_PROTOCOLS[pid]["max_allocation_pct"] / 100.0
                self.assertLessEqual(
                    frac, cap + 1e-9,
                    msg=f"{pid}: {frac:.4f} exceeds cap {cap:.4f}"
                )

    def test_sky_susds_gets_its_full_cap(self):
        """sky_susds (highest APY) is allocated first and should reach its cap."""
        cap = T1_PROTOCOLS["sky_susds"]["max_allocation_pct"] / 100.0
        self.assertAlmostEqual(self.alloc["sky_susds"], cap, places=6)

    def test_sky_susds_larger_than_aave(self):
        self.assertGreater(self.alloc["sky_susds"], self.alloc["aave_v3_usdc"])

    def test_sky_susds_larger_than_compound(self):
        self.assertGreater(self.alloc["sky_susds"], self.alloc["compound_v3_usdc"])

    def test_morpho_larger_than_aave(self):
        """morpho_blue_usdc (2nd highest APY) should exceed aave (3rd)."""
        self.assertGreater(self.alloc["morpho_blue_usdc"], self.alloc["aave_v3_usdc"])

    def test_greedy_highest_apy_allocated_first(self):
        """After sky_susds (40%) and morpho (50%), remaining 10% goes to aave."""
        # sky=40%, morpho=50%, aave≈10%, compound=0%
        self.assertAlmostEqual(self.alloc["sky_susds"], 0.40, places=6)
        self.assertAlmostEqual(self.alloc["morpho_blue_usdc"], 0.50, places=6)
        self.assertAlmostEqual(self.alloc["aave_v3_usdc"], 0.10, places=6)
        self.assertAlmostEqual(self.alloc["compound_v3_usdc"], 0.0, places=6)

    def test_accepts_custom_apys(self):
        """optimal_allocation() accepts caller-supplied APYs."""
        custom = {"sky_susds": 1.0, "morpho_blue_usdc": 0.5,
                  "aave_v3_usdc": 0.3, "compound_v3_usdc": 0.2}
        alloc = self.opt.optimal_allocation(apys=custom)
        self.assertAlmostEqual(sum(alloc.values()), 1.0, places=9)

    def test_no_args_calls_live_apys(self):
        """Calling without arguments should work (uses live_apys internally)."""
        alloc = self.opt.optimal_allocation()
        self.assertAlmostEqual(sum(alloc.values()), 1.0, places=9)


# ---------------------------------------------------------------------------
# Group 5: blended_apy()
# ---------------------------------------------------------------------------

class TestBlendedApy(unittest.TestCase):

    def setUp(self):
        self.opt = _FakeOptimizer()

    def test_returns_float(self):
        result = self.opt.blended_apy()
        self.assertIsInstance(result, float)

    def test_blended_apy_positive(self):
        result = self.opt.blended_apy()
        self.assertGreater(result, 0)

    def test_blended_apy_at_least_min_fallback(self):
        """Blended APY must be at least the lowest fallback APY."""
        min_apy = min(spec["fallback_apy"] for spec in T1_PROTOCOLS.values())
        result = self.opt.blended_apy()
        self.assertGreaterEqual(result, min_apy)

    def test_blended_apy_at_most_max_fallback(self):
        """Blended APY must not exceed the highest protocol APY."""
        max_apy = max(spec["fallback_apy"] for spec in T1_PROTOCOLS.values())
        result = self.opt.blended_apy()
        self.assertLessEqual(result, max_apy + 1e-9)

    def test_blended_apy_with_explicit_allocation(self):
        """blended_apy() accepts an explicit allocation dict."""
        alloc = {"sky_susds": 1.0,
                 "morpho_blue_usdc": 0.0,
                 "aave_v3_usdc": 0.0,
                 "compound_v3_usdc": 0.0}
        result = self.opt.blended_apy(allocation=alloc)
        # Should equal sky_susds fallback APY
        self.assertAlmostEqual(result, T1_PROTOCOLS["sky_susds"]["fallback_apy"],
                               places=4)

    def test_blended_apy_weighted_correctly(self):
        """50/50 mix of two protocols → arithmetic mean of their APYs."""
        apys = _default_apys()
        alloc = {"sky_susds": 0.5,
                 "morpho_blue_usdc": 0.5,
                 "aave_v3_usdc": 0.0,
                 "compound_v3_usdc": 0.0}
        expected = 0.5 * apys["sky_susds"] + 0.5 * apys["morpho_blue_usdc"]
        result = self.opt.blended_apy(allocation=alloc)
        self.assertAlmostEqual(result, expected, places=6)


# ---------------------------------------------------------------------------
# Group 6: allocation_report()
# ---------------------------------------------------------------------------

class TestAllocationReport(unittest.TestCase):

    def setUp(self):
        self.opt = _FakeOptimizer()
        self.report = self.opt.allocation_report()

    def test_returns_dict(self):
        self.assertIsInstance(self.report, dict)

    def test_contains_capital_fraction_key(self):
        self.assertIn("capital_fraction", self.report)

    def test_contains_protocols_key(self):
        self.assertIn("protocols", self.report)

    def test_contains_blended_apy_key(self):
        self.assertIn("blended_apy", self.report)

    def test_contains_total_allocated_pct_key(self):
        self.assertIn("total_allocated_pct", self.report)

    def test_contains_optimization_note_key(self):
        self.assertIn("optimization_note", self.report)

    def test_contains_generated_at_key(self):
        self.assertIn("generated_at", self.report)

    def test_total_allocated_pct_approx_100(self):
        self.assertAlmostEqual(self.report["total_allocated_pct"], 100.0, places=4)

    def test_blended_apy_positive(self):
        self.assertGreater(self.report["blended_apy"], 0)

    def test_capital_fraction_matches_constructor(self):
        self.assertAlmostEqual(self.report["capital_fraction"], 0.15, places=9)

    def test_protocols_contains_all_keys(self):
        for pid in T1_PROTOCOLS:
            self.assertIn(pid, self.report["protocols"])

    def test_each_protocol_has_required_fields(self):
        required = {"apy", "allocation_pct", "contribution_apy",
                    "max_allocation_pct", "tier", "chain"}
        for pid, info in self.report["protocols"].items():
            with self.subTest(protocol=pid):
                for field in required:
                    self.assertIn(field, info)

    def test_optimization_note_is_string(self):
        self.assertIsInstance(self.report["optimization_note"], str)

    def test_optimization_note_nonempty(self):
        self.assertTrue(len(self.report["optimization_note"]) > 0)


# ---------------------------------------------------------------------------
# Group 7: save() — atomic write
# ---------------------------------------------------------------------------

class TestSave(unittest.TestCase):

    def setUp(self):
        self.opt = _FakeOptimizer()

    def test_save_creates_file(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            path = os.path.join(tmpdir, "stablecoin_optimizer.json")
            self.opt.save(path=path)
            self.assertTrue(os.path.exists(path))

    def test_save_creates_nested_dirs(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            path = os.path.join(tmpdir, "research", "stablecoin_optimizer.json")
            self.opt.save(path=path)
            self.assertTrue(os.path.exists(path))

    def test_save_output_is_valid_json(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            path = os.path.join(tmpdir, "stablecoin_optimizer.json")
            self.opt.save(path=path)
            with open(path, "r", encoding="utf-8") as fh:
                data = json.load(fh)
            self.assertIsInstance(data, dict)

    def test_save_no_tmp_file_left(self):
        """Atomic write: .tmp file must not exist after save."""
        with tempfile.TemporaryDirectory() as tmpdir:
            path = os.path.join(tmpdir, "stablecoin_optimizer.json")
            self.opt.save(path=path)
            self.assertFalse(os.path.exists(path + ".tmp"))

    def test_save_report_has_blended_apy(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            path = os.path.join(tmpdir, "stablecoin_optimizer.json")
            self.opt.save(path=path)
            with open(path, "r", encoding="utf-8") as fh:
                data = json.load(fh)
            self.assertIn("blended_apy", data)
            self.assertGreater(data["blended_apy"], 0)


# ---------------------------------------------------------------------------
# Group 8: RS-002 slot (capital_fraction=0.16)
# ---------------------------------------------------------------------------

class TestRS002Slot(unittest.TestCase):
    """Verify the optimizer works correctly for RS-002's 16% stablecoin slot."""

    def setUp(self):
        class _FakeRS002(_FakeOptimizer):
            pass
        self.opt = _FakeRS002(capital_fraction=0.16)

    def test_capital_fraction_set_correctly(self):
        self.assertAlmostEqual(self.opt.capital_fraction, 0.16)

    def test_allocation_still_sums_to_one(self):
        alloc = self.opt.optimal_allocation()
        self.assertAlmostEqual(sum(alloc.values()), 1.0, places=9)

    def test_blended_apy_above_rs002_target(self):
        """RS-002 targets ~4%+; blended must exceed that with T1 defaults."""
        result = self.opt.blended_apy()
        self.assertGreater(result, 4.0)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

class TestHelpers(unittest.TestCase):

    def test_iso_now_format(self):
        ts = _iso_now()
        self.assertRegex(ts, r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")

    def test_atomic_write_creates_file(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            path = os.path.join(tmpdir, "out.json")
            _atomic_write(path, {"key": "value"})
            self.assertTrue(os.path.exists(path))

    def test_atomic_write_no_tmp_residue(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            path = os.path.join(tmpdir, "out.json")
            _atomic_write(path, {"key": "value"})
            self.assertFalse(os.path.exists(path + ".tmp"))


if __name__ == "__main__":
    unittest.main()
