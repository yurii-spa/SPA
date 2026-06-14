"""
Tests for SPA-V350: APY-feed DATE MONOTONICITY & CONTINUITY validation + alert.

Covers RiskMonitor.alert_apy_feed_date_monotonicity — the consecutive-bad streak
tracker that validates the DATES of each protocol's history in historical_apy.json
advance monotonically (non-decreasing) and continuously (no gaps wider than
APY_FEED_MAX_DATE_GAP_HOURS). This is a data-integrity blind spot none of the
other eight feed-health monitors can see: a history whose dates run BACKWARDS in
time (date regression) or skip days (large gap) passes freshness, count, delta,
structure, type and value-range checks, yet silently corrupts the rolling-90d
covariance / dynamic-Kelly computation that walks the whole dated series.

Date convention: the DeFiLlama feed is dated at DAILY granularity
(``YYYY-MM-DD``), so a gap > 72h (≥2 skipped days) is a degradation. Records also
accept ``ts`` / ``timestamp`` (epoch seconds or ISO).

Like value-bounds / schema-drift, a bad cycle alerts on the very first bad cycle
(threshold 1). All tests run fully offline (FakeSender) with a tmp_path-isolated
data_dir — no network, no real data/ writes.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

# Make ``spa_core`` importable when tests run from the repo root.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from alerts.risk_monitor import (  # noqa: E402
    RiskMonitor,
    APY_FEED_MAX_DATE_GAP_HOURS,
    APY_FEED_MONO_MAX_BAD_PCT,
    APY_FEED_MONO_MIN_PROTOCOLS,
)


class FakeSender:
    """Offline TelegramSender stand-in: records messages, never hits network."""

    def __init__(self):
        self.messages: list[str] = []

    def send(self, msg: str) -> bool:
        self.messages.append(msg)
        return True

    def send_risk_alert(self, *a, **k) -> bool:
        return True


@pytest.fixture()
def monitor(tmp_path):
    """RiskMonitor with isolated data_dir (no real data/ writes)."""
    return RiskMonitor(data_dir=tmp_path)


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

def _rec(date, apy=5.0, tvl=1e9, field="date", **extra):
    """A history record dated via ``field`` (date|ts|timestamp)."""
    rec = {"apy": apy, "tvl_usd": tvl, field: date}
    rec.update(extra)
    return rec


def _daily(*days, field="date"):
    """Build a history list of YYYY-MM-DD records for the given day numbers."""
    return [_rec(f"2026-05-{d:02d}", field=field) for d in days]


def _records(**protos):
    """Build a protocol -> history(list) mapping."""
    return dict(protos)


def _write_feed(path, protocols, root_key="protocols"):
    """Write a historical_apy.json-shaped file with given protocols mapping."""
    path.write_text(json.dumps({root_key: protocols}), encoding="utf-8")


# ---------------------------------------------------------------------------
# constants sanity
# ---------------------------------------------------------------------------

def test_constants_present():
    assert APY_FEED_MAX_DATE_GAP_HOURS == 72.0
    assert 0 < APY_FEED_MONO_MAX_BAD_PCT <= 1
    assert APY_FEED_MONO_MIN_PROTOCOLS >= 1


# ---------------------------------------------------------------------------
# healthy / monotonic histories — no alert
# ---------------------------------------------------------------------------

def test_healthy_monotonic_no_alert(monitor):
    recs = _records(
        aave=_daily(28, 29, 30),
        compound=_daily(27, 28, 29, 30),
    )
    sender = FakeSender()
    fired = monitor.alert_apy_feed_date_monotonicity(snapshot=recs, sender=sender)
    assert fired is False
    assert sender.messages == []


def test_single_record_history_ok(monitor):
    # < 2 valid dates → nothing to compare → OK.
    recs = _records(aave=_daily(30))
    sender = FakeSender()
    fired = monitor.alert_apy_feed_date_monotonicity(snapshot=recs, sender=sender)
    assert fired is False


def test_equal_dates_non_decreasing_ok(monitor):
    # Equal adjacent dates are non-decreasing (not a regression) → OK.
    recs = _records(aave=_daily(30, 30, 30))
    sender = FakeSender()
    fired = monitor.alert_apy_feed_date_monotonicity(snapshot=recs, sender=sender)
    assert fired is False


def test_gap_at_threshold_ok(monitor):
    # Exactly 72h gap (2 calendar days apart at midnight = 48h) is well within;
    # build a 72h gap explicitly via ISO timestamps and confirm == is allowed.
    recs = _records(aave=[
        _rec("2026-05-27T00:00:00Z"),
        _rec("2026-05-30T00:00:00Z"),  # exactly 72h later
    ])
    sender = FakeSender()
    fired = monitor.alert_apy_feed_date_monotonicity(snapshot=recs, sender=sender)
    # 72h is NOT > 72h → OK.
    assert fired is False


def test_epoch_ts_monotonic_ok(monitor):
    recs = _records(aave=[
        _rec(1_700_000_000, field="ts"),
        _rec(1_700_086_400, field="ts"),  # +1 day
    ])
    sender = FakeSender()
    fired = monitor.alert_apy_feed_date_monotonicity(snapshot=recs, sender=sender)
    assert fired is False


def test_timestamp_iso_field_ok(monitor):
    recs = _records(aave=[
        _rec("2026-05-29T12:00:00Z", field="timestamp"),
        _rec("2026-05-30T12:00:00Z", field="timestamp"),
    ])
    sender = FakeSender()
    fired = monitor.alert_apy_feed_date_monotonicity(snapshot=recs, sender=sender)
    assert fired is False


def test_nonnumeric_apy_does_not_matter(monitor):
    # apy/tvl garbage is schema-drift's concern; dates are fine → OK.
    recs = _records(aave=[
        _rec("2026-05-29", apy="n/a", tvl="x"),
        _rec("2026-05-30", apy="n/a", tvl="x"),
    ])
    sender = FakeSender()
    fired = monitor.alert_apy_feed_date_monotonicity(snapshot=recs, sender=sender)
    assert fired is False


# ---------------------------------------------------------------------------
# date regression — fire
# ---------------------------------------------------------------------------

def test_date_regression_fires(monitor):
    recs = _records(aave=_daily(30, 29))  # backwards
    sender = FakeSender()
    fired = monitor.alert_apy_feed_date_monotonicity(snapshot=recs, sender=sender)
    assert fired is True
    assert any("regression" in m.lower() for m in sender.messages)


def test_regression_mid_series_fires(monitor):
    recs = _records(aave=_daily(28, 29, 27, 30))  # dip at idx 2
    sender = FakeSender()
    fired = monitor.alert_apy_feed_date_monotonicity(snapshot=recs, sender=sender)
    assert fired is True


def test_regression_epoch_fires(monitor):
    recs = _records(aave=[
        _rec(1_700_086_400, field="ts"),
        _rec(1_700_000_000, field="ts"),  # earlier → regression
    ])
    sender = FakeSender()
    fired = monitor.alert_apy_feed_date_monotonicity(snapshot=recs, sender=sender)
    assert fired is True


# ---------------------------------------------------------------------------
# large gap — fire
# ---------------------------------------------------------------------------

def test_large_gap_fires(monitor):
    # 28 -> 02-Jun = 5 days = 120h gap > 72h.
    recs = _records(aave=[_rec("2026-05-28"), _rec("2026-06-02")])
    sender = FakeSender()
    fired = monitor.alert_apy_feed_date_monotonicity(snapshot=recs, sender=sender)
    assert fired is True
    assert any("gap" in m.lower() for m in sender.messages)


def test_gap_just_over_threshold_fires(monitor):
    # 72h + 1h = 73h > 72h.
    recs = _records(aave=[
        _rec("2026-05-27T00:00:00Z"),
        _rec("2026-05-30T01:00:00Z"),
    ])
    sender = FakeSender()
    fired = monitor.alert_apy_feed_date_monotonicity(snapshot=recs, sender=sender)
    assert fired is True


def test_gap_mid_series_fires(monitor):
    recs = _records(aave=[
        _rec("2026-05-20"), _rec("2026-05-21"),
        _rec("2026-05-28"),  # 7-day jump
        _rec("2026-05-29"),
    ])
    sender = FakeSender()
    fired = monitor.alert_apy_feed_date_monotonicity(snapshot=recs, sender=sender)
    assert fired is True


# ---------------------------------------------------------------------------
# unparseable / missing dates — bad
# ---------------------------------------------------------------------------

def test_unparseable_date_fires(monitor):
    recs = _records(aave=[_rec("not-a-date"), _rec("2026-05-30")])
    sender = FakeSender()
    fired = monitor.alert_apy_feed_date_monotonicity(snapshot=recs, sender=sender)
    assert fired is True
    assert any("unparseable" in m.lower() for m in sender.messages)


def test_missing_date_field_fires(monitor):
    recs = _records(aave=[{"apy": 5.0, "tvl_usd": 1e9},
                          {"apy": 5.0, "tvl_usd": 1e9}])
    sender = FakeSender()
    fired = monitor.alert_apy_feed_date_monotonicity(snapshot=recs, sender=sender)
    assert fired is True


def test_none_date_fires(monitor):
    recs = _records(aave=[_rec(None), _rec("2026-05-30")])
    sender = FakeSender()
    fired = monitor.alert_apy_feed_date_monotonicity(snapshot=recs, sender=sender)
    assert fired is True


def test_non_dict_record_fires(monitor):
    recs = _records(aave=["2026-05-29", "2026-05-30"])  # records are strings
    sender = FakeSender()
    fired = monitor.alert_apy_feed_date_monotonicity(snapshot=recs, sender=sender)
    assert fired is True


def test_bool_date_fires(monitor):
    recs = _records(aave=[_rec(True), _rec("2026-05-30")])
    sender = FakeSender()
    fired = monitor.alert_apy_feed_date_monotonicity(snapshot=recs, sender=sender)
    assert fired is True


# ---------------------------------------------------------------------------
# bad-fraction threshold (< vs >=)
# ---------------------------------------------------------------------------

def test_bad_fraction_below_threshold_no_alert(monitor):
    # 1 of 3 bad = 33% < 50% → healthy.
    recs = _records(
        a=_daily(28, 29, 30),
        b=_daily(28, 29, 30),
        bad=_daily(30, 29),
    )
    sender = FakeSender()
    fired = monitor.alert_apy_feed_date_monotonicity(snapshot=recs, sender=sender)
    assert fired is False
    assert sender.messages == []


def test_bad_fraction_at_threshold_fires(monitor):
    # 1 of 2 = 50% >= 50% → bad.
    recs = _records(
        a=_daily(28, 29, 30),
        bad=_daily(30, 29),
    )
    sender = FakeSender()
    fired = monitor.alert_apy_feed_date_monotonicity(snapshot=recs, sender=sender)
    assert fired is True


def test_bad_fraction_above_threshold_fires(monitor):
    # 2 of 3 = 66% >= 50% → bad.
    recs = _records(
        a=_daily(28, 29, 30),
        bad1=_daily(30, 28),
        bad2=[_rec("2026-05-20"), _rec("2026-05-30")],  # gap
    )
    sender = FakeSender()
    fired = monitor.alert_apy_feed_date_monotonicity(snapshot=recs, sender=sender)
    assert fired is True


def test_single_protocol_bad_fires(monitor):
    # 1 of 1 = 100% → bad (min_protocols=1).
    recs = _records(aave=_daily(30, 29))
    sender = FakeSender()
    fired = monitor.alert_apy_feed_date_monotonicity(snapshot=recs, sender=sender)
    assert fired is True


def test_empty_history_excluded_from_denominator(monitor):
    # Empty histories are skipped (not counted). 1 bad of 1 usable → fire.
    recs = _records(
        empty=[],
        bad=_daily(30, 29),
    )
    sender = FakeSender()
    fired = monitor.alert_apy_feed_date_monotonicity(snapshot=recs, sender=sender)
    assert fired is True


# ---------------------------------------------------------------------------
# unreadable: missing / corrupt / no protocols
# ---------------------------------------------------------------------------

def test_missing_file_unreadable_fires(monitor, tmp_path):
    feed = tmp_path / "historical_apy.json"  # does not exist
    sender = FakeSender()
    fired = monitor.alert_apy_feed_date_monotonicity(feed_path=str(feed), sender=sender)
    assert fired is True
    assert any("unreadable" in m.lower() for m in sender.messages)


def test_corrupt_file_unreadable_fires(monitor, tmp_path):
    feed = tmp_path / "historical_apy.json"
    feed.write_text("{not valid json", encoding="utf-8")
    sender = FakeSender()
    fired = monitor.alert_apy_feed_date_monotonicity(feed_path=str(feed), sender=sender)
    assert fired is True
    assert any("unreadable" in m.lower() for m in sender.messages)


def test_no_protocols_key_unreadable_fires(monitor, tmp_path):
    feed = tmp_path / "historical_apy.json"
    feed.write_text(json.dumps({"generated_at": "2026-05-30"}), encoding="utf-8")
    sender = FakeSender()
    fired = monitor.alert_apy_feed_date_monotonicity(feed_path=str(feed), sender=sender)
    assert fired is True


def test_all_empty_histories_unreadable_fires(monitor):
    recs = _records(a=[], b=[])
    sender = FakeSender()
    fired = monitor.alert_apy_feed_date_monotonicity(snapshot=recs, sender=sender)
    assert fired is True


# ---------------------------------------------------------------------------
# too_few
# ---------------------------------------------------------------------------

def test_too_few_via_min_protocols(tmp_path):
    import alerts.risk_monitor as rm
    orig = rm.APY_FEED_MONO_MIN_PROTOCOLS
    rm.APY_FEED_MONO_MIN_PROTOCOLS = 5
    try:
        m = RiskMonitor(data_dir=tmp_path)
        recs = _records(a=_daily(29, 30), b=_daily(29, 30))  # only 2 < 5
        sender = FakeSender()
        fired = m.alert_apy_feed_date_monotonicity(snapshot=recs, sender=sender)
        assert fired is True
        assert any("floor" in msg.lower() for msg in sender.messages)
    finally:
        rm.APY_FEED_MONO_MIN_PROTOCOLS = orig


# ---------------------------------------------------------------------------
# streak / refire / reset
# ---------------------------------------------------------------------------

def test_streak_refire_then_reset(monitor):
    bad = _records(aave=_daily(30, 29))
    good = _records(aave=_daily(29, 30))
    sender = FakeSender()
    assert monitor.alert_apy_feed_date_monotonicity(snapshot=bad, sender=sender) is True
    assert monitor.alert_apy_feed_date_monotonicity(snapshot=bad, sender=sender) is True
    assert monitor.alert_apy_feed_date_monotonicity(snapshot=good, sender=sender) is False
    assert monitor.alert_apy_feed_date_monotonicity(snapshot=good, sender=sender) is False
    assert len(sender.messages) == 2


def test_recovery_then_rebad_fires_again(monitor):
    bad = _records(aave=_daily(30, 29))
    good = _records(aave=_daily(29, 30))
    sender = FakeSender()
    assert monitor.alert_apy_feed_date_monotonicity(snapshot=bad, sender=sender) is True
    assert monitor.alert_apy_feed_date_monotonicity(snapshot=good, sender=sender) is False
    assert monitor.alert_apy_feed_date_monotonicity(snapshot=bad, sender=sender) is True


# ---------------------------------------------------------------------------
# persistent state
# ---------------------------------------------------------------------------

def test_persistent_state_roundtrip(monitor, tmp_path):
    bad = _records(aave=_daily(30, 29))
    sender = FakeSender()
    monitor.alert_apy_feed_date_monotonicity(snapshot=bad, sender=sender)
    state_file = tmp_path / "apy_feed_monotonicity_health_state.json"
    assert state_file.exists()
    data = json.loads(state_file.read_text())
    assert "prev_bad_keys" in data
    assert "consecutive_mono" in data
    assert "last_alerted_cycle" in data
    assert "updated_at" in data
    assert data["consecutive_mono"] == 1
    assert "aave" in data["prev_bad_keys"]


def test_state_survives_new_instance(monitor, tmp_path):
    bad = _records(aave=_daily(30, 29))
    sender = FakeSender()
    monitor.alert_apy_feed_date_monotonicity(snapshot=bad, sender=sender)
    m2 = RiskMonitor(data_dir=tmp_path)
    s2 = FakeSender()
    fired = m2.alert_apy_feed_date_monotonicity(snapshot=bad, sender=s2)
    assert fired is True


def test_corrupt_state_graceful(monitor, tmp_path):
    state_file = tmp_path / "apy_feed_monotonicity_health_state.json"
    state_file.write_text("{garbage", encoding="utf-8")
    bad = _records(aave=_daily(30, 29))
    sender = FakeSender()
    fired = monitor.alert_apy_feed_date_monotonicity(snapshot=bad, sender=sender)
    assert fired is True


def test_healthy_state_written(monitor, tmp_path):
    good = _records(aave=_daily(29, 30))
    sender = FakeSender()
    monitor.alert_apy_feed_date_monotonicity(snapshot=good, sender=sender)
    state_file = tmp_path / "apy_feed_monotonicity_health_state.json"
    assert state_file.exists()
    data = json.loads(state_file.read_text())
    assert data["consecutive_mono"] == 0


# ---------------------------------------------------------------------------
# never raises
# ---------------------------------------------------------------------------

def test_never_raises_on_bad_snapshot_type(monitor):
    sender = FakeSender()
    fired = monitor.alert_apy_feed_date_monotonicity(snapshot="not-a-dict", sender=sender)
    assert fired in (True, False)


def test_never_raises_no_args(monitor):
    sender = FakeSender()
    fired = monitor.alert_apy_feed_date_monotonicity(sender=sender)
    assert fired in (True, False)


def test_never_raises_weird_values(monitor):
    sender = FakeSender()
    recs = {"aave": [{"date": [1, 2, 3]}, {"date": {"x": 1}}]}
    fired = monitor.alert_apy_feed_date_monotonicity(snapshot=recs, sender=sender)
    assert fired in (True, False)


def test_no_sender_no_crash(monitor):
    # sender=None path: lazy TelegramSender import likely fails offline → swallowed.
    bad = _records(aave=_daily(30, 29))
    fired = monitor.alert_apy_feed_date_monotonicity(snapshot=bad)
    assert fired in (True, False)


# ---------------------------------------------------------------------------
# feed-file reading + protocol_history alias + snapshot precedence
# ---------------------------------------------------------------------------

def test_feed_file_healthy_read(monitor, tmp_path):
    feed = tmp_path / "historical_apy.json"
    _write_feed(feed, {"aave": _daily(29, 30)})
    sender = FakeSender()
    fired = monitor.alert_apy_feed_date_monotonicity(feed_path=str(feed), sender=sender)
    assert fired is False


def test_feed_file_regression_read(monitor, tmp_path):
    feed = tmp_path / "historical_apy.json"
    _write_feed(feed, {"aave": _daily(30, 29)})
    sender = FakeSender()
    fired = monitor.alert_apy_feed_date_monotonicity(feed_path=str(feed), sender=sender)
    assert fired is True


def test_protocol_history_alias_key(monitor, tmp_path):
    feed = tmp_path / "historical_apy.json"
    _write_feed(feed, {"aave": _daily(29, 30)}, root_key="protocol_history")
    sender = FakeSender()
    fired = monitor.alert_apy_feed_date_monotonicity(feed_path=str(feed), sender=sender)
    assert fired is False


def test_snapshot_takes_precedence_over_feed(monitor, tmp_path):
    feed = tmp_path / "historical_apy.json"
    _write_feed(feed, {"aave": _daily(30, 29)})  # bad in file
    sender = FakeSender()
    fired = monitor.alert_apy_feed_date_monotonicity(
        snapshot=_records(aave=_daily(29, 30)), feed_path=str(feed), sender=sender
    )
    assert fired is False


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))
