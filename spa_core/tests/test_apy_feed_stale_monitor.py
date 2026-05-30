"""
Tests for SPA-V340: APY-feed staleness monitoring + Telegram alert.

Covers RiskMonitor.alert_apy_feed_stale — the consecutive-stale streak tracker
that fires once historical_apy.json has been stale/stuck/synthetic for
APY_FEED_STALE_CYCLES_ALERT cycles in a row, before the covariance pipeline
silently falls back to synthetic data.

All tests are offline, deterministic and filesystem-isolated (tmp_path).
No network: a FakeSender records the messages it would have sent.
"""

from __future__ import annotations

import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

# Make spa_core sub-packages importable (mirrors other test modules).
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from alerts.risk_monitor import (  # noqa: E402
    RiskMonitor,
    APY_FEED_MAX_AGE_HOURS,
    APY_FEED_STALE_CYCLES_ALERT,
)


# ──────────────────────────────────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────────────────────────────────

class FakeSender:
    """Records messages instead of hitting Telegram. send() always succeeds."""

    def __init__(self, ok: bool = True) -> None:
        self.ok = ok
        self.messages: list[str] = []

    def send(self, text: str, parse_mode: str = "HTML") -> bool:
        self.messages.append(text)
        return self.ok


def _state(data_dir: Path) -> dict:
    p = Path(data_dir) / "apy_feed_health_state.json"
    return json.loads(p.read_text(encoding="utf-8"))


def _iso(dt: datetime) -> str:
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


# Fixed reference clock for deterministic age computations.
NOW = datetime(2026, 5, 30, 12, 0, 0, tzinfo=timezone.utc)


# ──────────────────────────────────────────────────────────────────────────
# Healthy feed
# ──────────────────────────────────────────────────────────────────────────

class TestHealthy:
    def test_fresh_feed_no_alert(self, tmp_path):
        sender = FakeSender()
        mon = RiskMonitor(data_dir=tmp_path)
        res = mon.alert_apy_feed_stale(
            generated_at=_iso(NOW),
            data_source="defillama",
            now=NOW,
            sender=sender,
        )
        assert res is False
        assert sender.messages == []
        assert _state(tmp_path)["consecutive_stale"] == 0


# ──────────────────────────────────────────────────────────────────────────
# Stale streak / threshold
# ──────────────────────────────────────────────────────────────────────────

class TestStaleStreak:
    def test_single_stale_cycle_no_alert(self, tmp_path):
        sender = FakeSender()
        mon = RiskMonitor(data_dir=tmp_path)
        old = NOW - timedelta(hours=APY_FEED_MAX_AGE_HOURS + 1)
        res = mon.alert_apy_feed_stale(
            generated_at=_iso(old),
            data_source="defillama",
            now=NOW,
            sender=sender,
        )
        assert res is False
        assert sender.messages == []
        assert _state(tmp_path)["consecutive_stale"] == 1

    def test_threshold_fires_once(self, tmp_path):
        sender = FakeSender()
        mon = RiskMonitor(data_dir=tmp_path)

        # Distinct old timestamps so "too_old" (not "stuck") drives degradation.
        for i in range(APY_FEED_STALE_CYCLES_ALERT - 1):
            old = NOW - timedelta(hours=APY_FEED_MAX_AGE_HOURS + 1 + i)
            assert mon.alert_apy_feed_stale(
                generated_at=_iso(old), data_source="defillama",
                now=NOW, sender=sender,
            ) is False
        assert sender.messages == []

        old = NOW - timedelta(hours=APY_FEED_MAX_AGE_HOURS + 99)
        fired = mon.alert_apy_feed_stale(
            generated_at=_iso(old), data_source="defillama",
            now=NOW, sender=sender,
        )
        assert fired is True
        assert len(sender.messages) == 1
        assert "APY Feed" in sender.messages[0]

        st = _state(tmp_path)
        assert st["consecutive_stale"] == APY_FEED_STALE_CYCLES_ALERT
        assert st["last_alerted_cycle"] == APY_FEED_STALE_CYCLES_ALERT

    def test_third_stale_refires(self, tmp_path):
        sender = FakeSender()
        mon = RiskMonitor(data_dir=tmp_path)

        # Drive to threshold (fires once) with distinct old timestamps.
        for i in range(APY_FEED_STALE_CYCLES_ALERT):
            old = NOW - timedelta(hours=APY_FEED_MAX_AGE_HOURS + 1 + i)
            mon.alert_apy_feed_stale(
                generated_at=_iso(old), data_source="defillama",
                now=NOW, sender=sender,
            )
        assert len(sender.messages) == 1

        # One more consecutive stale cycle → streak grew → fires again.
        old = NOW - timedelta(hours=APY_FEED_MAX_AGE_HOURS + 500)
        fired = mon.alert_apy_feed_stale(
            generated_at=_iso(old), data_source="defillama",
            now=NOW, sender=sender,
        )
        assert fired is True
        assert len(sender.messages) == 2
        st = _state(tmp_path)
        assert st["consecutive_stale"] == APY_FEED_STALE_CYCLES_ALERT + 1
        assert st["last_alerted_cycle"] == APY_FEED_STALE_CYCLES_ALERT + 1


