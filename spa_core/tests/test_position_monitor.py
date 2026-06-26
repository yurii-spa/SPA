#!/usr/bin/env python3
"""Tests for spa_core.execution.position_monitor.PositionMonitor.

PositionMonitor is the POST-EXECUTION verification + anomaly-detection layer of
the live execution path. At go-live it confirms that on-chain state matches the
intended state after a transaction and flags APY deviation / anomalies.

Coverage:
  * APY deviation beyond tolerance flagged
  * anomaly detection (APY out of expected range, deviation spikes, stale data)
  * healthy position passes (no anomalies)
  * fail-CLOSED on missing data (no positions / missing files → no silent "OK")
  * post-execution verification (verified True/False)

Hermetic: every test writes its own JSON into a tmp data dir; no real repo state.
These tests are READ-ONLY against the monitor code — no behaviour changes.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone, timedelta

import pytest

from spa_core.execution.position_monitor import PositionMonitor


# ─── Helpers ─────────────────────────────────────────────────────────────────


def _iso(dt: datetime) -> str:
    return dt.isoformat()


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _write(data_dir, name, obj):
    (data_dir / name).write_text(json.dumps(obj), encoding="utf-8")


@pytest.fixture()
def data_dir(tmp_path):
    d = tmp_path / "data"
    d.mkdir()
    return d


@pytest.fixture()
def monitor(data_dir):
    return PositionMonitor(data_dir=str(data_dir), mode="paper")


def _healthy_status(now=None):
    now = now or _now()
    return {
        "timestamp": _iso(now),
        "positions": [
            {
                "protocol_key": "aave-v3",
                "token": "USDC",
                "amount_usd": 40_000.0,
                "apy": 5.0,  # inside expected (2.5, 8.0)
                "last_updated": _iso(now),
            }
        ],
        "portfolio": {"total_drawdown_pct": 0.0},
    }


# ═══════════════════════════════════════════════════════════════════════════
# Live mode is gated
# ═══════════════════════════════════════════════════════════════════════════


def test_live_mode_not_implemented(data_dir):
    with pytest.raises(NotImplementedError):
        PositionMonitor(data_dir=str(data_dir), mode="live")


# ═══════════════════════════════════════════════════════════════════════════
# Position reads
# ═══════════════════════════════════════════════════════════════════════════


class TestPositionReads:
    def test_get_positions_from_status(self, monitor, data_dir):
        _write(data_dir, "status.json", _healthy_status())
        positions = monitor.get_positions()
        assert len(positions) == 1
        p = positions[0]
        assert p["protocol"] == "aave-v3"
        assert p["amount_usd"] == 40_000.0
        assert p["source"] == "paper_db"

    def test_missing_status_returns_empty(self, monitor):
        # No status.json written → empty list, NOT a crash (read fails closed to []).
        assert monitor.get_positions() == []

    def test_malformed_status_returns_empty(self, monitor, data_dir):
        (data_dir / "status.json").write_text("{not json", encoding="utf-8")
        assert monitor.get_positions() == []


# ═══════════════════════════════════════════════════════════════════════════
# APY deviation
# ═══════════════════════════════════════════════════════════════════════════


class TestApyDeviation:
    def _status_with_apy(self, current_apy, now=None):
        now = now or _now()
        return {
            "timestamp": _iso(now),
            "positions": [
                {
                    "protocol_key": "aave-v3",
                    "amount_usd": 10_000.0,
                    "apy": current_apy,
                    "last_updated": _iso(now),
                }
            ],
        }

    def _history(self, apy, n=5, now=None):
        now = now or _now()
        return {
            "aave-v3": [
                {"timestamp": _iso(now - timedelta(days=i)), "apy": apy}
                for i in range(n)
            ]
        }

    def test_zero_deviation_when_current_matches_average(self, monitor, data_dir):
        _write(data_dir, "status.json", self._status_with_apy(5.0))
        _write(data_dir, "historical_apy.json", self._history(5.0))
        assert monitor.get_apy_deviation("aave-v3") == 0.0

    def test_large_positive_deviation_detected(self, monitor, data_dir):
        # avg 5%, current 10% → +100% deviation
        _write(data_dir, "status.json", self._status_with_apy(10.0))
        _write(data_dir, "historical_apy.json", self._history(5.0))
        dev = monitor.get_apy_deviation("aave-v3")
        assert dev == pytest.approx(100.0, abs=0.5)

    def test_large_negative_deviation_detected(self, monitor, data_dir):
        # avg 5%, current 2.5% → -50% deviation
        _write(data_dir, "status.json", self._status_with_apy(2.5))
        _write(data_dir, "historical_apy.json", self._history(5.0))
        dev = monitor.get_apy_deviation("aave-v3")
        assert dev == pytest.approx(-50.0, abs=0.5)

    def test_insufficient_history_returns_zero(self, monitor, data_dir):
        # Fewer than 3 history points → 0.0 (cannot compute a meaningful average).
        _write(data_dir, "status.json", self._status_with_apy(10.0))
        _write(data_dir, "historical_apy.json", self._history(5.0, n=2))
        assert monitor.get_apy_deviation("aave-v3") == 0.0

    def test_missing_position_returns_zero(self, monitor, data_dir):
        # No matching position → 0.0 (no current APY available).
        _write(data_dir, "status.json", {"positions": []})
        _write(data_dir, "historical_apy.json", self._history(5.0))
        assert monitor.get_apy_deviation("aave-v3") == 0.0


# ═══════════════════════════════════════════════════════════════════════════
# Anomaly detection
# ═══════════════════════════════════════════════════════════════════════════


class TestAnomalyDetection:
    def test_healthy_position_no_anomalies(self, monitor, data_dir):
        now = _now()
        status = _healthy_status(now)
        # 7-day flat history matching current APY → no deviation anomaly.
        _write(data_dir, "status.json", status)
        _write(
            data_dir, "historical_apy.json",
            {"aave-v3": [{"timestamp": _iso(now - timedelta(days=i)), "apy": 5.0} for i in range(5)]},
        )
        assert monitor.detect_anomalies() == []

    def test_apy_below_minimum_flagged_alert(self, monitor, data_dir):
        now = _now()
        status = _healthy_status(now)
        status["positions"][0]["apy"] = 1.0  # below expected min 2.5 for aave-v3
        _write(data_dir, "status.json", status)
        anomalies = monitor.detect_anomalies()
        types = {a["type"] for a in anomalies}
        assert "apy_below_minimum" in types
        below = next(a for a in anomalies if a["type"] == "apy_below_minimum")
        assert below["severity"] == "ALERT"

    def test_apy_above_maximum_flagged_warn(self, monitor, data_dir):
        now = _now()
        status = _healthy_status(now)
        status["positions"][0]["apy"] = 50.0  # above expected max 8.0
        _write(data_dir, "status.json", status)
        anomalies = monitor.detect_anomalies()
        types = {a["type"] for a in anomalies}
        assert "apy_above_maximum" in types

    def test_apy_deviation_spike_flagged(self, monitor, data_dir):
        now = _now()
        status = _healthy_status(now)
        status["positions"][0]["apy"] = 5.0  # within range, but deviates vs history
        _write(data_dir, "status.json", status)
        # 7-day avg ~3.0 → current 5.0 is +66% deviation → ALERT (>= 40%)
        _write(
            data_dir, "historical_apy.json",
            {"aave-v3": [{"timestamp": _iso(now - timedelta(days=i)), "apy": 3.0} for i in range(5)]},
        )
        anomalies = monitor.detect_anomalies()
        types = {a["type"] for a in anomalies}
        assert "apy_spike" in types

    def test_stale_position_flagged(self, monitor, data_dir):
        now = _now()
        status = _healthy_status(now)
        # last_updated 5h ago → > 2h staleness threshold
        status["positions"][0]["last_updated"] = _iso(now - timedelta(hours=5))
        _write(data_dir, "status.json", status)
        anomalies = monitor.detect_anomalies()
        types = {a["type"] for a in anomalies}
        assert "stale_position_data" in types

    def test_no_positions_no_anomalies(self, monitor):
        # Fail-safe: with no data the scan returns [] (no crash). Health check
        # is the layer that flags the missing-data condition (see TestHealthCheck).
        assert monitor.detect_anomalies() == []


# ═══════════════════════════════════════════════════════════════════════════
# Post-execution verification
# ═══════════════════════════════════════════════════════════════════════════


class TestPostExecutionVerification:
    def test_verified_when_position_present(self, monitor, data_dir):
        _write(data_dir, "status.json", _healthy_status())
        res = monitor.verify_post_execution("aave-v3", "supply", 40_000.0, tx_hash="0xabc")
        assert res["verified"] is True
        assert res["protocol"] == "aave-v3"
        assert res["current_balance"] == 40_000.0
        assert res["tx_hash"] == "0xabc"

    def test_not_verified_when_position_absent(self, monitor, data_dir):
        # Fail-closed: no position for the protocol → verified False (not a silent OK).
        _write(data_dir, "status.json", {"positions": []})
        res = monitor.verify_post_execution("aave-v3", "supply", 40_000.0)
        assert res["verified"] is False
        assert res["current_balance"] is None
        assert "no position" in res["message"].lower()

    def test_not_verified_when_status_missing(self, monitor):
        # No status.json at all → verified False (fail-closed).
        res = monitor.verify_post_execution("aave-v3", "supply", 40_000.0)
        assert res["verified"] is False


# ═══════════════════════════════════════════════════════════════════════════
# Health check (fail-closed on missing/stale data)
# ═══════════════════════════════════════════════════════════════════════════


class TestHealthCheck:
    def test_healthy_when_fresh_and_clean(self, monitor, data_dir):
        now = _now()
        status = _healthy_status(now)
        _write(data_dir, "status.json", status)
        _write(
            data_dir, "historical_apy.json",
            {"aave-v3": [{"timestamp": _iso(now - timedelta(days=i)), "apy": 5.0} for i in range(5)]},
        )
        hc = monitor.health_check()
        assert hc["healthy"] is True
        assert hc["issues"] == []
        assert hc["positions_count"] == 1

    def test_unhealthy_when_status_missing(self, monitor):
        # Fail-closed: missing status.json → not healthy, issue recorded.
        hc = monitor.health_check()
        assert hc["healthy"] is False
        assert any("status.json" in i for i in hc["issues"])

    def test_unhealthy_on_stale_status_timestamp(self, monitor, data_dir):
        now = _now()
        status = _healthy_status(now)
        status["timestamp"] = _iso(now - timedelta(hours=10))  # > 6h freshness
        _write(data_dir, "status.json", status)
        hc = monitor.health_check()
        assert hc["healthy"] is False
        assert any("old" in i for i in hc["issues"])

    def test_unhealthy_on_alert_anomaly(self, monitor, data_dir):
        now = _now()
        status = _healthy_status(now)
        status["positions"][0]["apy"] = 1.0  # below minimum → ALERT anomaly
        _write(data_dir, "status.json", status)
        hc = monitor.health_check()
        assert hc["healthy"] is False
        assert any("ALERT" in i for i in hc["issues"])
