"""
tests/test_source_integration_helper.py

25 unit tests for spa_core/analytics/source_integration_helper.py.
File I/O uses temporary directories — no real data files are touched.
"""

import json
import os
import sys
import unittest
import tempfile

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from spa_core.analytics.source_integration_helper import SourceIntegrationHelper

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

VALID_UUID = "abc12345-def6-789a-bcde-f01234567890"
SHORT_ID   = "abc123"
NOT_UUID   = "not-a-valid-uuid-at-all-!!!!"


class TestValidatePoolId(unittest.TestCase):
    """Tests for validate_pool_id()"""

    def _h(self):
        return SourceIntegrationHelper()

    # 1. Short string → invalid
    def test_short_id_invalid(self):
        result = self._h().validate_pool_id(SHORT_ID)
        self.assertFalse(result["valid"])
        self.assertIn("short", result["reason"].lower())

    # 2. Valid UUID → valid
    def test_valid_uuid_returns_valid(self):
        result = self._h().validate_pool_id(VALID_UUID)
        self.assertTrue(result["valid"])

    # 3. Non-UUID string of correct length → invalid
    def test_non_uuid_pattern_invalid(self):
        # 36 chars but wrong format
        bad = "xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx"
        result = self._h().validate_pool_id(bad)
        self.assertFalse(result["valid"])

    # 4. Returns dict with 'valid' and 'reason' keys
    def test_returns_dict_with_correct_keys(self):
        result = self._h().validate_pool_id(VALID_UUID)
        self.assertIn("valid", result)
        self.assertIn("reason", result)

    # 5. Empty string → invalid
    def test_empty_string_invalid(self):
        result = self._h().validate_pool_id("")
        self.assertFalse(result["valid"])

    # 6. Non-string → invalid
    def test_non_string_invalid(self):
        result = self._h().validate_pool_id(12345)
        self.assertFalse(result["valid"])

    # 7. UUID with uppercase hex → valid (case-insensitive)
    def test_uppercase_uuid_valid(self):
        upper = VALID_UUID.upper()
        result = self._h().validate_pool_id(upper)
        self.assertTrue(result["valid"])

    # 8. Valid reason string is non-empty
    def test_valid_reason_is_non_empty(self):
        result = self._h().validate_pool_id(VALID_UUID)
        self.assertIsInstance(result["reason"], str)
        self.assertGreater(len(result["reason"]), 0)

    # 9. Wrong segment count (missing one hyphen group) → invalid
    def test_wrong_segment_count_invalid(self):
        bad = "abc12345-def6-789a-f01234567890"  # only 4 segments
        result = self._h().validate_pool_id(bad)
        self.assertFalse(result["valid"])


class TestGenerateAdapterSnippet(unittest.TestCase):
    """Tests for generate_adapter_snippet()"""

    def _h(self):
        return SourceIntegrationHelper()

    # 10. Returns non-empty string
    def test_returns_non_empty_string(self):
        result = self._h().generate_adapter_snippet("gmx_v2_btc", VALID_UUID, 18.0)
        self.assertIsInstance(result, str)
        self.assertGreater(len(result), 0)

    # 11. Contains the pool_id
    def test_contains_pool_id(self):
        result = self._h().generate_adapter_snippet("gmx_v2_btc", VALID_UUID, 18.0)
        self.assertIn(VALID_UUID, result)

    # 12. Contains the source_name (or sanitized form)
    def test_contains_source_name(self):
        result = self._h().generate_adapter_snippet("gmx_v2_btc", VALID_UUID, 18.0)
        self.assertIn("gmx_v2_btc", result)

    # 13. Contains fallback APY value
    def test_contains_fallback_apy(self):
        result = self._h().generate_adapter_snippet("morpho_usdc", VALID_UUID, 6.5)
        self.assertIn("6.5", result)

    # 14. Generated snippet contains a Python function definition
    def test_contains_def_keyword(self):
        result = self._h().generate_adapter_snippet("sky_susds", VALID_UUID, 5.0)
        self.assertIn("def ", result)

    # 15. Works with default fallback_apy=0.0
    def test_default_fallback_apy(self):
        result = self._h().generate_adapter_snippet("pendle_pt", VALID_UUID)
        self.assertIsInstance(result, str)
        self.assertGreater(len(result), 0)

    # 16. Source names with hyphens are sanitized (no syntax error)
    def test_hyphens_sanitized_in_source_name(self):
        result = self._h().generate_adapter_snippet("gmx-v2-btc", VALID_UUID, 10.0)
        # Hyphens must not appear in Python identifiers in the snippet
        self.assertNotIn("def fetch_gmx-v2-btc", result)
        self.assertIn("def fetch_", result)


