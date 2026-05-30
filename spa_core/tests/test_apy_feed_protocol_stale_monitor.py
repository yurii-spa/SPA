"""
Tests for SPA-V346: APY-feed PER-PROTOCOL staleness monitoring + alert.

Covers RiskMonitor.alert_apy_feed_protocol_stale — the consecutive-stale streak
tracker that fires as soon as a SPECIFIC protocol's newest history record is
older than APY_FEED_PROTOCOL_MAX_AGE_HOURS, even when the feed as a whole still
looks fresh (its generated_at advances because the OTHER protocols keep
updating).

This closes a TIME blind spot that none of the other APY-feed monitors catch:
  • whole-feed staleness (alert_apy_feed_stale) watches feed-level generated_at;
  • per-protocol anomaly (alert_apy_feed_protocol_anomaly) watches APY/TVL value
    crashes and dropouts — a protocol that simply stops getting fresher dates
    (values frozen, never disappears) trips none of those.

Staleness is measured by record AGE in hours — NOT cycle-to-cycle date equality
— so a healthy DAILY-granularity feed (same date across the 6 cycles/day) never
false-positives. Threshold is 1 cycle (fire immediately, like the drop/anomaly
monitors).

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
    APY_FEED_PROTOCOL_MAX_AGE_HOURS,
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


class BadSender:
    """Raises on send() — exercises the swallow-and-return-False path."""

    def send(self, text: str, parse_mode: str = "HTML") -> bool:
        raise RuntimeError("telegram down")


NOW = datetime(2026, 5, 30, 12, 0, 0, tzinfo=timezone.utc)


def _state(data_dir: Path) -> dict:
    p = Path(data_dir) / "apy_feed_protocol_stale_health_state.json"
    return json.loads(p.read_text(encoding="utf-8"))


def _iso_days_ago(days: float, *, ref: datetime = NOW) -> str:
    """ISO date string `days` before `ref` (date-only, daily granularity)."""
    return (ref - timedelta(days=days)).strftime("%Y-%m-%d")


def _snap(**protos) -> dict:
    """protocol=date_iso → snapshot dict."""
    return dict(protos)


def _write_feed(data_dir: Path, last_dates: dict, *, key: str = "protocols",
                generated_at: str = "2026-05-30T12:00:00Z") -> Path:
    """
    Write a realistic historical_apy.json. `last_dates` maps protocol → the
    `date` of the LAST history record (a short 2-record history is written so
    `hist[-1]` is exercised).
    """
    feed = Path(data_dir) / "historical_apy.json"
    proto_block = {}
    for name, last_date in last_dates.items():
        proto_block[name] = [
            {"date": "2026-05-01", "apy": 5.0, "tvl_usd": 1.0e8},
            {"date": last_date, "apy": 5.0, "tvl_usd": 1.0e8},
        ]
    feed.write_text(
        json.dumps({
            "generated_at": generated_at,
            "data_source": "defillama",
            "days": 90,
            key: proto_block,
        }),
        encoding="utf-8",
    )
    return feed


# ──────────────────────────────────────────────────────────────────────────
# Healthy / no-alert cases
# ──────────────────────────────────────────────────────────────────────────

def test_all_fresh_no_alert(tmp_path):
    """Every protocol updated today → healthy, no alert, streak 0."""
    rm = RiskMonitor(data_dir=tmp_path)
    sender = FakeSender()
    fired = rm.alert_apy_feed_protocol_stale(
        snapshot=_snap(aave=_iso_days_ago(0), morpho=_iso_days_ago(1)),
        now=NOW, sender=sender,
    )
    assert fired is False
    assert sender.messages == []
    assert _state(tmp_path)["consecutive_stale"] == 0


def test_daily_granularity_same_date_not_stale(tmp_path):
    """
    Within a day the date is unchanged across cycles but age < threshold —
    must NOT be considered stale (this is the false-positive guard).
    """
    rm = RiskMonitor(data_dir=tmp_path)
    sender = FakeSender()
    # 1 day old << 48h threshold.
    fired = rm.alert_apy_feed_protocol_stale(
        snapshot=_snap(aave=_iso_days_ago(1), morpho=_iso_days_ago(1)),
        now=NOW, sender=sender,
    )
    assert fired is False
    assert sender.messages == []


def test_just_under_threshold_no_alert(tmp_path):
    """A record exactly at the threshold age is not yet stale (strict `>`)."""
    rm = RiskMonitor(data_dir=tmp_path)
    sender = FakeSender()
    ts = (NOW - timedelta(hours=APY_FEED_PROTOCOL_MAX_AGE_HOURS)).strftime(
        "%Y-%m-%dT%H:%M:%S+00:00")
    fired = rm.alert_apy_feed_protocol_stale(
        snapshot=_snap(aave=ts), now=NOW, sender=sender,
    )
    assert fired is False


# ──────────────────────────────────────────────────────────────────────────
# Stale → alert
# ──────────────────────────────────────────────────────────────────────────

def test_one_protocol_stale_fires_immediately(tmp_path):
    """One protocol 3 days old while others fresh → fire on first cycle."""
    rm = RiskMonitor(data_dir=tmp_path)
    sender = FakeSender()
    fired = rm.alert_apy_feed_protocol_stale(
        snapshot=_snap(aave=_iso_days_ago(0), morpho=_iso_days_ago(3)),
        now=NOW, sender=sender,
    )
    assert fired is True
    assert len(sender.messages) == 1
    assert "Protocol Stale" in sender.messages[0]
    assert "morpho" in sender.messages[0]
    st = _state(tmp_path)
    assert st["consecutive_stale"] == 1
    assert st["last_alerted_cycle"] == 1
    assert st["last_stale_keys"] == ["morpho"]


def test_refire_on_consecutive_stale_cycle(tmp_path):
    """Stale persists a second cycle → re-fires (streak grew)."""
    rm = RiskMonitor(data_dir=tmp_path)
    sender = FakeSender()
    snap = _snap(aave=_iso_days_ago(0), morpho=_iso_days_ago(3))
    assert rm.alert_apy_feed_protocol_stale(snapshot=snap, now=NOW, sender=sender) is True
    # Next cycle, still stale (4 days old now).
    snap2 = _snap(aave=_iso_days_ago(0), morpho=_iso_days_ago(4))
    fired = rm.alert_apy_feed_protocol_stale(snapshot=snap2, now=NOW, sender=sender)
    assert fired is True
    assert len(sender.messages) == 2
    assert _state(tmp_path)["consecutive_stale"] == 2


def test_recovery_resets_streak(tmp_path):
    """After a stale alert, a healthy cycle resets the streak silently."""
    rm = RiskMonitor(data_dir=tmp_path)
    sender = FakeSender()
    rm.alert_apy_feed_protocol_stale(
        snapshot=_snap(morpho=_iso_days_ago(3)), now=NOW, sender=sender)
    assert len(sender.messages) == 1
    fired = rm.alert_apy_feed_protocol_stale(
        snapshot=_snap(morpho=_iso_days_ago(0)), now=NOW, sender=sender)
    assert fired is False
    assert len(sender.messages) == 1
    st = _state(tmp_path)
    assert st["consecutive_stale"] == 0
    assert st["last_alerted_cycle"] == 0
    assert st["last_stale_keys"] == []


def test_multiple_stale_protocols_listed(tmp_path):
    """Several stale protocols are all listed in the message."""
    rm = RiskMonitor(data_dir=tmp_path)
    sender = FakeSender()
    rm.alert_apy_feed_protocol_stale(
        snapshot=_snap(aave=_iso_days_ago(0),
                       morpho=_iso_days_ago(3),
                       euler=_iso_days_ago(5)),
        now=NOW, sender=sender,
    )
    assert len(sender.messages) == 1
    msg = sender.messages[0]
    assert "morpho" in msg and "euler" in msg
    assert sorted(_state(tmp_path)["last_stale_keys"]) == ["euler", "morpho"]


# ──────────────────────────────────────────────────────────────────────────
# Edge cases
# ──────────────────────────────────────────────────────────────────────────

def test_unparseable_date_counts_stale(tmp_path):
    """A record whose date can't be parsed is treated as stale."""
    rm = RiskMonitor(data_dir=tmp_path)
    sender = FakeSender()
    fired = rm.alert_apy_feed_protocol_stale(
        snapshot=_snap(aave="not-a-date"), now=NOW, sender=sender)
    assert fired is True
    assert "no parseable date" in sender.messages[0]


