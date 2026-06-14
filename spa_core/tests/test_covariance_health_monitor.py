"""
Tests for SPA-V339: covariance health monitoring + Telegram alert.

Covers RiskMonitor.alert_covariance_degraded — the consecutive-degraded
streak tracker that fires once the covariance pipeline has been running on
synthetic fallback data (or failing) for COVARIANCE_DEGRADED_CYCLES_ALERT
cycles in a row.

All tests are offline, deterministic and filesystem-isolated (tmp_path).
No network: a FakeSender records the messages it would have sent.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

# Make spa_core sub-packages importable (mirrors other test modules).
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from alerts.risk_monitor import (  # noqa: E402
    RiskMonitor,
    COVARIANCE_DEGRADED_CYCLES_ALERT,
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
    p = Path(data_dir) / "covariance_health_state.json"
    return json.loads(p.read_text(encoding="utf-8"))


# ──────────────────────────────────────────────────────────────────────────
# Healthy sources
# ──────────────────────────────────────────────────────────────────────────

class TestHealthy:
    def test_live_source_no_alert(self, tmp_path):
        sender = FakeSender()
        mon = RiskMonitor(data_dir=tmp_path)
        res = mon.alert_covariance_degraded("live", sender=sender)
        assert res is False
        assert sender.messages == []
        assert _state(tmp_path)["consecutive_degraded"] == 0

    def test_partial_treated_healthy(self, tmp_path):
        sender = FakeSender()
        mon = RiskMonitor(data_dir=tmp_path)
        res = mon.alert_covariance_degraded("partial", sender=sender)
        assert res is False
        assert sender.messages == []
        assert _state(tmp_path)["consecutive_degraded"] == 0


# ──────────────────────────────────────────────────────────────────────────
# Degraded streak / threshold
# ──────────────────────────────────────────────────────────────────────────

class TestDegradedStreak:
    def test_single_synthetic_no_alert(self, tmp_path):
        sender = FakeSender()
        mon = RiskMonitor(data_dir=tmp_path)
        res = mon.alert_covariance_degraded("synthetic_fallback", sender=sender)
        assert res is False
        assert sender.messages == []
        assert _state(tmp_path)["consecutive_degraded"] == 1

    def test_threshold_fires_once(self, tmp_path):
        sender = FakeSender()
        mon = RiskMonitor(data_dir=tmp_path)

        # First (threshold - 1) cycles: degraded, no alert.
        for _ in range(COVARIANCE_DEGRADED_CYCLES_ALERT - 1):
            assert mon.alert_covariance_degraded(
                "synthetic_fallback", sender=sender
            ) is False
        assert sender.messages == []

        # The threshold-th cycle fires exactly one alert.
        fired = mon.alert_covariance_degraded("synthetic_fallback", sender=sender)
        assert fired is True
        assert len(sender.messages) == 1
        assert "Covariance Degraded" in sender.messages[0]

        st = _state(tmp_path)
        assert st["consecutive_degraded"] == COVARIANCE_DEGRADED_CYCLES_ALERT
        assert st["last_alerted_cycle"] == COVARIANCE_DEGRADED_CYCLES_ALERT

    def test_streak_growth_refires(self, tmp_path):
        sender = FakeSender()
        mon = RiskMonitor(data_dir=tmp_path)

        # Drive to threshold (fires once).
        for _ in range(COVARIANCE_DEGRADED_CYCLES_ALERT):
            mon.alert_covariance_degraded("synthetic_fallback", sender=sender)
        assert len(sender.messages) == 1

        # One more consecutive degraded cycle → streak grew → fires again.
        fired = mon.alert_covariance_degraded("synthetic_fallback", sender=sender)
        assert fired is True
        assert len(sender.messages) == 2
        st = _state(tmp_path)
        assert st["consecutive_degraded"] == COVARIANCE_DEGRADED_CYCLES_ALERT + 1
        assert st["last_alerted_cycle"] == COVARIANCE_DEGRADED_CYCLES_ALERT + 1


# ──────────────────────────────────────────────────────────────────────────
# Recovery
# ──────────────────────────────────────────────────────────────────────────

class TestRecovery:
    def test_live_resets_streak(self, tmp_path):
        sender = FakeSender()
        mon = RiskMonitor(data_dir=tmp_path)

        # Build a degraded streak past threshold (some alerts fire).
        for _ in range(COVARIANCE_DEGRADED_CYCLES_ALERT):
            mon.alert_covariance_degraded("synthetic_fallback", sender=sender)
        msgs_before = len(sender.messages)
        assert msgs_before >= 1

        # Recovery cycle: healthy source → reset, no new alert.
        res = mon.alert_covariance_degraded("live", sender=sender)
        assert res is False
        assert len(sender.messages) == msgs_before
        st = _state(tmp_path)
        assert st["consecutive_degraded"] == 0
        assert st["last_alerted_cycle"] == 0


# ──────────────────────────────────────────────────────────────────────────
# Edge cases
# ──────────────────────────────────────────────────────────────────────────

class TestEdgeCases:
    def test_section_failed_with_none_source_is_degraded(self, tmp_path):
        sender = FakeSender()
        mon = RiskMonitor(data_dir=tmp_path)
        res = mon.alert_covariance_degraded(
            None, sender=sender, section_failed=True
        )
        assert res is False  # first cycle, below threshold
        assert _state(tmp_path)["consecutive_degraded"] == 1

    def test_none_source_is_degraded(self, tmp_path):
        sender = FakeSender()
        mon = RiskMonitor(data_dir=tmp_path)
        mon.alert_covariance_degraded(None, sender=sender)
        assert _state(tmp_path)["consecutive_degraded"] == 1

    def test_corrupt_state_recovers(self, tmp_path):
        p = tmp_path / "covariance_health_state.json"
        p.write_text("{bad json", encoding="utf-8")
        sender = FakeSender()
        mon = RiskMonitor(data_dir=tmp_path)
        # Must not raise; treats state as fresh.
        res = mon.alert_covariance_degraded("synthetic_fallback", sender=sender)
        assert res is False
        assert _state(tmp_path)["consecutive_degraded"] == 1

    def test_never_raises_on_bad_sender(self, tmp_path):
        class BoomSender:
            def send(self, text, parse_mode="HTML"):
                raise RuntimeError("telegram down")

        mon = RiskMonitor(data_dir=tmp_path)
        # Drive to threshold so an alert is attempted.
        for _ in range(COVARIANCE_DEGRADED_CYCLES_ALERT):
            res = mon.alert_covariance_degraded(
                "synthetic_fallback", sender=BoomSender()
            )
        # The send raised internally but was swallowed → returns False.
        assert res is False


# ──────────────────────────────────────────────────────────────────────────
# Persistence across instances
# ──────────────────────────────────────────────────────────────────────────

class TestPersistence:
    def test_state_persists_across_reinstantiation(self, tmp_path):
        sender = FakeSender()

        # Two degraded cycles on separate RiskMonitor instances (same data_dir).
        RiskMonitor(data_dir=tmp_path).alert_covariance_degraded(
            "synthetic_fallback", sender=sender
        )
        RiskMonitor(data_dir=tmp_path).alert_covariance_degraded(
            "synthetic_fallback", sender=sender
        )
        assert _state(tmp_path)["consecutive_degraded"] == 2
        assert sender.messages == []  # still below threshold

        # The threshold-th cycle on yet another fresh instance fires.
        fired = RiskMonitor(data_dir=tmp_path).alert_covariance_degraded(
            "synthetic_fallback", sender=sender
        )
        # If threshold == 3 this fires now; otherwise drive a couple more.
        n = _state(tmp_path)["consecutive_degraded"]
        assert n == 3
        if COVARIANCE_DEGRADED_CYCLES_ALERT <= 3:
            assert fired is True
            assert len(sender.messages) == 1