class TestUpdateSourcePipeline(unittest.TestCase):
    """Tests for update_source_pipeline()"""

    def _helper_with_tmpdir(self, tmpdir):
        path = os.path.join(tmpdir, "source_pipeline.json")
        return SourceIntegrationHelper(pipeline_path=path), path

    # 17. Creates file when it doesn't exist
    def test_creates_file(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            h, path = self._helper_with_tmpdir(tmpdir)
            result = h.update_source_pipeline("gmx_v2_btc", VALID_UUID)
            self.assertTrue(result)
            self.assertTrue(os.path.exists(path))

    # 18. File contains valid JSON
    def test_file_contains_valid_json(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            h, path = self._helper_with_tmpdir(tmpdir)
            h.update_source_pipeline("gmx_v2_btc", VALID_UUID)
            with open(path, "r") as fh:
                data = json.load(fh)
            self.assertIsInstance(data, dict)

    # 19. Written entry contains source_id
    def test_written_entry_contains_source_id(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            h, path = self._helper_with_tmpdir(tmpdir)
            h.update_source_pipeline("morpho_usdc", VALID_UUID, "TESTING")
            with open(path, "r") as fh:
                data = json.load(fh)
            self.assertIn("morpho_usdc", data["sources"])

    # 20. Written entry contains pool_id
    def test_written_entry_contains_pool_id(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            h, path = self._helper_with_tmpdir(tmpdir)
            h.update_source_pipeline("sky_susds", VALID_UUID, "INTEGRATED")
            with open(path, "r") as fh:
                data = json.load(fh)
            entry = data["sources"]["sky_susds"]
            self.assertEqual(entry["pool_id"], VALID_UUID)

    # 21. Status is recorded correctly
    def test_status_recorded(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            h, path = self._helper_with_tmpdir(tmpdir)
            h.update_source_pipeline("ondo_ousg", VALID_UUID, "CLEAN")
            with open(path, "r") as fh:
                data = json.load(fh)
            self.assertEqual(data["sources"]["ondo_ousg"]["status"], "CLEAN")

    # 22. Multiple calls accumulate sources (no overwrite)
    def test_multiple_calls_accumulate(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            h, path = self._helper_with_tmpdir(tmpdir)
            h.update_source_pipeline("source_a", VALID_UUID, "PENDING")
            h.update_source_pipeline("source_b", VALID_UUID, "TESTING")
            with open(path, "r") as fh:
                data = json.load(fh)
            self.assertIn("source_a", data["sources"])
            self.assertIn("source_b", data["sources"])

    # 23. Returns True on success
    def test_returns_true_on_success(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            h, path = self._helper_with_tmpdir(tmpdir)
            result = h.update_source_pipeline("pendle_pt", VALID_UUID)
            self.assertTrue(result)

    # 24. Default status is PENDING
    def test_default_status_is_pending(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            h, path = self._helper_with_tmpdir(tmpdir)
            h.update_source_pipeline("aave_usdc_arb", VALID_UUID)
            with open(path, "r") as fh:
                data = json.load(fh)
            self.assertEqual(data["sources"]["aave_usdc_arb"]["status"], "PENDING")


class TestIntegrationChecklist(unittest.TestCase):
    """Tests for integration_checklist()"""

    def _h(self):
        return SourceIntegrationHelper()

    # 25. Returns exactly 5 items
    def test_returns_five_items(self):
        result = self._h().integration_checklist("gmx_v2_btc")
        self.assertIsInstance(result, list)
        self.assertEqual(len(result), 5)

    def test_all_items_are_strings(self):
        result = self._h().integration_checklist("sky_susds")
        for item in result:
            self.assertIsInstance(item, str)

    def test_source_id_appears_in_checklist(self):
        result = self._h().integration_checklist("morpho_usdc")
        combined = " ".join(result)
        self.assertIn("morpho_usdc", combined)

    def test_checklist_items_are_non_empty(self):
        result = self._h().integration_checklist("pendle_pt")
        for item in result:
            self.assertGreater(len(item.strip()), 0)


if __name__ == "__main__":
    unittest.main(verbosity=2)