def test_none_date_counts_stale(tmp_path):
    """A protocol whose last record carries date=None is stale (unverifiable)."""
    rm = RiskMonitor(data_dir=tmp_path)
    sender = FakeSender()
    fired = rm.alert_apy_feed_protocol_stale(
        snapshot=_snap(aave=None), now=NOW, sender=sender)
    assert fired is True


def test_epoch_seconds_supported(tmp_path):
    """Numeric epoch-seconds timestamps are parsed (fresh → no alert)."""
    rm = RiskMonitor(data_dir=tmp_path)
    sender = FakeSender()
    epoch = NOW.timestamp()
    fired = rm.alert_apy_feed_protocol_stale(
        snapshot={"aave": epoch}, now=NOW, sender=sender)
    assert fired is False


def test_unreadable_snapshot_alerts(tmp_path):
    """snapshot=None AND no feed → unreadable → alert."""
    rm = RiskMonitor(data_dir=tmp_path)
    sender = FakeSender()
    fired = rm.alert_apy_feed_protocol_stale(snapshot=None, now=NOW, sender=sender)
    assert fired is True
    assert "unreadable" in sender.messages[0]


def test_naive_now_treated_as_utc(tmp_path):
    """A naive `now` is treated as UTC (no crash, correct age)."""
    rm = RiskMonitor(data_dir=tmp_path)
    sender = FakeSender()
    naive = datetime(2026, 5, 30, 12, 0, 0)  # no tzinfo
    fired = rm.alert_apy_feed_protocol_stale(
        snapshot=_snap(aave=_iso_days_ago(3)), now=naive, sender=sender)
    assert fired is True


# ──────────────────────────────────────────────────────────────────────────
# Feed-file resolution
# ──────────────────────────────────────────────────────────────────────────

