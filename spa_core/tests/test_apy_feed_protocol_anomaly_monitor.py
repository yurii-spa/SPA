"""
Tests for SPA-V344: APY-feed per-protocol anomaly + dropout monitoring + alert.

Covers RiskMonitor.alert_apy_feed_protocol_anomaly — the consecutive-anomaly
streak tracker that fires as soon as a SPECIFIC protocol disappears from
historical_apy.json between cycles, or its APY / TVL crashes sharply, even when
the aggregate alerts (protocol count, total TVL) stay quiet.

Like the protocol-drop monitor, a point anomaly alerts on the very first
anomalous cycle (threshold 1).

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
    APY_FEED_PROTOCOL_APY_DROP_PCT,
    APY_FEED_PROTOCOL_TVL_DROP_PCT,
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
    p = Path(data_dir) / "apy_feed_anomaly_health_state.json"
    return json.loads(p.read_text(encoding="utf-8"))


def _snap(**protos) -> dict:
    """Build a snapshot dict from key=(apy, tvl) tuples."""
    out = {}
    for key, (apy, tvl) in protos.items():
        out[key] = {"apy": apy, "tvl_usd": tvl}
    return out


def _write_feed(data_dir: Path, protocols: dict, *, key="protocols") -> Path:
    """Write a realistic historical_apy.json. `protocols` maps key→(apy, tvl)."""
    feed = Path(data_dir) / "historical_apy.json"
    proto_block = {
        name: [{"date": "2026-05-29", "apy": apy, "tvl_usd": tvl}]
        for name, (apy, tvl) in protocols.items()
    }
    feed.write_text(
        json.dumps({
            "generated_at": "2026-05-30T12:00:00Z",
            "data_source": "defillama",
            "days": 90,
            key: proto_block,
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
    def test_stable_snapshot_no_alert(self, tmp_path):
        sender = FakeSender()
        mon = RiskMonitor(data_dir=tmp_path)
        snap = _snap(a=(6.0, 1.0e8), b=(5.0, 2.0e8))
        r1 = mon.alert_apy_feed_protocol_anomaly(snapshot=snap, now=NOW, sender=sender)
        r2 = mon.alert_apy_feed_protocol_anomaly(snapshot=snap, now=NOW, sender=sender)
        assert r1 is False and r2 is False
        assert sender.messages == []
        st = _state(tmp_path)
        assert st["consecutive_anomalies"] == 0
        assert st["prev_snapshot"] == snap

    def test_first_cycle_no_prev_no_alert(self, tmp_path):
        sender = FakeSender()
        mon = RiskMonitor(data_dir=tmp_path)
        snap = _snap(a=(6.0, 1.0e8))
        res = mon.alert_apy_feed_protocol_anomaly(snapshot=snap, now=NOW, sender=sender)
        assert res is False
        assert sender.messages == []
        assert _state(tmp_path)["prev_snapshot"] == snap

    def test_growth_new_protocol_no_alert(self, tmp_path):
        sender = FakeSender()
        mon = RiskMonitor(data_dir=tmp_path)
        mon.alert_apy_feed_protocol_anomaly(
            snapshot=_snap(a=(6.0, 1.0e8)), now=NOW, sender=sender
        )
        # A new protocol appeared → not an anomaly.
        res = mon.alert_apy_feed_protocol_anomaly(
            snapshot=_snap(a=(6.0, 1.0e8), b=(5.0, 2.0e8)), now=NOW, sender=sender
        )
        assert res is False
        assert sender.messages == []
        assert set(_state(tmp_path)["prev_snapshot"]) == {"a", "b"}

    def test_mild_apy_drop_no_alert(self, tmp_path):
        # 6.0 → 4.0 is a 33% drop, below the 60% threshold.
        sender = FakeSender()
        mon = RiskMonitor(data_dir=tmp_path)
        mon.alert_apy_feed_protocol_anomaly(
            snapshot=_snap(a=(6.0, 1.0e8)), now=NOW, sender=sender
        )
        res = mon.alert_apy_feed_protocol_anomaly(
            snapshot=_snap(a=(4.0, 1.0e8)), now=NOW, sender=sender
        )
        assert res is False
        assert sender.messages == []

    def test_mild_tvl_drop_no_alert(self, tmp_path):
        # 1e8 → 0.5e8 is a 50% drop, below the 60% threshold.
        sender = FakeSender()
        mon = RiskMonitor(data_dir=tmp_path)
        mon.alert_apy_feed_protocol_anomaly(
            snapshot=_snap(a=(6.0, 1.0e8)), now=NOW, sender=sender
        )
        res = mon.alert_apy_feed_protocol_anomaly(
            snapshot=_snap(a=(6.0, 0.5e8)), now=NOW, sender=sender
        )
        assert res is False
        assert sender.messages == []


# ──────────────────────────────────────────────────────────────────────────
# Disappearance
# ──────────────────────────────────────────────────────────────────────────

class TestDisappeared:
    def test_protocol_disappeared_fires_immediately(self, tmp_path):
        sender = FakeSender()
        mon = RiskMonitor(data_dir=tmp_path)
        mon.alert_apy_feed_protocol_anomaly(
            snapshot=_snap(a=(6.0, 1.0e8), b=(5.0, 2.0e8)), now=NOW, sender=sender
        )
        assert sender.messages == []
        # b vanished from the feed → fires on the first anomalous cycle.
        fired = mon.alert_apy_feed_protocol_anomaly(
            snapshot=_snap(a=(6.0, 1.0e8)), now=NOW, sender=sender
        )
        assert fired is True
        assert len(sender.messages) == 1
        assert "Protocol Anomaly" in sender.messages[0]
        assert "disappeared" in sender.messages[0]
        assert "b" in sender.messages[0]
        st = _state(tmp_path)
        assert st["consecutive_anomalies"] == 1
        assert st["last_alerted_cycle"] == 1
        assert set(st["prev_snapshot"]) == {"a"}


# ──────────────────────────────────────────────────────────────────────────
# APY crash
# ──────────────────────────────────────────────────────────────────────────

class TestApyCrash:
    def test_apy_crash_exactly_at_threshold_fires(self, tmp_path):
        sender = FakeSender()
        mon = RiskMonitor(data_dir=tmp_path)
        mon.alert_apy_feed_protocol_anomaly(
            snapshot=_snap(a=(10.0, 1.0e8)), now=NOW, sender=sender
        )
        # 10.0 → 4.0 == 10 * (1 - 0.6) → exactly at the 60% threshold → fires.
        fired = mon.alert_apy_feed_protocol_anomaly(
            snapshot=_snap(a=(4.0, 1.0e8)), now=NOW, sender=sender
        )
        assert fired is True
        assert "APY crash" in sender.messages[0]
        assert APY_FEED_PROTOCOL_APY_DROP_PCT == 0.6

    def test_apy_just_below_threshold_no_fire(self, tmp_path):
        sender = FakeSender()
        mon = RiskMonitor(data_dir=tmp_path)
        mon.alert_apy_feed_protocol_anomaly(
            snapshot=_snap(a=(10.0, 1.0e8)), now=NOW, sender=sender
        )
        # 10.0 → 4.01 is a 59.9% drop, just shy of 60% → no fire.
        res = mon.alert_apy_feed_protocol_anomaly(
            snapshot=_snap(a=(4.01, 1.0e8)), now=NOW, sender=sender
        )
        assert res is False
        assert sender.messages == []

    def test_severe_apy_crash_fires(self, tmp_path):
        sender = FakeSender()
        mon = RiskMonitor(data_dir=tmp_path)
        mon.alert_apy_feed_protocol_anomaly(
            snapshot=_snap(a=(12.0, 1.0e8)), now=NOW, sender=sender
        )
        fired = mon.alert_apy_feed_protocol_anomaly(
            snapshot=_snap(a=(0.5, 1.0e8)), now=NOW, sender=sender
        )
        assert fired is True
        assert "APY crash" in sender.messages[0]

    def test_apy_to_zero_fires(self, tmp_path):
        sender = FakeSender()
        mon = RiskMonitor(data_dir=tmp_path)
        mon.alert_apy_feed_protocol_anomaly(
            snapshot=_snap(a=(8.0, 1.0e8)), now=NOW, sender=sender
        )
        fired = mon.alert_apy_feed_protocol_anomaly(
            snapshot=_snap(a=(0.0, 1.0e8)), now=NOW, sender=sender
        )
        assert fired is True

    def test_apy_prev_none_no_fire(self, tmp_path):
        # Prev apy is None → cannot compute crash → no fire.
        sender = FakeSender()
        mon = RiskMonitor(data_dir=tmp_path)
        mon.alert_apy_feed_protocol_anomaly(
            snapshot=_snap(a=(None, 1.0e8)), now=NOW, sender=sender
        )
        res = mon.alert_apy_feed_protocol_anomaly(
            snapshot=_snap(a=(1.0, 1.0e8)), now=NOW, sender=sender
        )
        assert res is False
        assert sender.messages == []


# ──────────────────────────────────────────────────────────────────────────
# TVL crash
# ──────────────────────────────────────────────────────────────────────────

class TestTvlCrash:
    def test_tvl_crash_exactly_at_threshold_fires(self, tmp_path):
        sender = FakeSender()
        mon = RiskMonitor(data_dir=tmp_path)
        mon.alert_apy_feed_protocol_anomaly(
            snapshot=_snap(a=(6.0, 1.0e8)), now=NOW, sender=sender
        )
        # 1e8 → 4e7 == 1e8 * (1 - 0.6) → exactly the 60% threshold → fires.
        fired = mon.alert_apy_feed_protocol_anomaly(
            snapshot=_snap(a=(6.0, 4.0e7)), now=NOW, sender=sender
        )
        assert fired is True
        assert "TVL crash" in sender.messages[0]
        assert APY_FEED_PROTOCOL_TVL_DROP_PCT == 0.6

    def test_tvl_just_below_threshold_no_fire(self, tmp_path):
        sender = FakeSender()
        mon = RiskMonitor(data_dir=tmp_path)
        mon.alert_apy_feed_protocol_anomaly(
            snapshot=_snap(a=(6.0, 1.0e8)), now=NOW, sender=sender
        )
        # 1e8 → 4.1e7 is a 59% drop → no fire.
        res = mon.alert_apy_feed_protocol_anomaly(
            snapshot=_snap(a=(6.0, 4.1e7)), now=NOW, sender=sender
        )
        assert res is False
        assert sender.messages == []

    def test_severe_tvl_crash_fires(self, tmp_path):
        sender = FakeSender()
        mon = RiskMonitor(data_dir=tmp_path)
        mon.alert_apy_feed_protocol_anomaly(
            snapshot=_snap(a=(6.0, 5.0e8)), now=NOW, sender=sender
        )
        fired = mon.alert_apy_feed_protocol_anomaly(
            snapshot=_snap(a=(6.0, 1.0e7)), now=NOW, sender=sender
        )
        assert fired is True
        assert "TVL crash" in sender.messages[0]


# ──────────────────────────────────────────────────────────────────────────
# Combined
# ──────────────────────────────────────────────────────────────────────────

class TestCombined:
    def test_disappeared_plus_crash_fires(self, tmp_path):
        sender = FakeSender()
        mon = RiskMonitor(data_dir=tmp_path)
        mon.alert_apy_feed_protocol_anomaly(
            snapshot=_snap(a=(10.0, 1.0e8), b=(5.0, 2.0e8)), now=NOW, sender=sender
        )
        # a's APY crashes AND b disappears in the same cycle.
        fired = mon.alert_apy_feed_protocol_anomaly(
            snapshot=_snap(a=(2.0, 1.0e8)), now=NOW, sender=sender
        )
        assert fired is True
        msg = sender.messages[0]
        assert "disappeared" in msg and "APY crash" in msg


# ──────────────────────────────────────────────────────────────────────────
# Refire / recovery
# ──────────────────────────────────────────────────────────────────────────

class TestRefireRecovery:
    def test_refire_on_continued_anomaly(self, tmp_path):
        sender = FakeSender()
        mon = RiskMonitor(data_dir=tmp_path)
        mon.alert_apy_feed_protocol_anomaly(
            snapshot=_snap(a=(10.0, 1.0e8), b=(5.0, 2.0e8)), now=NOW, sender=sender
        )
        # Cycle 1 anomaly: b disappears.
        mon.alert_apy_feed_protocol_anomaly(
            snapshot=_snap(a=(10.0, 1.0e8)), now=NOW, sender=sender
        )
        assert len(sender.messages) == 1
        # Cycle 2 anomaly: a's TVL crashes → streak grows → refire.
        fired = mon.alert_apy_feed_protocol_anomaly(
            snapshot=_snap(a=(10.0, 1.0e7)), now=NOW, sender=sender
        )
        assert fired is True
        assert len(sender.messages) == 2
        st = _state(tmp_path)
        assert st["consecutive_anomalies"] == 2
        assert st["last_alerted_cycle"] == 2

    def test_recovery_resets_streak(self, tmp_path):
        sender = FakeSender()
        mon = RiskMonitor(data_dir=tmp_path)
        mon.alert_apy_feed_protocol_anomaly(
            snapshot=_snap(a=(10.0, 1.0e8), b=(5.0, 2.0e8)), now=NOW, sender=sender
        )
        mon.alert_apy_feed_protocol_anomaly(
            snapshot=_snap(a=(10.0, 1.0e8)), now=NOW, sender=sender
        )  # fire (b gone)
        assert len(sender.messages) == 1
        # Recovery: stable snapshot vs new prev (just a) → healthy reset.
        res = mon.alert_apy_feed_protocol_anomaly(
            snapshot=_snap(a=(10.0, 1.0e8)), now=NOW, sender=sender
        )
        assert res is False
        assert len(sender.messages) == 1
        st = _state(tmp_path)
        assert st["consecutive_anomalies"] == 0
        assert st["last_alerted_cycle"] == 0


# ──────────────────────────────────────────────────────────────────────────
# Unreadable / feed file handling
# ──────────────────────────────────────────────────────────────────────────

class TestUnreadable:
    def test_none_snapshot_fires(self, tmp_path):
        sender = FakeSender()
        mon = RiskMonitor(data_dir=tmp_path)
        # snapshot None and no feed_path → unreadable → anomalous → fires.
        fired = mon.alert_apy_feed_protocol_anomaly(
            snapshot=None, now=NOW, sender=sender
        )
        assert fired is True
        assert "unreadable" in sender.messages[0]
        assert _state(tmp_path)["consecutive_anomalies"] == 1

    def test_missing_feed_file_fires(self, tmp_path):
        sender = FakeSender()
        mon = RiskMonitor(data_dir=tmp_path)
        missing = tmp_path / "does_not_exist.json"
        fired = mon.alert_apy_feed_protocol_anomaly(
            feed_path=str(missing), now=NOW, sender=sender
        )
        assert fired is True
        assert _state(tmp_path)["consecutive_anomalies"] == 1

    def test_corrupt_feed_file_fires(self, tmp_path):
        sender = FakeSender()
        mon = RiskMonitor(data_dir=tmp_path)
        bad = tmp_path / "historical_apy.json"
        bad.write_text("{not valid json", encoding="utf-8")
        fired = mon.alert_apy_feed_protocol_anomaly(
            feed_path=str(bad), now=NOW, sender=sender
        )
        assert fired is True
        assert _state(tmp_path)["consecutive_anomalies"] == 1


# ──────────────────────────────────────────────────────────────────────────
# feed_path real-format reading
# ──────────────────────────────────────────────────────────────────────────

class TestFeedPath:
    def test_reads_snapshot_from_real_feed(self, tmp_path):
        sender = FakeSender()
        mon = RiskMonitor(data_dir=tmp_path)
        feed = _write_feed(tmp_path, {"a-usdc-eth": (6.0, 1.0e8), "b-usdc-eth": (5.0, 2.0e8)})
        res = mon.alert_apy_feed_protocol_anomaly(
            feed_path=str(feed), now=NOW, sender=sender
        )
        assert res is False
        st = _state(tmp_path)
        assert set(st["prev_snapshot"]) == {"a-usdc-eth", "b-usdc-eth"}
        assert st["prev_snapshot"]["a-usdc-eth"]["apy"] == 6.0

    def test_real_feed_dropout_fires(self, tmp_path):
        sender = FakeSender()
        mon = RiskMonitor(data_dir=tmp_path)
        feed = _write_feed(tmp_path, {"a-usdc-eth": (6.0, 1.0e8), "b-usdc-eth": (5.0, 2.0e8)})
        mon.alert_apy_feed_protocol_anomaly(feed_path=str(feed), now=NOW, sender=sender)
        # DeFiLlama dropped b.
        _write_feed(tmp_path, {"a-usdc-eth": (6.0, 1.0e8)})
        fired = mon.alert_apy_feed_protocol_anomaly(
            feed_path=str(feed), now=NOW, sender=sender
        )
        assert fired is True
        assert "b-usdc-eth" in sender.messages[0]

    def test_protocol_history_key_variant(self, tmp_path):
        sender = FakeSender()
        mon = RiskMonitor(data_dir=tmp_path)
        feed = _write_feed(
            tmp_path,
            {"a-usdc-eth": (6.0, 1.0e8), "b-usdc-eth": (5.0, 2.0e8)},
            key="protocol_history",
        )
        res = mon.alert_apy_feed_protocol_anomaly(
            feed_path=str(feed), now=NOW, sender=sender
        )
        assert res is False
        assert set(_state(tmp_path)["prev_snapshot"]) == {"a-usdc-eth", "b-usdc-eth"}

    def test_empty_and_missing_fields_protocols_skipped(self, tmp_path):
        sender = FakeSender()
        mon = RiskMonitor(data_dir=tmp_path)
        feed = tmp_path / "historical_apy.json"
        feed.write_text(
            json.dumps({
                "protocols": {
                    "good": [{"date": "2026-05-29", "apy": 6.0, "tvl_usd": 1.0e8}],
                    "empty-hist": [],
                    "no-apy-tvl": [{"date": "2026-05-29"}],
                }
            }),
            encoding="utf-8",
        )
        res = mon.alert_apy_feed_protocol_anomaly(
            feed_path=str(feed), now=NOW, sender=sender
        )
        assert res is False
        st = _state(tmp_path)
        # empty-hist skipped entirely; good + no-apy-tvl included (None fields).
        assert "good" in st["prev_snapshot"]
        assert "empty-hist" not in st["prev_snapshot"]
        assert st["prev_snapshot"]["no-apy-tvl"] == {"apy": None, "tvl_usd": None}

    def test_non_numeric_fields_coerced_to_none(self, tmp_path):
        sender = FakeSender()
        mon = RiskMonitor(data_dir=tmp_path)
        feed = tmp_path / "historical_apy.json"
        feed.write_text(
            json.dumps({
                "protocols": {
                    "x": [{"date": "2026-05-29", "apy": "bad", "tvl_usd": None}],
                }
            }),
            encoding="utf-8",
        )
        res = mon.alert_apy_feed_protocol_anomaly(
            feed_path=str(feed), now=NOW, sender=sender
        )
        assert res is False
        assert _state(tmp_path)["prev_snapshot"]["x"] == {"apy": None, "tvl_usd": None}

    def test_last_record_used_for_snapshot(self, tmp_path):
        sender = FakeSender()
        mon = RiskMonitor(data_dir=tmp_path)
        feed = tmp_path / "historical_apy.json"
        feed.write_text(
            json.dumps({
                "protocols": {
                    "x": [
                        {"date": "2026-05-28", "apy": 9.0, "tvl_usd": 9.0e8},
                        {"date": "2026-05-29", "apy": 6.0, "tvl_usd": 1.0e8},
                    ],
                }
            }),
            encoding="utf-8",
        )
        mon.alert_apy_feed_protocol_anomaly(feed_path=str(feed), now=NOW, sender=sender)
        st = _state(tmp_path)
        assert st["prev_snapshot"]["x"]["apy"] == 6.0  # last record


# ──────────────────────────────────────────────────────────────────────────
# Persistence / robustness
# ──────────────────────────────────────────────────────────────────────────

class TestPersistence:
    def test_state_persists_across_reinstantiation(self, tmp_path):
        sender = FakeSender()
        RiskMonitor(data_dir=tmp_path).alert_apy_feed_protocol_anomaly(
            snapshot=_snap(a=(6.0, 1.0e8), b=(5.0, 2.0e8)), now=NOW, sender=sender
        )
        assert set(_state(tmp_path)["prev_snapshot"]) == {"a", "b"}
        # New instance reads persisted prev, sees b dropout → fires.
        fired = RiskMonitor(data_dir=tmp_path).alert_apy_feed_protocol_anomaly(
            snapshot=_snap(a=(6.0, 1.0e8)), now=NOW, sender=sender
        )
        assert fired is True
        assert len(sender.messages) == 1


class TestRobustness:
    def test_corrupt_state_recovers(self, tmp_path):
        p = tmp_path / "apy_feed_anomaly_health_state.json"
        p.write_text("{bad json", encoding="utf-8")
        sender = FakeSender()
        mon = RiskMonitor(data_dir=tmp_path)
        res = mon.alert_apy_feed_protocol_anomaly(
            snapshot=_snap(a=(6.0, 1.0e8)), now=NOW, sender=sender
        )
        # Fresh state recovered → no prev → healthy.
        assert res is False
        assert set(_state(tmp_path)["prev_snapshot"]) == {"a"}

    def test_never_raises_on_bad_sender(self, tmp_path):
        class BoomSender:
            def send(self, text, parse_mode="HTML"):
                raise RuntimeError("telegram down")

        mon = RiskMonitor(data_dir=tmp_path)
        mon.alert_apy_feed_protocol_anomaly(
            snapshot=_snap(a=(6.0, 1.0e8), b=(5.0, 2.0e8)),
            now=NOW, sender=BoomSender(),
        )
        # b disappears → tries to send which raises internally → swallowed → False.
        res = mon.alert_apy_feed_protocol_anomaly(
            snapshot=_snap(a=(6.0, 1.0e8)), now=NOW, sender=BoomSender()
        )
        assert res is False
        # Streak still grew and was persisted despite the send failure.
        assert _state(tmp_path)["consecutive_anomalies"] == 1

    def test_naive_now_treated_as_utc(self, tmp_path):
        sender = FakeSender()
        mon = RiskMonitor(data_dir=tmp_path)
        naive_now = datetime(2026, 5, 30, 12, 0, 0)  # no tzinfo
        res = mon.alert_apy_feed_protocol_anomaly(
            snapshot=_snap(a=(6.0, 1.0e8)), now=naive_now, sender=sender
        )
        assert res is False
        assert "a" in _state(tmp_path)["prev_snapshot"]