# ──────────────────────────────────────────────────────────────────────────
# Recovery
# ──────────────────────────────────────────────────────────────────────────

class TestRecovery:
    def test_fresh_resets_streak(self, tmp_path):
        sender = FakeSender()
        mon = RiskMonitor(data_dir=tmp_path)

        # Build a stale streak past threshold (alert fires).
        for i in range(APY_FEED_STALE_CYCLES_ALERT):
            old = NOW - timedelta(hours=APY_FEED_MAX_AGE_HOURS + 1 + i)
            mon.alert_apy_feed_stale(
                generated_at=_iso(old), data_source="defillama",
                now=NOW, sender=sender,
            )
        msgs_before = len(sender.messages)
        assert msgs_before >= 1

        # Recovery cycle: fresh generated_at → reset, no new alert.
        res = mon.alert_apy_feed_stale(
            generated_at=_iso(NOW), data_source="defillama",
            now=NOW, sender=sender,
        )
        assert res is False
        assert len(sender.messages) == msgs_before
        st = _state(tmp_path)
        assert st["consecutive_stale"] == 0
        assert st["last_alerted_cycle"] == 0


# ──────────────────────────────────────────────────────────────────────────
# Degradation signals
# ──────────────────────────────────────────────────────────────────────────

class TestSignals:
    def test_stuck_generated_at_fires(self, tmp_path):
        sender = FakeSender()
        mon = RiskMonitor(data_dir=tmp_path)
        # Same recent generated_at twice (age OK, but stuck → degraded).
        stamp = _iso(NOW - timedelta(hours=1))
        res1 = mon.alert_apy_feed_stale(
            generated_at=stamp, data_source="defillama",
            now=NOW, sender=sender,
        )
        # First cycle records the stamp; not "stuck" yet (no prev) but age OK
        # → healthy, streak 0.
        assert res1 is False
        assert _state(tmp_path)["consecutive_stale"] == 0

        # Second cycle: identical generated_at → stuck → degraded (cycle 1).
        res2 = mon.alert_apy_feed_stale(
            generated_at=stamp, data_source="defillama",
            now=NOW, sender=sender,
        )
        assert _state(tmp_path)["consecutive_stale"] == 1
        # Third identical → cycle 2 hits threshold → fires.
        res3 = mon.alert_apy_feed_stale(
            generated_at=stamp, data_source="defillama",
            now=NOW, sender=sender,
        )
        if APY_FEED_STALE_CYCLES_ALERT <= 2:
            assert res3 is True
            assert len(sender.messages) == 1
            assert "stuck" in sender.messages[0]

    def test_synthetic_source_degraded(self, tmp_path):
        sender = FakeSender()
        mon = RiskMonitor(data_dir=tmp_path)
        # Recent generated_at (age OK), not stuck, but synthetic source.
        res = mon.alert_apy_feed_stale(
            generated_at=_iso(NOW - timedelta(hours=1)),
            data_source="synthetic",
            now=NOW, sender=sender,
        )
        assert res is False  # first cycle, below threshold
        assert _state(tmp_path)["consecutive_stale"] == 1

    def test_missing_feed_file_degraded(self, tmp_path):
        sender = FakeSender()
        mon = RiskMonitor(data_dir=tmp_path)
        missing = tmp_path / "does_not_exist.json"
        res = mon.alert_apy_feed_stale(
            feed_path=str(missing), now=NOW, sender=sender,
        )
        # No generated_at parsed → too_old → degraded; first cycle below thresh.
        assert res is False
        assert _state(tmp_path)["consecutive_stale"] == 1

    def test_corrupt_feed_file_degraded(self, tmp_path):
        sender = FakeSender()
        mon = RiskMonitor(data_dir=tmp_path)
        bad = tmp_path / "historical_apy.json"
        bad.write_text("{not valid json", encoding="utf-8")
        res = mon.alert_apy_feed_stale(
            feed_path=str(bad), now=NOW, sender=sender,
        )
        assert res is False
        assert _state(tmp_path)["consecutive_stale"] == 1


