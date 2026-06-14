"""
Tests for spa_core/data_pipeline/sky_monitor.py

Covers:
  1. Manual status check (legacy check_sky_status)
  2. Allocation pct for PENDING status → 0.0
  3. Allocation pct for ELIGIBLE status → 0.30
  4. check_sky_status_live() falls back to manual when all live sources fail
  5. check_sky_status_live() returns ELIGIBLE when gsm_hours >= 48
  6. check_sky_status_live() returns PENDING when gsm_hours < 48
  7. JSON export format (sky_status.json contains required keys)
  8. GSM threshold boundary: exactly 48h → ELIGIBLE
  9. GSM threshold boundary: 47.999h → PENDING
 10. export_sky_status_json writes valid JSON and correct allocation_pct
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

# Ensure spa_core is on the path when running from any directory
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


# ─── Helpers ─────────────────────────────────────────────────────────────────

def _make_live_result(status: str, gsm_hours=None, source="manual") -> dict:
    """Build a status dict matching the shape returned by check_sky_status_live."""
    return {
        "status": status,
        "gsm_hours": gsm_hours,
        "source": source,
        "last_checked": "2026-05-22T00:00:00+00:00",
    }


# ─── Test 1: Manual status check ─────────────────────────────────────────────

class TestCheckSkyStatusManual:
    def test_returns_dict_with_required_keys(self):
        result = check_sky_status()
        required = {"protocol", "watch_condition", "status", "eligible_for_t1",
                    "allocation_pct", "last_checked", "note"}
        assert required.issubset(result.keys()), (
            f"Missing keys: {required - result.keys()}"
        )

    def test_protocol_name(self):
        result = check_sky_status()
        assert result["protocol"] == "Sky/sUSDS"

    def test_status_is_string(self):
        result = check_sky_status()
        assert isinstance(result["status"], str)
        assert result["status"] in ("PENDING", "ELIGIBLE", "CONFIRMED", "FAILED")

    def test_eligible_for_t1_consistent_with_status(self):
        result = check_sky_status()
        # eligible_for_t1 must match (status == "ELIGIBLE" or legacy "CONFIRMED")
        expected = result["status"] in ("ELIGIBLE", "CONFIRMED")
        assert result["eligible_for_t1"] == expected

    def test_allocation_pct_consistent_with_status(self):
        result = check_sky_status()
        if result["eligible_for_t1"]:
            assert result["allocation_pct"] == pytest.approx(0.30)
        else:
            assert result["allocation_pct"] == pytest.approx(0.0)


# ─── Test 2 & 3: get_sky_allocation_pct ──────────────────────────────────────

class TestGetSkyAllocationPct:
    def test_pending_returns_zero(self):
        assert get_sky_allocation_pct({"status": "PENDING"}) == pytest.approx(0.0)

    def test_eligible_returns_thirty_pct(self):
        assert get_sky_allocation_pct({"status": "ELIGIBLE"}) == pytest.approx(0.30)

    def test_unknown_status_returns_zero(self):
        assert get_sky_allocation_pct({"status": "UNKNOWN"}) == pytest.approx(0.0)

    def test_missing_status_key_returns_zero(self):
        assert get_sky_allocation_pct({}) == pytest.approx(0.0)


# ─── Test 4: Fallback when all live sources fail ──────────────────────────────

class TestCheckSkyStatusLiveFallback:
    @patch("data_pipeline.sky_monitor._fetch_gsm_delay_onchain", return_value=None)
    @patch("data_pipeline.sky_monitor._fetch_gsm_delay_governance_api", return_value=None)
    def test_falls_back_to_manual_when_live_unavailable(self, mock_api, mock_onchain):
        result = check_sky_status_live()
        assert result["source"] == "manual"
        assert result["status"] == SKY_CURRENT_STATUS
        assert result["gsm_hours"] is None

    @patch("data_pipeline.sky_monitor._fetch_gsm_delay_onchain", side_effect=Exception("network error"))
    @patch("data_pipeline.sky_monitor._fetch_gsm_delay_governance_api", side_effect=Exception("api down"))
    def test_falls_back_gracefully_on_exceptions(self, mock_api, mock_onchain):
        result = check_sky_status_live()
        # Should not raise; must return a valid dict
        assert isinstance(result, dict)
        assert result["status"] in ("PENDING", "ELIGIBLE")
        assert result["source"] == "manual"


# ─── Test 5 & 6: GSM threshold checks via live path ──────────────────────────

class TestGSMThreshold:
    @patch("data_pipeline.sky_monitor._fetch_gsm_delay_onchain", return_value=48.0)
    def test_gsm_exactly_48h_is_eligible(self, mock_onchain):
        result = check_sky_status_live()
        assert result["status"] == "ELIGIBLE"
        assert result["gsm_hours"] == pytest.approx(48.0)
        assert result["source"] == "onchain"

    @patch("data_pipeline.sky_monitor._fetch_gsm_delay_onchain", return_value=72.0)
    def test_gsm_above_48h_is_eligible(self, mock_onchain):
        result = check_sky_status_live()
        assert result["status"] == "ELIGIBLE"

    @patch("data_pipeline.sky_monitor._fetch_gsm_delay_onchain", return_value=24.0)
    def test_gsm_below_48h_is_pending(self, mock_onchain):
        result = check_sky_status_live()
        assert result["status"] == "PENDING"
        assert result["gsm_hours"] == pytest.approx(24.0)

    @patch("data_pipeline.sky_monitor._fetch_gsm_delay_onchain", return_value=47.999)
    def test_gsm_just_below_threshold_is_pending(self, mock_onchain):
        result = check_sky_status_live()
        assert result["status"] == "PENDING"

    @patch("data_pipeline.sky_monitor._fetch_gsm_delay_onchain", return_value=0.0)
    def test_gsm_zero_is_pending(self, mock_onchain):
        result = check_sky_status_live()
        assert result["status"] == "PENDING"

    def test_gsm_min_hours_constant_is_48(self):
        """GSM_MIN_HOURS must remain 48.0 — policy ADR hard requirement."""
        assert GSM_MIN_HOURS == pytest.approx(48.0)


# ─── Test 7 & 10: JSON export format ─────────────────────────────────────────

class TestExportSkyStatusJson:
    def test_export_writes_valid_json(self, tmp_path, monkeypatch):
        # Redirect DATA_DIR to tmp_path
        monkeypatch.setattr(
            "data_pipeline.sky_monitor._DATA_DIR", tmp_path
        )
        status = _make_live_result("PENDING", None, "manual")
        path = export_sky_status_json(status)
        assert path.exists()
        data = json.loads(path.read_text())
        assert isinstance(data, dict)

    def test_export_contains_required_keys(self, tmp_path, monkeypatch):
        monkeypatch.setattr("data_pipeline.sky_monitor._DATA_DIR", tmp_path)
        status = _make_live_result("PENDING", None, "manual")
        path = export_sky_status_json(status)
        data = json.loads(path.read_text())
        required = {
            "protocol", "watch_condition", "gsm_min_hours",
            "status", "eligible_for_t1", "allocation_pct",
            "gsm_hours", "source", "last_checked", "note",
        }
        assert required.issubset(data.keys()), (
            f"Missing keys: {required - data.keys()}"
        )

    def test_export_pending_allocation_is_zero(self, tmp_path, monkeypatch):
        monkeypatch.setattr("data_pipeline.sky_monitor._DATA_DIR", tmp_path)
        status = _make_live_result("PENDING", None, "manual")
        path = export_sky_status_json(status)
        data = json.loads(path.read_text())
        assert data["allocation_pct"] == pytest.approx(0.0)
        assert data["eligible_for_t1"] is False

    def test_export_eligible_allocation_is_30pct(self, tmp_path, monkeypatch):
        monkeypatch.setattr("data_pipeline.sky_monitor._DATA_DIR", tmp_path)
        status = _make_live_result("ELIGIBLE", 72.0, "onchain")
        path = export_sky_status_json(status)
        data = json.loads(path.read_text())
        assert data["allocation_pct"] == pytest.approx(0.30)
        assert data["eligible_for_t1"] is True
        assert data["gsm_hours"] == pytest.approx(72.0)
        assert data["source"] == "onchain"

    def test_export_filename_is_sky_status_json(self, tmp_path, monkeypatch):
        monkeypatch.setattr("data_pipeline.sky_monitor._DATA_DIR", tmp_path)
        status = _make_live_result("PENDING")
        path = export_sky_status_json(status)
        assert path.name == "sky_status.json"

    def test_export_creates_data_dir_if_missing(self, tmp_path, monkeypatch):
        new_dir = tmp_path / "nested" / "data"
        monkeypatch.setattr("data_pipeline.sky_monitor._DATA_DIR", new_dir)
        status = _make_live_result("PENDING")
        path = export_sky_status_json(status)
        assert path.exists()

    def test_export_without_precomputed_status_calls_live(self, tmp_path, monkeypatch):
        """export_sky_status_json(None) should call check_sky_status_live internally."""
        monkeypatch.setattr("data_pipeline.sky_monitor._DATA_DIR", tmp_path)
        mock_status = _make_live_result("PENDING", None, "manual")
        with patch("data_pipeline.sky_monitor.check_sky_status_live",
                   return_value=mock_status) as mock_fn:
            export_sky_status_json(None)
            mock_fn.assert_called_once()


# ─── Test: API source path ─────────────────────────────────────────────────

class TestApiSourcePath:
    @patch("data_pipeline.sky_monitor._fetch_gsm_delay_onchain", return_value=None)
    @patch("data_pipeline.sky_monitor._fetch_gsm_delay_governance_api", return_value=172800.0 / 3600)
    def test_api_source_used_when_onchain_fails(self, mock_api, mock_onchain):
        # governance API returns 48h exactly
        result = check_sky_status_live()
        assert result["source"] == "api"
        assert result["status"] == "ELIGIBLE"
        assert result["gsm_hours"] == pytest.approx(48.0)
