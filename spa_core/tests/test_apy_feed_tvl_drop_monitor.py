"""
Tests for SPA-V343: APY-feed total-TVL collapse monitoring + Telegram alert.

Covers RiskMonitor.alert_apy_feed_tvl_drop — the consecutive-drop streak
tracker that fires as soon as the TOTAL TVL carried in historical_apy.json
collapses sharply between cycles (e.g. DeFiLlama returns drastically lower TVL
while still reporting the same number of protocols) or falls below an absolute
floor, before the covariance / Kelly universe silently thins by capital weight.

Like the protocol-count monitor (threshold 1), a sharp TVL collapse alerts on
the very first degraded cycle.

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
    APY_FEED_TVL_DROP_PCT,
    APY_FEED_MIN_TVL_USD,
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
    p = Path(data_dir) / "apy_feed_tvl_health_state.json"
    return json.loads(p.read_text(encoding="utf-8"))


def _write_feed(data_dir: Path, tvls: list[float]) -> Path:
    """Write a realistic historical_apy.json; one protocol per TVL in `tvls`.

    Each protocol gets a short history; the LAST entry carries the given
    tvl_usd so the monitor sums the most-recent TVL per protocol.
    """
    feed = Path(data_dir) / "historical_apy.json"
    protocols = {
        f"protocol-{i}-usdc-ethereum": [
            {"date": "2026-05-28", "apy": 5.0 + i, "tvl_usd": tvl * 0.9},
            {"date": "2026-05-29", "apy": 5.0 + i, "tvl_usd": tvl},
        ]
        for i, tvl in enumerate(tvls)
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
    def test_stable_tvl_no_alert(self, tmp_path):
        sender = FakeSender()
        mon = RiskMonitor(data_dir=tmp_path)
        r1 = mon.alert_apy_feed_tvl_drop(total_tvl_usd=1.0e9, now=NOW, sender=sender)
        r2 = mon.alert_apy_feed_tvl_drop(total_tvl_usd=1.0e9, now=NOW, sender=sender)
        assert r1 is False and r2 is False
        assert sender.messages == []
        st = _state(tmp_path)
        assert st["consecutive_drops"] == 0
        assert st["prev_tvl_usd"] == 1.0e9

    def test_first_cycle_no_prev_no_alert(self, tmp_path):
        sender = FakeSender()
        mon = RiskMonitor(data_dir=tmp_path)
        res = mon.alert_apy_feed_tvl_drop(total_tvl_usd=1.0e9, now=NOW, sender=sender)
        assert res is False
        assert sender.messages == []
        assert _state(tmp_path)["prev_tvl_usd"] == 1.0e9

    def test_growth_no_alert(self, tmp_path):
        sender = FakeSender()
        mon = RiskMonitor(data_dir=tmp_path)
        mon.alert_apy_feed_tvl_drop(total_tvl_usd=8.0e8, now=NOW, sender=sender)
        res = mon.alert_apy_feed_tvl_drop(total_tvl_usd=1.2e9, now=NOW, sender=sender)
        assert res is False
        assert sender.messages == []
        assert _state(tmp_path)["prev_tvl_usd"] == 1.2e9

    def test_mild_drop_no_alert(self, tmp_path):
        # 1e9 → 7e8 is a 30% drop, below the 50% threshold and above the floor.
        sender = FakeSender()
        mon = RiskMonitor(data_dir=tmp_path)
        mon.alert_apy_feed_tvl_drop(total_tvl_usd=1.0e9, now=NOW, sender=sender)
        res = mon.alert_apy_feed_tvl_drop(total_tvl_usd=7.0e8, now=NOW, sender=sender)
        assert res is False
        assert sender.messages == []
        assert _state(tmp_path)["prev_tvl_usd"] == 7.0e8


# ──────────────────────────────────────────────────────────────────────────
# Sharp drop
# ──────────────────────────────────────────────────────────────────────────

class TestSharpDrop:
    def test_sharp_drop_fires_immediately(self, tmp_path):
        sender = FakeSender()
        mon = RiskMonitor(data_dir=tmp_path)
        # Establish prev=1e9.
        mon.alert_apy_feed_tvl_drop(total_tvl_usd=1.0e9, now=NOW, sender=sender)
        assert sender.messages == []
        # 1e9 → 3e8 is a 70% drop ≥ 50% → fires on the first degraded cycle.
        fired = mon.alert_apy_feed_tvl_drop(total_tvl_usd=3.0e8, now=NOW, sender=sender)
        assert fired is True
        assert len(sender.messages) == 1
        assert "TVL Collapse" in sender.messages[0]
        assert "sharp drop" in sender.messages[0]
        st = _state(tmp_path)
        assert st["consecutive_drops"] == 1
        assert st["last_alerted_cycle"] == 1
        assert st["prev_tvl_usd"] == 3.0e8

    def test_exactly_50pct_drop_fires(self, tmp_path):
        sender = FakeSender()
        mon = RiskMonitor(data_dir=tmp_path)
        mon.alert_apy_feed_tvl_drop(total_tvl_usd=1.0e9, now=NOW, sender=sender)
        # 1e9 → 5e8 is exactly 50% (5e8 <= 1e9 * 0.5) → degraded.
        fired = mon.alert_apy_feed_tvl_drop(total_tvl_usd=5.0e8, now=NOW, sender=sender)
        assert fired is True
        assert APY_FEED_TVL_DROP_PCT == 0.5

    def test_refire_on_continued_drop(self, tmp_path):
        sender = FakeSender()
        mon = RiskMonitor(data_dir=tmp_path)
        mon.alert_apy_feed_tvl_drop(total_tvl_usd=1.0e9, now=NOW, sender=sender)
        mon.alert_apy_feed_tvl_drop(total_tvl_usd=3.0e8, now=NOW, sender=sender)  # fire 1
        assert len(sender.messages) == 1
        # Next cycle drops further 3e8 → 5e6 (also below floor) → refire.
        fired = mon.alert_apy_feed_tvl_drop(total_tvl_usd=5.0e6, now=NOW, sender=sender)
        assert fired is True
        assert len(sender.messages) == 2
        st = _state(tmp_path)
        assert st["consecutive_drops"] == 2
        assert st["last_alerted_cycle"] == 2


# ──────────────────────────────────────────────────────────────────────────
# Below absolute floor
# ──────────────────────────────────────────────────────────────────────────

class TestBelowMin:
    def test_below_min_tvl_fires(self, tmp_path):
        sender = FakeSender()
        mon = RiskMonitor(data_dir=tmp_path)
        # No prev, but only $5M < $10M floor → degraded on first cycle.
        fired = mon.alert_apy_feed_tvl_drop(total_tvl_usd=5.0e6, now=NOW, sender=sender)
        assert fired is True
        assert len(sender.messages) == 1
        assert "floor" in sender.messages[0]
        assert APY_FEED_MIN_TVL_USD == 1.0e7

    def test_at_floor_healthy(self, tmp_path):
        sender = FakeSender()
        mon = RiskMonitor(data_dir=tmp_path)
        # Exactly the floor ($10M) with no prev → healthy (not < floor).
        res = mon.alert_apy_feed_tvl_drop(total_tvl_usd=1.0e7, now=NOW, sender=sender)
        assert res is False
        assert sender.messages == []


# ──────────────────────────────────────────────────────────────────────────
# Recovery
# ──────────────────────────────────────────────────────────────────────────

class TestRecovery:
    def test_recovery_resets_streak(self, tmp_path):
        sender = FakeSender()
        mon = RiskMonitor(data_dir=tmp_path)
        mon.alert_apy_feed_tvl_drop(total_tvl_usd=1.0e9, now=NOW, sender=sender)
        mon.alert_apy_feed_tvl_drop(total_tvl_usd=3.0e8, now=NOW, sender=sender)  # fire
        assert len(sender.messages) == 1
        # Recovery: TVL back to 9e8 (9e8 > 3e8 * 0.5, above floor) → healthy reset.
        res = mon.alert_apy_feed_tvl_drop(total_tvl_usd=9.0e8, now=NOW, sender=sender)
        assert res is False
        assert len(sender.messages) == 1
        st = _state(tmp_path)
        assert st["consecutive_drops"] == 0
        assert st["last_alerted_cycle"] == 0
        assert st["prev_tvl_usd"] == 9.0e8


# ──────────────────────────────────────────────────────────────────────────
# Unreadable / feed file handling
# ──────────────────────────────────────────────────────────────────────────

class TestUnreadable:
    def test_unreadable_none_degraded_fires(self, tmp_path):
        sender = FakeSender()
        mon = RiskMonitor(data_dir=tmp_path)
        # total_tvl_usd None and no feed_path → unreadable → degraded → fires.
        fired = mon.alert_apy_feed_tvl_drop(total_tvl_usd=None, now=NOW, sender=sender)
        assert fired is True
        assert "unreadable" in sender.messages[0]
        assert _state(tmp_path)["consecutive_drops"] == 1

    def test_missing_feed_file_degraded(self, tmp_path):
        sender = FakeSender()
        mon = RiskMonitor(data_dir=tmp_path)
        missing = tmp_path / "does_not_exist.json"
        fired = mon.alert_apy_feed_tvl_drop(
            feed_path=str(missing), now=NOW, sender=sender
        )
        # Cannot read → total stays None → unreadable → degraded → fires.
        assert fired is True
        assert _state(tmp_path)["consecutive_drops"] == 1

    def test_corrupt_feed_file_degraded(self, tmp_path):
        sender = FakeSender()
        mon = RiskMonitor(data_dir=tmp_path)
        bad = tmp_path / "historical_apy.json"
        bad.write_text("{not valid json", encoding="utf-8")
        fired = mon.alert_apy_feed_tvl_drop(
            feed_path=str(bad), now=NOW, sender=sender
        )
        assert fired is True
        assert _state(tmp_path)["consecutive_drops"] == 1

    def test_empty_protocols_unreadable(self, tmp_path):
        sender = FakeSender()
        mon = RiskMonitor(data_dir=tmp_path)
        feed = tmp_path / "historical_apy.json"
        feed.write_text(json.dumps({"protocols": {}}), encoding="utf-8")
        fired = mon.alert_apy_feed_tvl_drop(
            feed_path=str(feed), now=NOW, sender=sender
        )
        # No usable protocols → total stays None → unreadable → fires.
        assert fired is True
        assert _state(tmp_path)["consecutive_drops"] == 1


# ──────────────────────────────────────────────────────────────────────────
# feed_path real-format reading
# ──────────────────────────────────────────────────────────────────────────

class TestFeedPath:
    def test_reads_total_tvl_from_real_feed(self, tmp_path):
        sender = FakeSender()
        mon = RiskMonitor(data_dir=tmp_path)
        # Three protocols, last tvl_usd each 2e8/3e8/5e8 → total 1e9.
        feed = _write_feed(tmp_path, [2.0e8, 3.0e8, 5.0e8])
        res = mon.alert_apy_feed_tvl_drop(
            feed_path=str(feed), now=NOW, sender=sender
        )
        assert res is False
        assert _state(tmp_path)["prev_tvl_usd"] == 1.0e9

    def test_real_feed_sharp_drop_fires(self, tmp_path):
        sender = FakeSender()
        mon = RiskMonitor(data_dir=tmp_path)
        feed = _write_feed(tmp_path, [2.0e8, 3.0e8, 5.0e8])  # total 1e9
        mon.alert_apy_feed_tvl_drop(feed_path=str(feed), now=NOW, sender=sender)
        # DeFiLlama returns much lower TVL (same 3 protocols): total 2e8.
        _write_feed(tmp_path, [0.5e8, 0.5e8, 1.0e8])  # total 2e8 = 80% drop
        fired = mon.alert_apy_feed_tvl_drop(
            feed_path=str(feed), now=NOW, sender=sender
        )
        assert fired is True
        assert _state(tmp_path)["prev_tvl_usd"] == 2.0e8

    def test_protocol_history_key_variant(self, tmp_path):
        sender = FakeSender()
        mon = RiskMonitor(data_dir=tmp_path)
        feed = tmp_path / "historical_apy.json"
        feed.write_text(
            json.dumps({
                "protocol_history": {
                    "a-usdc-eth": [{"date": "2026-05-29", "tvl_usd": 4.0e8}],
                    "b-usdc-eth": [{"date": "2026-05-29", "tvl_usd": 6.0e8}],
                }
            }),
            encoding="utf-8",
        )
        res = mon.alert_apy_feed_tvl_drop(
            feed_path=str(feed), now=NOW, sender=sender
        )
        assert res is False
        assert _state(tmp_path)["prev_tvl_usd"] == 1.0e9

    def test_skips_bad_entries_in_feed(self, tmp_path):
        sender = FakeSender()
        mon = RiskMonitor(data_dir=tmp_path)
        feed = tmp_path / "historical_apy.json"
        feed.write_text(
            json.dumps({
                "protocols": {
                    "good": [{"date": "2026-05-29", "tvl_usd": 5.0e8}],
                    "empty-list": [],
                    "not-a-list": {"date": "x", "tvl_usd": 9.9e9},
                    "no-tvl": [{"date": "2026-05-29", "apy": 3.0}],
                    "string-tvl-coercible": [{"date": "2026-05-29", "tvl_usd": "6e8"}],
                }
            }),
            encoding="utf-8",
        )
        res = mon.alert_apy_feed_tvl_drop(
            feed_path=str(feed), now=NOW, sender=sender
        )
        # Usable: good (5e8) + coercible "6e8" → total 1.1e9 (healthy, no prev).
        assert res is False
        assert _state(tmp_path)["prev_tvl_usd"] == 1.1e9


# ──────────────────────────────────────────────────────────────────────────
# Persistence
# ──────────────────────────────────────────────────────────────────────────

class TestPersistence:
    def test_state_persists_across_reinstantiation(self, tmp_path):
        sender = FakeSender()
        RiskMonitor(data_dir=tmp_path).alert_apy_feed_tvl_drop(
            total_tvl_usd=1.0e9, now=NOW, sender=sender
        )
        assert _state(tmp_path)["prev_tvl_usd"] == 1.0e9
        # New instance reads persisted prev=1e9, sees a sharp drop → fires.
        fired = RiskMonitor(data_dir=tmp_path).alert_apy_feed_tvl_drop(
            total_tvl_usd=3.0e8, now=NOW, sender=sender
        )
        assert fired is True
        assert len(sender.messages) == 1
        assert _state(tmp_path)["prev_tvl_usd"] == 3.0e8

    def test_state_file_keys(self, tmp_path):
        sender = FakeSender()
        mon = RiskMonitor(data_dir=tmp_path)
        mon.alert_apy_feed_tvl_drop(total_tvl_usd=1.0e9, now=NOW, sender=sender)
        st = _state(tmp_path)
        assert set(st.keys()) == {
            "consecutive_drops", "prev_tvl_usd",
            "last_alerted_cycle", "updated_at",
        }
        assert st["updated_at"] == "2026-05-30T12:00:00Z"


# ──────────────────────────────────────────────────────────────────────────
# Message content
# ──────────────────────────────────────────────────────────────────────────

class TestMessage:
    def test_message_formats_tvl_with_commas(self, tmp_path):
        sender = FakeSender()
        mon = RiskMonitor(data_dir=tmp_path)
        mon.alert_apy_feed_tvl_drop(total_tvl_usd=1.0e9, now=NOW, sender=sender)
        mon.alert_apy_feed_tvl_drop(total_tvl_usd=3.0e8, now=NOW, sender=sender)
        msg = sender.messages[0]
        assert "TVL Collapse" in msg
        assert "$1,000,000,000" in msg  # prev formatted with commas
        assert "$300,000,000" in msg    # current formatted with commas
        assert "capital weight" in msg


# ──────────────────────────────────────────────────────────────────────────
# Robustness
# ──────────────────────────────────────────────────────────────────────────

class TestRobustness:
    def test_corrupt_state_recovers(self, tmp_path):
        p = tmp_path / "apy_feed_tvl_health_state.json"
        p.write_text("{bad json", encoding="utf-8")
        sender = FakeSender()
        mon = RiskMonitor(data_dir=tmp_path)
        res = mon.alert_apy_feed_tvl_drop(total_tvl_usd=1.0e9, now=NOW, sender=sender)
        # Fresh state recovered → no prev → healthy.
        assert res is False
        assert _state(tmp_path)["prev_tvl_usd"] == 1.0e9

    def test_never_raises_on_bad_sender(self, tmp_path):
        class BoomSender:
            def send(self, text, parse_mode="HTML"):
                raise RuntimeError("telegram down")

        mon = RiskMonitor(data_dir=tmp_path)
        mon.alert_apy_feed_tvl_drop(total_tvl_usd=1.0e9, now=NOW, sender=BoomSender())
        # Sharp drop attempts a send which raises internally → swallowed → False.
        res = mon.alert_apy_feed_tvl_drop(
            total_tvl_usd=3.0e6, now=NOW, sender=BoomSender()
        )
        assert res is False
        # Streak still grew and was persisted despite the send failure.
        assert _state(tmp_path)["consecutive_drops"] == 1

    def test_naive_now_treated_as_utc(self, tmp_path):
        sender = FakeSender()
        mon = RiskMonitor(data_dir=tmp_path)
        naive_now = datetime(2026, 5, 30, 12, 0, 0)  # no tzinfo
        res = mon.alert_apy_feed_tvl_drop(
            total_tvl_usd=1.0e9, now=naive_now, sender=sender
        )
        assert res is False
        assert _state(tmp_path)["prev_tvl_usd"] == 1.0e9
