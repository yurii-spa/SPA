"""
Standalone test runner for sky_monitor — no pytest required.
Runs all tests using unittest + unittest.mock only.

Usage:
    cd spa_core
    python tests/run_sky_tests.py
"""
from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

# Ensure spa_core is importable
_SPA_CORE = Path(__file__).parent.parent
if str(_SPA_CORE) not in sys.path:
    sys.path.insert(0, str(_SPA_CORE))

from data_pipeline.sky_monitor import (
    GSM_MIN_HOURS,
    SKY_CURRENT_STATUS,
    check_sky_status,
    check_sky_status_live,
    export_sky_status_json,
    get_sky_allocation_pct,
)


def _make_live(status, gsm_hours=None, source="manual"):
    return {
        "status": status,
        "gsm_hours": gsm_hours,
        "source": source,
        "last_checked": "2026-05-22T00:00:00+00:00",
    }


class TestManualStatus(unittest.TestCase):
    """Test 1 – legacy check_sky_status() returns correct shape."""

    def test_required_keys_present(self):
        result = check_sky_status()
        for key in ("protocol", "watch_condition", "status", "eligible_for_t1",
                    "allocation_pct", "last_checked", "note"):
            self.assertIn(key, result, f"Key '{key}' missing from check_sky_status()")

    def test_protocol_name(self):
        self.assertEqual(check_sky_status()["protocol"], "Sky/sUSDS")

    def test_status_valid_value(self):
        s = check_sky_status()["status"]
        self.assertIn(s, ("PENDING", "ELIGIBLE", "CONFIRMED", "FAILED"))

    def test_eligible_and_allocation_consistent(self):
        r = check_sky_status()
        if r["eligible_for_t1"]:
            self.assertAlmostEqual(r["allocation_pct"], 0.30, places=4)
        else:
            self.assertAlmostEqual(r["allocation_pct"], 0.0, places=4)


class TestAllocationPct(unittest.TestCase):
    """Tests 2 & 3 – get_sky_allocation_pct()."""

    def test_pending_returns_zero(self):
        self.assertAlmostEqual(get_sky_allocation_pct({"status": "PENDING"}), 0.0)

    def test_eligible_returns_030(self):
        self.assertAlmostEqual(get_sky_allocation_pct({"status": "ELIGIBLE"}), 0.30)

    def test_unknown_status_returns_zero(self):
        self.assertAlmostEqual(get_sky_allocation_pct({"status": "UNKNOWN"}), 0.0)

    def test_empty_dict_returns_zero(self):
        self.assertAlmostEqual(get_sky_allocation_pct({}), 0.0)


class TestLiveFallback(unittest.TestCase):
    """Test 4 – fallback to manual when live sources unavailable."""

    @patch("data_pipeline.sky_monitor._fetch_gsm_delay_onchain", return_value=None)
    @patch("data_pipeline.sky_monitor._fetch_gsm_delay_governance_api", return_value=None)
    def test_falls_back_when_both_fail(self, _api, _onchain):
        result = check_sky_status_live()
        self.assertEqual(result["source"], "manual")
        self.assertEqual(result["status"], SKY_CURRENT_STATUS)
        self.assertIsNone(result["gsm_hours"])

    @patch("data_pipeline.sky_monitor._fetch_gsm_delay_onchain", side_effect=RuntimeError("net"))
    @patch("data_pipeline.sky_monitor._fetch_gsm_delay_governance_api", side_effect=RuntimeError("api"))
    def test_no_exception_raised_on_errors(self, _api, _onchain):
        result = check_sky_status_live()
        self.assertIsInstance(result, dict)
        self.assertIn(result["status"], ("PENDING", "ELIGIBLE"))


class TestGSMThreshold(unittest.TestCase):
    """Tests 5 & 6 – GSM hours correctly mapped to ELIGIBLE / PENDING."""

    @patch("data_pipeline.sky_monitor._fetch_gsm_delay_onchain", return_value=48.0)
    def test_exactly_48h_is_eligible(self, _mock):
        r = check_sky_status_live()
        self.assertEqual(r["status"], "ELIGIBLE")
        self.assertAlmostEqual(r["gsm_hours"], 48.0)
        self.assertEqual(r["source"], "onchain")

    @patch("data_pipeline.sky_monitor._fetch_gsm_delay_onchain", return_value=72.0)
    def test_above_48h_is_eligible(self, _mock):
        self.assertEqual(check_sky_status_live()["status"], "ELIGIBLE")

    @patch("data_pipeline.sky_monitor._fetch_gsm_delay_onchain", return_value=24.0)
    def test_below_48h_is_pending(self, _mock):
        r = check_sky_status_live()
        self.assertEqual(r["status"], "PENDING")
        self.assertAlmostEqual(r["gsm_hours"], 24.0)

    @patch("data_pipeline.sky_monitor._fetch_gsm_delay_onchain", return_value=47.9999)
    def test_just_below_threshold_is_pending(self, _mock):
        self.assertEqual(check_sky_status_live()["status"], "PENDING")

    @patch("data_pipeline.sky_monitor._fetch_gsm_delay_onchain", return_value=0.0)
    def test_zero_hours_is_pending(self, _mock):
        self.assertEqual(check_sky_status_live()["status"], "PENDING")

    def test_gsm_min_hours_constant(self):
        """Policy hard requirement: threshold must be 48h."""
        self.assertEqual(GSM_MIN_HOURS, 48.0)


