"""
Tests for SPA-V342: APY-feed protocol-count drop monitoring + Telegram alert.

Covers RiskMonitor.alert_apy_feed_protocol_drop — the consecutive-drop streak
tracker that fires as soon as historical_apy.json sheds a large fraction of its
protocols (e.g. DeFiLlama partially failed: 7 → 3) or falls below an absolute
protocol floor, before the covariance / Kelly universe silently thins.

Unlike staleness (threshold 2 cycles), a sharp protocol drop alerts on the very
first degraded cycle (threshold 1).

All tests are offline, deterministic and filesystem-isolated (tmp_path).
No network: a FakeSender records the messages it would have sent.
"""

from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

# Make spa_core sub-packages importable (mirrors other test modules).
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from alerts.risk_monitor import (  # noqa: E402
    RiskMonitor,
    APY_FEED_PROTOCOL_DROP_PCT,
    APY_FEED_MIN_PROTOCOLS,
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
    p = Path(data_dir) / "apy_feed_protocol_health_state.json"
    return json.loads(p.read_text(encoding="utf-8"))


def _write_feed(data_dir: Path, n_protocols: int) -> Path:
    """Write a realistic historical_apy.json with n protocols."""
    feed = Path(data_dir) / "historical_apy.json"
    protocols = {
        f"protocol-{i}-usdc-ethereum": [
            {"date": "2026-05-29", "apy": 5.0 + i, "tvl_usd": 1.0e8}
        ]
        for i in range(n_protocols)
    }
    feed.write_text(
        json.dumps({
            "generated_at": "2026-05-30T12:00:00Z",
            "data_source": "defillama",
            "days": 90,
            "protocols": protocols,
        }),
        encoding="utf-8",
    )
    return feed


# Fixed reference clock.
NOW = datetime(2026, 5, 30, 12, 0, 0, tzinfo=timezone.utc)


# ──────────────────────────────────────────────────────────────────────────
# Healthy
# ──────────────────────────────────────────────────────────────────────────

class TestHealthy:
    def test_stable_count_no_alert(self, tmp_path):
        sender = FakeSender()
        mon = RiskMonitor(data_dir=tmp_path)
        # First cycle establishes prev=7 (healthy, no prev to compare).
        r1 = mon.alert_apy_feed_protocol_drop(num_protocols=7, now=NOW, sender=sender)
        # Second cycle: still 7 → healthy.
        r2 = mon.alert_apy_feed_protocol_drop(num_protocols=7, now=NOW, sender=sender)
        assert r1 is False and r2 is False
        assert sender.messages == []
        st = _state(tmp_path)
        assert st["consecutive_drops"] == 0
        assert st["prev_num_protocols"] == 7

    def test_first_cycle_no_prev_no_alert(self, tmp_path):
        sender = FakeSender()
        mon = RiskMonitor(data_dir=tmp_path)
        # First cycle with a healthy count and no prior state → no alert.
        res = mon.alert_apy_feed_protocol_drop(num_protocols=7, now=NOW, sender=sender)
        assert res is False
        assert sender.messages == []
        assert _state(tmp_path)["prev_num_protocols"] == 7

    def test_growth_no_alert(self, tmp_path):
        sender = FakeSender()
        mon = RiskMonitor(data_dir=tmp_path)
        mon.alert_apy_feed_protocol_drop(num_protocols=5, now=NOW, sender=sender)
        res = mon.alert_apy_feed_protocol_drop(num_protocols=7, now=NOW, sender=sender)
        assert res is False
        assert sender.messages == []
        assert _state(tmp_path)["prev_num_protocols"] == 7

    def test_mild_drop_no_alert(self, tmp_path):
        # 7 → 5 is a 28.6% drop, below the 50% threshold and above the floor.
        sender = FakeSender()
        mon = RiskMonitor(data_dir=tmp_path)
        mon.alert_apy_feed_protocol_drop(num_protocols=7, now=NOW, sender=sender)
        res = mon.alert_apy_feed_protocol_drop(num_protocols=5, now=NOW, sender=sender)
        assert res is False
        assert sender.messages == []


# ──────────────────────────────────────────────────────────────────────────
# Sharp drop
# ──────────────────────────────────────────────────────────────────────────

class TestSharpDrop:
    def test_sharp_drop_fires_immediately(self, tmp_path):
        sender = FakeSender()
        mon = RiskMonitor(data_dir=tmp_path)
        # Establish prev=8.
        mon.alert_apy_feed_protocol_drop(num_protocols=8, now=NOW, sender=sender)
        assert sender.messages == []
        # 8 → 3 is a 62.5% drop ≥ 50% → fires on the first degraded cycle.
        fired = mon.alert_apy_feed_protocol_drop(num_protocols=3, now=NOW, sender=sender)
        assert fired is True
        assert len(sender.messages) == 1
        assert "Protocol Drop" in sender.messages[0]
        assert "sharp drop" in sender.messages[0]
        st = _state(tmp_path)
        assert st["consecutive_drops"] == 1
        assert st["last_alerted_cycle"] == 1
        assert st["prev_num_protocols"] == 3

    def test_exactly_50pct_drop_fires(self, tmp_path):
        sender = FakeSender()
        mon = RiskMonitor(data_dir=tmp_path)
        mon.alert_apy_feed_protocol_drop(num_protocols=8, now=NOW, sender=sender)
        # 8 → 4 is exactly 50% (4 <= 8 * 0.5) → degraded.
        fired = mon.alert_apy_feed_protocol_drop(num_protocols=4, now=NOW, sender=sender)
        assert fired is True
        assert APY_FEED_PROTOCOL_DROP_PCT == 0.5

    def test_refire_on_continued_drop(self, tmp_path):
        sender = FakeSender()
        mon = RiskMonitor(data_dir=tmp_path)
        mon.alert_apy_feed_protocol_drop(num_protocols=8, now=NOW, sender=sender)
        mon.alert_apy_feed_protocol_drop(num_protocols=3, now=NOW, sender=sender)  # fire 1
        assert len(sender.messages) == 1
        # Next cycle drops further 3 → 1 (also below floor) → streak grows → refire.
        fired = mon.alert_apy_feed_protocol_drop(num_protocols=1, now=NOW, sender=sender)
        assert fired is True
        assert len(sender.messages) == 2
        st = _state(tmp_path)
        assert st["consecutive_drops"] == 2
        assert st["last_alerted_cycle"] == 2


# ──────────────────────────────────────────────────────────────────────────
# Below absolute floor
# ──────────────────────────────────────────────────────────────────────────

class TestBelowMin:
    def test_below_min_protocols_fires(self, tmp_path):
        sender = FakeSender()
        mon = RiskMonitor(data_dir=tmp_path)
        # No prev, but only 2 protocols < floor of 3 → degraded on first cycle.
        fired = mon.alert_apy_feed_protocol_drop(num_protocols=2, now=NOW, sender=sender)
        assert fired is True
        assert len(sender.messages) == 1
        assert "floor" in sender.messages[0]
        assert APY_FEED_MIN_PROTOCOLS == 3

    def test_at_min_protocols_healthy(self, tmp_path):
        sender = FakeSender()
        mon = RiskMonitor(data_dir=tmp_path)
        # Exactly the floor (3) with no prev → healthy.
        res = mon.alert_apy_feed_protocol_drop(num_protocols=3, now=NOW, sender=sender)
        assert res is False
        assert sender.messages == []


# ──────────────────────────────────────────────────────────────────────────
# Recovery
# ──────────────────────────────────────────────────────────────────────────

class TestRecovery:
    def test_recovery_resets_streak(self, tmp_path):
        sender = FakeSender()
        mon = RiskMonitor(data_dir=tmp_path)
        mon.alert_apy_feed_protocol_drop(num_protocols=8, now=NOW, sender=sender)
        mon.alert_apy_feed_protocol_drop(num_protocols=3, now=NOW, sender=sender)  # fire
        msgs_before = len(sender.messages)
        assert msgs_before == 1
        # Recovery: count back to 7 (7 > 3 * 0.5, above floor) → healthy reset.
        res = mon.alert_apy_feed_protocol_drop(num_protocols=7, now=NOW, sender=sender)
        assert res is False
        assert len(sender.messages) == msgs_before
        st = _state(tmp_path)
        assert st["consecutive_drops"] == 0
        assert st["last_alerted_cycle"] == 0
        assert st["prev_num_protocols"] == 7


# ──────────────────────────────────────────────────────────────────────────
# Unreadable / feed file handling
# ──────────────────────────────────────────────────────────────────────────

class TestUnreadable:
    def test_unreadable_none_degraded_fires(self, tmp_path):
        sender = FakeSender()
        mon = RiskMonitor(data_dir=tmp_path)
        # num_protocols None and no feed_path → unreadable → degraded → fires.
        fired = mon.alert_apy_feed_protocol_drop(num_protocols=None, now=NOW, sender=sender)
        assert fired is True
        assert "unreadable" in sender.messages[0]
        assert _state(tmp_path)["consecutive_drops"] == 1

    def test_missing_feed_file_degraded(self, tmp_path):
        sender = FakeSender()
        mon = RiskMonitor(data_dir=tmp_path)
        missing = tmp_path / "does_not_exist.json"
        fired = mon.alert_apy_feed_protocol_drop(
            feed_path=str(missing), now=NOW, sender=sender
        )
        # Cannot read → num_protocols stays None → unreadable → degraded → fires.
        assert fired is True
        assert _state(tmp_path)["consecutive_drops"] == 1

    def test_corrupt_feed_file_degraded(self, tmp_path):
        sender = FakeSender()
        mon = RiskMonitor(data_dir=tmp_path)
        bad = tmp_path / "historical_apy.json"
        bad.write_text("{not valid json", encoding="utf-8")
        fired = mon.alert_apy_feed_protocol_drop(
            feed_path=str(bad), now=NOW, sender=sender
        )
        assert fired is True
        assert _state(tmp_path)["consecutive_drops"] == 1


# ──────────────────────────────────────────────────────────────────────────
# feed_path real-format reading
# ──────────────────────────────────────────────────────────────────────────

class TestFeedPath:
    def test_reads_protocol_count_from_real_feed(self, tmp_path):
        sender = FakeSender()
        mon = RiskMonitor(data_dir=tmp_path)
        feed = _write_feed(tmp_path, 7)
        res = mon.alert_apy_feed_protocol_drop(
            feed_path=str(feed), now=NOW, sender=sender
        )
        # 7 protocols, no prev → healthy.
        assert res is False
        assert _state(tmp_path)["prev_num_protocols"] == 7

    def test_real_feed_sharp_drop_fires(self, tmp_path):
        sender = FakeSender()
        mon = RiskMonitor(data_dir=tmp_path)
        feed = _write_feed(tmp_path, 7)
        mon.alert_apy_feed_protocol_drop(feed_path=str(feed), now=NOW, sender=sender)
        # DeFiLlama partially failed: rewrite feed with only 3 protocols.
        _write_feed(tmp_path, 3)
        fired = mon.alert_apy_feed_protocol_drop(
            feed_path=str(feed), now=NOW, sender=sender
        )
        assert fired is True
        assert _state(tmp_path)["prev_num_protocols"] == 3

    def test_protocol_history_key_variant(self, tmp_path):
        sender = FakeSender()
        mon = RiskMonitor(data_dir=tmp_path)
        feed = tmp_path / "historical_apy.json"
        feed.write_text(
            json.dumps({
                "protocol_history": {
                    "a-usdc-eth": [], "b-usdc-eth": [], "c-usdc-eth": [],
                    "d-usdc-eth": [], "e-usdc-eth": [],
                }
            }),
            encoding="utf-8",
        )
        res = mon.alert_apy_feed_protocol_drop(
            feed_path=str(feed), now=NOW, sender=sender
        )
        assert res is False
        assert _state(tmp_path)["prev_num_protocols"] == 5


# ──────────────────────────────────────────────────────────────────────────
# Persistence
# ──────────────────────────────────────────────────────────────────────────

class TestPersistence:
    def test_state_persists_across_reinstantiation(self, tmp_path):
        sender = FakeSender()
        RiskMonitor(data_dir=tmp_path).alert_apy_feed_protocol_drop(
            num_protocols=8, now=NOW, sender=sender
        )
        assert _state(tmp_path)["prev_num_protocols"] == 8
        # New instance reads persisted prev=8, sees a sharp drop → fires.
        fired = RiskMonitor(data_dir=tmp_path).alert_apy_feed_protocol_drop(
            num_protocols=3, now=NOW, sender=sender
        )
        assert fired is True
        assert len(sender.messages) == 1
        assert _state(tmp_path)["prev_num_protocols"] == 3


# ──────────────────────────────────────────────────────────────────────────
# Robustness
# ──────────────────────────────────────────────────────────────────────────

class TestRobustness:
    def test_corrupt_state_recovers(self, tmp_path):
        p = tmp_path / "apy_feed_protocol_health_state.json"
        p.write_text("{bad json", encoding="utf-8")
        sender = FakeSender()
        mon = RiskMonitor(data_dir=tmp_path)
        res = mon.alert_apy_feed_protocol_drop(num_protocols=7, now=NOW, sender=sender)
        # Fresh state recovered → no prev → healthy.
        assert res is False
        assert _state(tmp_path)["prev_num_protocols"] == 7

    def test_never_raises_on_bad_sender(self, tmp_path):
        class BoomSender:
            def send(self, text, parse_mode="HTML"):
                raise RuntimeError("telegram down")

        mon = RiskMonitor(data_dir=tmp_path)
        mon.alert_apy_feed_protocol_drop(num_protocols=8, now=NOW, sender=BoomSender())
        # Sharp drop attempts a send which raises internally → swallowed → False.
        res = mon.alert_apy_feed_protocol_drop(
            num_protocols=2, now=NOW, sender=BoomSender()
        )
        assert res is False
        # Streak still grew and was persisted despite the send failure.
        assert _state(tmp_path)["consecutive_drops"] == 1

    def test_naive_now_treated_as_utc(self, tmp_path):
        sender = FakeSender()
        mon = RiskMonitor(data_dir=tmp_path)
        naive_now = datetime(2026, 5, 30, 12, 0, 0)  # no tzinfo
        res = mon.alert_apy_feed_protocol_drop(
            num_protocols=7, now=naive_now, sender=sender
        )
        assert res is False
        assert _state(tmp_path)["prev_num_protocols"] == 7
