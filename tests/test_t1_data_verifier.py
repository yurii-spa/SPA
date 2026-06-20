"""
tests/test_t1_data_verifier.py

MP-1394 (v10.10): 35 tests for spa_core/analytics/t1_data_verifier.py

Test coverage:
  - T1DataVerifier instantiation and attributes
  - T1_EXPECTED_RANGES structure and contents
  - verify_adapter() with mocked APY → PASS/FAIL/WARN verdicts
  - verify_all_t1() returns list covering all expected adapters
  - all_pass() returns correct bool
  - save() creates atomic JSON file
  - to_markdown() returns formatted string
"""
import json
import os
import sys
import unittest
import tempfile
from unittest.mock import patch, MagicMock

_REPO = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if _REPO not in sys.path:
    sys.path.insert(0, _REPO)

from spa_core.analytics.t1_data_verifier import (
    T1DataVerifier,
    T1_EXPECTED_RANGES,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _verifier_with_apy(apy_decimal: float | None) -> T1DataVerifier:
    """Return a T1DataVerifier whose _get_apy() always returns apy_decimal."""
    v = T1DataVerifier()
    v._get_apy = lambda adapter_id: apy_decimal
    return v


# ===========================================================================
# 1. T1_EXPECTED_RANGES structure
# ===========================================================================

class TestT1ExpectedRanges(unittest.TestCase):

    def test_is_dict(self):
        self.assertIsInstance(T1_EXPECTED_RANGES, dict)

    def test_contains_sky_susds(self):
        self.assertIn("sky_susds", T1_EXPECTED_RANGES)

    def test_contains_spark_susds(self):
        self.assertIn("spark_susds", T1_EXPECTED_RANGES)

    def test_contains_aave_usdc(self):
        self.assertIn("aave_usdc", T1_EXPECTED_RANGES)

    def test_contains_morpho_usdc(self):
        self.assertIn("morpho_usdc", T1_EXPECTED_RANGES)

    def test_each_entry_has_min_apy(self):
        for aid, rng in T1_EXPECTED_RANGES.items():
            with self.subTest(adapter=aid):
                self.assertIn("min_apy", rng)

    def test_each_entry_has_max_apy(self):
        for aid, rng in T1_EXPECTED_RANGES.items():
            with self.subTest(adapter=aid):
                self.assertIn("max_apy", rng)

    def test_min_less_than_max_for_all(self):
        for aid, rng in T1_EXPECTED_RANGES.items():
            with self.subTest(adapter=aid):
                self.assertLess(
                    rng["min_apy"], rng["max_apy"],
                    f"{aid}: min_apy must be < max_apy"
                )

    def test_apy_values_are_numeric(self):
        for aid, rng in T1_EXPECTED_RANGES.items():
            for key in ("min_apy", "max_apy"):
                with self.subTest(adapter=aid, key=key):
                    self.assertIsInstance(rng[key], (int, float))


# ===========================================================================
# 2. T1DataVerifier instantiation
# ===========================================================================

class TestT1DataVerifierInstantiation(unittest.TestCase):

    def test_instantiates_with_defaults(self):
        v = T1DataVerifier()
        self.assertIsNotNone(v)

    def test_instantiates_with_base_dir(self):
        v = T1DataVerifier(base_dir="/tmp")
        self.assertEqual(v.base_dir, "/tmp")

    def test_has_verify_adapter_method(self):
        self.assertTrue(callable(T1DataVerifier().verify_adapter))

    def test_has_verify_all_t1_method(self):
        self.assertTrue(callable(T1DataVerifier().verify_all_t1))

    def test_has_all_pass_method(self):
        self.assertTrue(callable(T1DataVerifier().all_pass))

    def test_has_save_method(self):
        self.assertTrue(callable(T1DataVerifier().save))

    def test_has_to_markdown_method(self):
        self.assertTrue(callable(T1DataVerifier().to_markdown))


# ===========================================================================
# 3. verify_adapter() — return shape
# ===========================================================================

class TestVerifyAdapterShape(unittest.TestCase):

    def _result(self, apy):
        v = _verifier_with_apy(apy)
        return v.verify_adapter("aave_usdc")

    def test_returns_dict(self):
        self.assertIsInstance(self._result(0.05), dict)

    def test_has_adapter_id(self):
        self.assertIn("adapter_id", self._result(0.05))

    def test_adapter_id_echoed(self):
        self.assertEqual(self._result(0.05)["adapter_id"], "aave_usdc")

    def test_has_apy_key(self):
        self.assertIn("apy", self._result(0.05))

    def test_has_in_range_key(self):
        self.assertIn("in_range", self._result(0.05))

    def test_has_source_responded_key(self):
        self.assertIn("source_responded", self._result(0.05))

    def test_has_expected_range_key(self):
        self.assertIn("expected_range", self._result(0.05))

    def test_has_verdict_key(self):
        self.assertIn("verdict", self._result(0.05))


# ===========================================================================
# 4. verify_adapter() — verdict logic
# ===========================================================================

class TestVerifyAdapterVerdicts(unittest.TestCase):

    def _result(self, adapter_id, apy):
        v = _verifier_with_apy(apy)
        return v.verify_adapter(adapter_id)

    # aave_usdc range is 2.0–8.0 %
    def test_apy_in_range_gives_pass(self):
        r = self._result("aave_usdc", 0.05)   # 5.0% → in [2,8]
        self.assertEqual(r["verdict"], "PASS")

    def test_apy_in_range_gives_source_responded_true(self):
        r = self._result("aave_usdc", 0.05)
        self.assertTrue(r["source_responded"])

    def test_apy_in_range_gives_in_range_true(self):
        r = self._result("aave_usdc", 0.05)
        self.assertTrue(r["in_range"])

    def test_apy_zero_gives_fail(self):
        r = self._result("aave_usdc", 0.0)
        self.assertEqual(r["verdict"], "FAIL")

    def test_apy_none_gives_fail(self):
        r = self._result("aave_usdc", None)
        self.assertEqual(r["verdict"], "FAIL")

    def test_apy_none_gives_source_responded_false(self):
        r = self._result("aave_usdc", None)
        self.assertFalse(r["source_responded"])

    def test_apy_zero_gives_source_responded_false(self):
        r = self._result("aave_usdc", 0.0)
        self.assertFalse(r["source_responded"])

    def test_apy_above_max_gives_warn(self):
        # aave_usdc max 8.0% → 0.20 decimal = 20% → out of range
        r = self._result("aave_usdc", 0.20)
        self.assertEqual(r["verdict"], "WARN")

    def test_apy_below_min_gives_warn(self):
        # aave_usdc min 2.0% → 0.005 decimal = 0.5% → below min
        r = self._result("aave_usdc", 0.005)
        self.assertEqual(r["verdict"], "WARN")

    def test_apy_warn_gives_source_responded_true(self):
        r = self._result("aave_usdc", 0.20)
        self.assertTrue(r["source_responded"])

    def test_apy_stored_as_pct(self):
        # adapter returns decimal 0.05 → stored as 5.0 in result
        r = self._result("aave_usdc", 0.05)
        self.assertAlmostEqual(r["apy"], 5.0, places=4)

    def test_sky_susds_in_range(self):
        # sky_susds range 4.0–12.0% → 0.07 = 7%
        r = self._result("sky_susds", 0.07)
        self.assertEqual(r["verdict"], "PASS")

    def test_spark_susds_in_range(self):
        # spark range 3.0–10.0% → 0.055 = 5.5%
        r = self._result("spark_susds", 0.055)
        self.assertEqual(r["verdict"], "PASS")

    def test_morpho_usdc_in_range(self):
        # morpho range 3.0–10.0% → 0.065 = 6.5%
        r = self._result("morpho_usdc", 0.065)
        self.assertEqual(r["verdict"], "PASS")


# ===========================================================================
# 5. verify_all_t1()
# ===========================================================================

class TestVerifyAllT1(unittest.TestCase):

    def _all(self, apy):
        return _verifier_with_apy(apy).verify_all_t1()

    def test_returns_list(self):
        self.assertIsInstance(self._all(0.05), list)

    def test_length_matches_expected_ranges(self):
        self.assertEqual(len(self._all(0.05)), len(T1_EXPECTED_RANGES))

    def test_each_element_is_dict(self):
        for r in self._all(0.05):
            self.assertIsInstance(r, dict)

    def test_all_adapter_ids_present(self):
        results = self._all(0.05)
        ids = {r["adapter_id"] for r in results}
        for aid in T1_EXPECTED_RANGES:
            self.assertIn(aid, ids)


# ===========================================================================
# 6. all_pass()
# ===========================================================================

class TestAllPass(unittest.TestCase):

    def test_all_pass_returns_bool(self):
        self.assertIsInstance(_verifier_with_apy(0.05).all_pass(), bool)

    def test_all_pass_false_when_fail(self):
        # APY = None → FAIL for all → all_pass = False
        self.assertFalse(_verifier_with_apy(None).all_pass())

    def test_all_pass_false_when_warn(self):
        # APY far out of range for all → WARN → all_pass = False
        self.assertFalse(_verifier_with_apy(0.50).all_pass())

    def test_all_pass_true_when_all_in_range(self):
        # 0.05 (5%) is inside every adapter's range in T1_EXPECTED_RANGES
        self.assertTrue(_verifier_with_apy(0.05).all_pass())


# ===========================================================================
# 7. save()
# ===========================================================================

class TestSave(unittest.TestCase):

    def test_save_creates_file(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            v = T1DataVerifier(base_dir=tmpdir)
            v._get_apy = lambda aid: 0.05
            path = v.save()
            self.assertTrue(os.path.exists(path))

    def test_save_returns_str(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            v = T1DataVerifier(base_dir=tmpdir)
            v._get_apy = lambda aid: 0.05
            result = v.save()
            self.assertIsInstance(result, str)

    def test_save_file_is_valid_json(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            v = T1DataVerifier(base_dir=tmpdir)
            v._get_apy = lambda aid: 0.05
            path = v.save()
            with open(path) as fh:
                data = json.load(fh)
            self.assertIn("results", data)

    def test_save_contains_verified_at(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            v = T1DataVerifier(base_dir=tmpdir)
            v._get_apy = lambda aid: 0.05
            path = v.save()
            with open(path) as fh:
                data = json.load(fh)
            self.assertIn("verified_at", data)

    def test_save_accepts_explicit_results(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            v = T1DataVerifier(base_dir=tmpdir)
            results = [{"adapter_id": "aave_usdc", "verdict": "PASS",
                        "apy": 5.0, "in_range": True, "source_responded": True,
                        "expected_range": {"min_apy": 2.0, "max_apy": 8.0}}]
            path = v.save(results=results)
            with open(path) as fh:
                data = json.load(fh)
            self.assertEqual(len(data["results"]), 1)


# ===========================================================================
# 8. to_markdown()
# ===========================================================================

class TestToMarkdown(unittest.TestCase):

    def _md(self, apy=0.05):
        v = _verifier_with_apy(apy)
        return v.to_markdown()

    def test_returns_string(self):
        self.assertIsInstance(self._md(), str)

    def test_contains_pass(self):
        self.assertIn("PASS", self._md(apy=0.05))

    def test_contains_fail(self):
        self.assertIn("FAIL", self._md(apy=None))

    def test_contains_aave_usdc(self):
        self.assertIn("aave_usdc", self._md())

    def test_contains_sky_susds(self):
        self.assertIn("sky_susds", self._md())

    def test_contains_spark_susds(self):
        self.assertIn("spark_susds", self._md())

    def test_contains_expected_range_info(self):
        md = self._md()
        # Range info like "4.0–12.0%" should appear somewhere
        self.assertIn("4.0", md)


if __name__ == "__main__":
    unittest.main(verbosity=2)