class TestJsonExport(unittest.TestCase):
    """Tests 7 & 10 – export_sky_status_json() writes correct JSON."""

    def _redirect_data_dir(self, tmp_path):
        import data_pipeline.sky_monitor as m
        self._orig = m._DATA_DIR
        m._DATA_DIR = Path(tmp_path)

    def _restore_data_dir(self):
        import data_pipeline.sky_monitor as m
        m._DATA_DIR = self._orig

    def setUp(self):
        import tempfile
        self._tmpdir = tempfile.mkdtemp()
        self._redirect_data_dir(self._tmpdir)

    def tearDown(self):
        self._restore_data_dir()

    def test_writes_file(self):
        path = export_sky_status_json(_make_live("PENDING"))
        self.assertTrue(path.exists())

    def test_valid_json(self):
        path = export_sky_status_json(_make_live("PENDING"))
        data = json.loads(path.read_text())
        self.assertIsInstance(data, dict)

    def test_required_keys(self):
        path = export_sky_status_json(_make_live("PENDING"))
        data = json.loads(path.read_text())
        for key in ("protocol", "watch_condition", "gsm_min_hours",
                    "status", "eligible_for_t1", "allocation_pct",
                    "gsm_hours", "source", "last_checked", "note"):
            self.assertIn(key, data, f"Key '{key}' missing from sky_status.json")

    def test_pending_allocation_zero(self):
        data = json.loads(export_sky_status_json(_make_live("PENDING")).read_text())
        self.assertAlmostEqual(data["allocation_pct"], 0.0)
        self.assertFalse(data["eligible_for_t1"])

    def test_eligible_allocation_030(self):
        data = json.loads(
            export_sky_status_json(_make_live("ELIGIBLE", 72.0, "onchain")).read_text()
        )
        self.assertAlmostEqual(data["allocation_pct"], 0.30)
        self.assertTrue(data["eligible_for_t1"])
        self.assertAlmostEqual(data["gsm_hours"], 72.0)

    def test_filename_is_sky_status_json(self):
        path = export_sky_status_json(_make_live("PENDING"))
        self.assertEqual(path.name, "sky_status.json")

    def test_creates_directory_if_missing(self):
        import data_pipeline.sky_monitor as m
        new_dir = Path(self._tmpdir) / "nested" / "data"
        m._DATA_DIR = new_dir
        path = export_sky_status_json(_make_live("PENDING"))
        self.assertTrue(path.exists())

    def test_no_precomputed_status_calls_live(self):
        with patch("data_pipeline.sky_monitor.check_sky_status_live",
                   return_value=_make_live("PENDING")) as mock_fn:
            export_sky_status_json(None)
            mock_fn.assert_called_once()


class TestApiSourcePath(unittest.TestCase):
    """Test API source fallback path."""

    @patch("data_pipeline.sky_monitor._fetch_gsm_delay_onchain", return_value=None)
    @patch("data_pipeline.sky_monitor._fetch_gsm_delay_governance_api", return_value=48.0)
    def test_api_source_when_onchain_fails(self, _api, _onchain):
        result = check_sky_status_live()
        self.assertEqual(result["source"], "api")
        self.assertEqual(result["status"], "ELIGIBLE")
        self.assertAlmostEqual(result["gsm_hours"], 48.0)


if __name__ == "__main__":
    loader = unittest.TestLoader()
    suite = unittest.TestSuite()
    for cls in (
        TestManualStatus,
        TestAllocationPct,
        TestLiveFallback,
        TestGSMThreshold,
        TestJsonExport,
        TestApiSourcePath,
    ):
        suite.addTests(loader.loadTestsFromTestCase(cls))

    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(suite)
    sys.exit(0 if result.wasSuccessful() else 1)