# ──────────────────────────────────────────────────────────────────────────
# feed_path reading
# ──────────────────────────────────────────────────────────────────────────

class TestFeedPath:
    def test_reads_metadata_from_feed(self, tmp_path):
        sender = FakeSender()
        mon = RiskMonitor(data_dir=tmp_path)
        feed = tmp_path / "historical_apy.json"
        feed.write_text(
            json.dumps({
                "generated_at": _iso(NOW),
                "data_source": "defillama",
            }),
            encoding="utf-8",
        )
        res = mon.alert_apy_feed_stale(
            feed_path=str(feed), now=NOW, sender=sender,
        )
        assert res is False
        st = _state(tmp_path)
        assert st["consecutive_stale"] == 0
        assert st["last_generated_at"] == _iso(NOW)
        assert st["last_source"] == "defillama"

    def test_synthetic_from_feed_degraded(self, tmp_path):
        sender = FakeSender()
        mon = RiskMonitor(data_dir=tmp_path)
        feed = tmp_path / "historical_apy.json"
        feed.write_text(
            json.dumps({
                "generated_at": _iso(NOW - timedelta(hours=1)),
                "data_source": "synthetic",
            }),
            encoding="utf-8",
        )
        res = mon.alert_apy_feed_stale(
            feed_path=str(feed), now=NOW, sender=sender,
        )
        assert res is False
        assert _state(tmp_path)["consecutive_stale"] == 1
        assert _state(tmp_path)["last_source"] == "synthetic"


# ──────────────────────────────────────────────────────────────────────────
# Persistence across instances
# ──────────────────────────────────────────────────────────────────────────

class TestPersistence:
    def test_state_persists_across_reinstantiation(self, tmp_path):
        sender = FakeSender()
        old1 = NOW - timedelta(hours=APY_FEED_MAX_AGE_HOURS + 1)
        old2 = NOW - timedelta(hours=APY_FEED_MAX_AGE_HOURS + 2)

        RiskMonitor(data_dir=tmp_path).alert_apy_feed_stale(
            generated_at=_iso(old1), data_source="defillama",
            now=NOW, sender=sender,
        )
        assert _state(tmp_path)["consecutive_stale"] == 1
        RiskMonitor(data_dir=tmp_path).alert_apy_feed_stale(
            generated_at=_iso(old2), data_source="defillama",
            now=NOW, sender=sender,
        )
        st = _state(tmp_path)
        assert st["consecutive_stale"] == 2
        if APY_FEED_STALE_CYCLES_ALERT <= 2:
            assert len(sender.messages) == 1


# ──────────────────────────────────────────────────────────────────────────
# Robustness
# ──────────────────────────────────────────────────────────────────────────

class TestRobustness:
    def test_corrupt_state_recovers(self, tmp_path):
        p = tmp_path / "apy_feed_health_state.json"
        p.write_text("{bad json", encoding="utf-8")
        sender = FakeSender()
        mon = RiskMonitor(data_dir=tmp_path)
        old = NOW - timedelta(hours=APY_FEED_MAX_AGE_HOURS + 1)
        res = mon.alert_apy_feed_stale(
            generated_at=_iso(old), data_source="defillama",
            now=NOW, sender=sender,
        )
        assert res is False
        assert _state(tmp_path)["consecutive_stale"] == 1

    def test_never_raises_on_bad_sender(self, tmp_path):
        class BoomSender:
            def send(self, text, parse_mode="HTML"):
                raise RuntimeError("telegram down")

        mon = RiskMonitor(data_dir=tmp_path)
        # Drive to threshold so an alert is attempted, distinct old stamps.
        res = True
        for i in range(APY_FEED_STALE_CYCLES_ALERT):
            old = NOW - timedelta(hours=APY_FEED_MAX_AGE_HOURS + 1 + i)
            res = mon.alert_apy_feed_stale(
                generated_at=_iso(old), data_source="defillama",
                now=NOW, sender=BoomSender(),
            )
        # The send raised internally but was swallowed → returns False.
        assert res is False

    def test_naive_now_treated_as_utc(self, tmp_path):
        sender = FakeSender()
        mon = RiskMonitor(data_dir=tmp_path)
        naive_now = datetime(2026, 5, 30, 12, 0, 0)  # no tzinfo
        res = mon.alert_apy_feed_stale(
            generated_at="2026-05-30T11:00:00Z",
            data_source="defillama",
            now=naive_now, sender=sender,
        )
        # Age 1h < 8h, fresh → no alert, streak 0.
        assert res is False
        assert _state(tmp_path)["consecutive_stale"] == 0