def test_reads_last_date_from_feed_file_protocols(tmp_path):
    """Resolve last-record date from historical_apy.json (`protocols` key)."""
    _write_feed(tmp_path, {"aave": _iso_days_ago(0), "morpho": _iso_days_ago(4)})
    rm = RiskMonitor(data_dir=tmp_path)
    sender = FakeSender()
    fired = rm.alert_apy_feed_protocol_stale(
        feed_path=tmp_path / "historical_apy.json", now=NOW, sender=sender)
    assert fired is True
    assert "morpho" in sender.messages[0]


def test_reads_feed_file_protocol_history_key(tmp_path):
    """Also supports the `protocol_history` top-level key."""
    _write_feed(tmp_path, {"aave": _iso_days_ago(0), "yearn": _iso_days_ago(6)},
                key="protocol_history")
    rm = RiskMonitor(data_dir=tmp_path)
    sender = FakeSender()
    fired = rm.alert_apy_feed_protocol_stale(
        feed_path=tmp_path / "historical_apy.json", now=NOW, sender=sender)
    assert fired is True
    assert "yearn" in sender.messages[0]


def test_feed_all_fresh_no_alert(tmp_path):
    """A fully fresh feed file → no alert."""
    _write_feed(tmp_path, {"aave": _iso_days_ago(0), "morpho": _iso_days_ago(1)})
    rm = RiskMonitor(data_dir=tmp_path)
    sender = FakeSender()
    fired = rm.alert_apy_feed_protocol_stale(
        feed_path=tmp_path / "historical_apy.json", now=NOW, sender=sender)
    assert fired is False


def test_missing_feed_file_alerts_unreadable(tmp_path):
    """No feed file at all → unreadable → alert, no exception."""
    rm = RiskMonitor(data_dir=tmp_path)
    sender = FakeSender()
    fired = rm.alert_apy_feed_protocol_stale(
        feed_path=tmp_path / "does_not_exist.json", now=NOW, sender=sender)
    assert fired is True


def test_corrupt_feed_file_alerts_unreadable(tmp_path):
    """A corrupt JSON feed → unreadable → alert, no exception."""
    bad = tmp_path / "historical_apy.json"
    bad.write_text("{not valid json", encoding="utf-8")
    rm = RiskMonitor(data_dir=tmp_path)
    sender = FakeSender()
    fired = rm.alert_apy_feed_protocol_stale(
        feed_path=bad, now=NOW, sender=sender)
    assert fired is True


# ──────────────────────────────────────────────────────────────────────────
# Persistence / robustness
# ──────────────────────────────────────────────────────────────────────────

def test_persistence_across_instances(tmp_path):
    """Streak survives across RiskMonitor re-instantiation (same data_dir)."""
    sender = FakeSender()
    RiskMonitor(data_dir=tmp_path).alert_apy_feed_protocol_stale(
        snapshot=_snap(morpho=_iso_days_ago(3)), now=NOW, sender=sender)
    # Fresh instance, still stale next cycle → must re-fire (streak=2).
    fired = RiskMonitor(data_dir=tmp_path).alert_apy_feed_protocol_stale(
        snapshot=_snap(morpho=_iso_days_ago(4)), now=NOW, sender=sender)
    assert fired is True
    assert _state(tmp_path)["consecutive_stale"] == 2


def test_corrupt_state_recovers(tmp_path):
    """A corrupt state file is recovered (fresh) without raising."""
    sp = tmp_path / "apy_feed_protocol_stale_health_state.json"
    sp.write_text("{garbage", encoding="utf-8")
    rm = RiskMonitor(data_dir=tmp_path)
    sender = FakeSender()
    fired = rm.alert_apy_feed_protocol_stale(
        snapshot=_snap(morpho=_iso_days_ago(3)), now=NOW, sender=sender)
    assert fired is True
    assert _state(tmp_path)["consecutive_stale"] == 1


def test_bad_sender_swallowed(tmp_path):
    """A sender that raises is swallowed → returns False, streak persisted."""
    rm = RiskMonitor(data_dir=tmp_path)
    fired = rm.alert_apy_feed_protocol_stale(
        snapshot=_snap(morpho=_iso_days_ago(3)), now=NOW, sender=BadSender())
    assert fired is False
    st = _state(tmp_path)
    assert st["consecutive_stale"] == 1
    # last_alerted_cycle NOT advanced (send failed) → re-attempt next cycle.
    assert st["last_alerted_cycle"] == 0


def test_failed_send_retries_next_cycle(tmp_path):
    """ok=False sender → returns False; a working sender next cycle still fires."""
    rm = RiskMonitor(data_dir=tmp_path)
    fired = rm.alert_apy_feed_protocol_stale(
        snapshot=_snap(morpho=_iso_days_ago(3)), now=NOW, sender=FakeSender(ok=False))
    assert fired is False
    good = FakeSender()
    fired2 = rm.alert_apy_feed_protocol_stale(
        snapshot=_snap(morpho=_iso_days_ago(4)), now=NOW, sender=good)
    assert fired2 is True
    assert len(good.messages) == 1
