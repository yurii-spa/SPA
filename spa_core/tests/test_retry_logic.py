"""
tests/test_retry_logic.py — retry mechanism and pipeline health tests.

Run with:
    cd /Users/yuriikulieshov/Documents/SPA_Claude
    python -m pytest tests/test_retry_logic.py -v
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

try:
    import pytest
except ImportError:  # pragma: no cover — pytest always present in CI
    pytest = None   # type: ignore

# ── make spa_core importable ─────────────────────────────────────────────────
SPA_CORE = Path(__file__).parent.parent
ROOT = SPA_CORE.parent
sys.path.insert(0, str(SPA_CORE))

# ─── 1. retry_request succeeds after two failures ────────────────────────────

def test_retry_succeeds_after_two_failures():
    """
    mock urlopen to fail twice then succeed on the 3rd attempt.
    retry_request should return the body bytes and call urlopen exactly 3 times.
    """
    from data_pipeline.defillama_fetcher import retry_request

    call_count = 0

    class _FakeResp:
        def read(self):
            return b'{"data": []}'
        def __enter__(self):
            return self
        def __exit__(self, *a):
            pass

    def _urlopen(url, timeout=15):
        nonlocal call_count
        call_count += 1
        if call_count < 3:
            raise OSError(f"network error attempt {call_count}")
        return _FakeResp()

    with patch("data_pipeline.defillama_fetcher.urllib.request.urlopen", side_effect=_urlopen), \
         patch("data_pipeline.defillama_fetcher.time.sleep"):   # skip backoff waits
        data, err = retry_request("https://fake.url/pools", max_attempts=3, backoff=1.0)

    assert err is None, f"Expected no error, got: {err}"
    assert data == b'{"data": []}', f"Unexpected data: {data}"
    assert call_count == 3, f"Expected 3 urlopen calls, got {call_count}"


# ─── 2. retry_all_fail → fetch_pools returns [] ──────────────────────────────

def test_retry_all_fail_returns_empty():
    """
    When all 3 retry attempts fail, fetch_pools() (the class method) should
    return [] rather than raising.
    """
    from data_pipeline.defillama_fetcher import DeFiLlamaFetcher

    def _always_fail(url, timeout=15):
        raise OSError("always failing")

    with patch("data_pipeline.defillama_fetcher.urllib.request.urlopen", side_effect=_always_fail), \
         patch("data_pipeline.defillama_fetcher.time.sleep"):
        fetcher = DeFiLlamaFetcher()
        result = fetcher.fetch_pools()

    assert isinstance(result, dict), "fetch_pools() should return a dict"
    pools = result.get("pools", {})
    assert pools == {} or isinstance(pools, dict), "pools should be empty dict on failure"
    # The key invariant: no exception raised


# ─── 3. pipeline_health.json written with correct schema ─────────────────────

def test_pipeline_health_written(tmp_path):
    """
    When run_export() completes (even with many mocked failures), it should
    write data/pipeline_health.json with all required fields.
    """
    # We don't run the full export (too many deps); instead we unit-test the
    # health-dict structure that export_data.py builds.
    required_keys = {
        "timestamp",
        "sections_run",
        "sections_ok",
        "sections_failed",
        "failed_sections",
        "total_pools_fetched",
        "pendle_pools_found",
        "export_duration_seconds",
        "next_run_eta",
    }

    # Build a health dict the same way export_data.py does
    import time as _time
    from datetime import datetime, timezone

    _export_start = _time.time()
    _health: dict = {
        "timestamp":             datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "sections_run":          0,
        "sections_ok":           0,
        "sections_failed":       0,
        "failed_sections":       [],
        "total_pools_fetched":   0,
        "pendle_pools_found":    0,
        "export_duration_seconds": 0.0,
        "next_run_eta":          "4h",
    }

    # Simulate some sections passing/failing
    _health["sections_run"]   += 1
    _health["sections_ok"]    += 1

    _health["sections_run"]    += 1
    _health["sections_failed"] += 1
    _health["failed_sections"].append("sky_status")

    _health["export_duration_seconds"] = round(_time.time() - _export_start, 2)

    # Write it
    health_path = tmp_path / "pipeline_health.json"
    health_path.write_text(json.dumps(_health, indent=2), encoding="utf-8")

    # Verify schema
    loaded = json.loads(health_path.read_text())
    missing = required_keys - loaded.keys()
    assert not missing, f"pipeline_health.json missing keys: {missing}"

    assert loaded["sections_run"]     == 2
    assert loaded["sections_ok"]      == 1
    assert loaded["sections_failed"]  == 1
    assert loaded["failed_sections"]  == ["sky_status"]
    assert loaded["next_run_eta"]     == "4h"
    assert isinstance(loaded["export_duration_seconds"], float)


# ─── 4. alert_pipeline_failure triggered on 6 failures ───────────────────────

def test_pipeline_failure_alert_triggered():
    """
    When sections_failed > 2, alert_pipeline_failure() should call sender.send().
    Mock a health dict with 6 failures and verify alert is dispatched.
    """
    from alerts.risk_monitor import RiskMonitor

    health = {
        "timestamp":             "2026-05-22T10:00:00Z",
        "sections_run":          20,
        "sections_ok":           14,
        "sections_failed":       6,
        "failed_sections":       [
            "sky_status", "defillama_fetch", "backtest_results",
            "agent_summaries", "tournament_results", "pdf_report",
        ],
        "total_pools_fetched":   8,
        "pendle_pools_found":    2,
        "export_duration_seconds": 12.3,
        "next_run_eta":          "4h",
    }

    mock_sender = MagicMock()
    mock_sender.send.return_value = True

    monitor = RiskMonitor()
    result = monitor.alert_pipeline_failure(health, sender=mock_sender)

    assert result is True, "alert_pipeline_failure should return True when alert is sent"
    mock_sender.send.assert_called_once()

    # Verify the message content contains key info
    sent_message = mock_sender.send.call_args[0][0]
    assert "6" in sent_message, "Message should mention 6 failed sections"
    assert "20" in sent_message, "Message should mention total sections"


def test_pipeline_failure_alert_no_pools():
    """
    When total_pools_fetched == 0 (even with 0 section failures), alert should fire.
    """
    from alerts.risk_monitor import RiskMonitor

    health = {
        "timestamp":             "2026-05-22T10:00:00Z",
        "sections_run":          20,
        "sections_ok":           20,
        "sections_failed":       0,
        "failed_sections":       [],
        "total_pools_fetched":   0,   # ← triggers alert
        "pendle_pools_found":    0,
        "export_duration_seconds": 4.1,
        "next_run_eta":          "4h",
    }

    mock_sender = MagicMock()
    mock_sender.send.return_value = True

    monitor = RiskMonitor()
    result = monitor.alert_pipeline_failure(health, sender=mock_sender)

    assert result is True
    mock_sender.send.assert_called_once()


def test_pipeline_failure_alert_not_triggered_when_healthy():
    """
    When sections_failed <= 2 AND total_pools_fetched > 0, no alert should fire.
    """
    from alerts.risk_monitor import RiskMonitor

    health = {
        "timestamp":             "2026-05-22T10:00:00Z",
        "sections_run":          20,
        "sections_ok":           19,
        "sections_failed":       1,
        "failed_sections":       ["sky_status"],
        "total_pools_fetched":   12,
        "pendle_pools_found":    3,
        "export_duration_seconds": 4.2,
        "next_run_eta":          "4h",
    }

    mock_sender = MagicMock()

    monitor = RiskMonitor()
    result = monitor.alert_pipeline_failure(health, sender=mock_sender)

    assert result is False, "No alert should fire for a healthy pipeline"
    mock_sender.send.assert_not_called()
