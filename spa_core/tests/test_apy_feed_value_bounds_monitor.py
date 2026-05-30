"""
Tests for SPA-V349: APY-feed VALUE-RANGE sanity-bounds validation + alert.

Covers RiskMonitor.alert_apy_feed_value_bounds — the consecutive-bad streak
tracker that validates the numeric VALUES of historical_apy.json fall in sane
RANGES and fires the moment too many protocols carry out-of-bounds numbers
(apy > 1000% / apy < 0 / tvl_usd <= 0 / tvl_usd > $10T). This is a blind spot
none of the aggregate / per-protocol / schema monitors can see: a
type-valid-but-garbage number passes freshness, count, delta, structure and
TYPE checks yet poisons the covariance / dynamic-Kelly universe.

apy unit convention: the DeFiLlama feed stores ``apy`` as a PERCENT number
(6.3057 == 6.3057%, see execution/defillama_apy_feed.py "Return live APY (%)"
and data/historical_apy.json), so the upper bound is 1000.0 (== 1000%). tvl_usd
is raw USD.

Like schema-drift, a bad cycle alerts on the very first bad cycle (threshold 1).
All tests run fully offline (FakeSender) with a tmp_path-isolated data_dir — no
network, no real data/ writes.
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
    APY_FEED_APY_MIN,
    APY_FEED_APY_MAX,
    APY_FEED_TVL_MIN,
    APY_FEED_TVL_MAX,
    APY_FEED_BOUNDS_MAX_BAD_PCT,
    APY_FEED_BOUNDS_MIN_PROTOCOLS,
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

def _good(apy=5.0, tvl=1e9, **extra):
    """A well-formed, in-bounds history record."""
    rec = {"apy": apy, "tvl_usd": tvl}
    rec.update(extra)
    return rec


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
    assert APY_FEED_APY_MIN == 0.0
    # apy stored as a PERCENT number -> bound is 1000.0 (1000%).
    assert APY_FEED_APY_MAX == 1000.0
    assert APY_FEED_TVL_MIN == 0.0
    assert APY_FEED_TVL_MAX == 1.0e13
    assert 0 < APY_FEED_BOUNDS_MAX_BAD_PCT <= 1
    assert APY_FEED_BOUNDS_MIN_PROTOCOLS >= 1


# ---------------------------------------------------------------------------
# healthy / in-bounds cases — no alert
# ---------------------------------------------------------------------------

def test_healthy_in_bounds_no_alert(monitor):
    recs = _records(
        aave=[_good(6.3, 1.38e8)],
        compound=[_good(0.77, 4.2e7)],
    )
    sender = FakeSender()
    fired = monitor.alert_apy_feed_value_bounds(records=recs, sender=sender)
    assert fired is False
    assert sender.messages == []


def test_healthy_with_numeric_string_ok(monitor):
    # Numeric strings are coerced via float() and range-checked normally.
    recs = _records(aave=[{"apy": "5.0", "tvl_usd": "1000000000"}])
    sender = FakeSender()
    fired = monitor.alert_apy_feed_value_bounds(records=recs, sender=sender)
    assert fired is False
    assert sender.messages == []


def test_apy_zero_is_in_bounds(monitor):
    # apy == 0 is allowed (>= APY_FEED_APY_MIN).
    recs = _records(aave=[_good(0.0, 1e9)])
    sender = FakeSender()
    fired = monitor.alert_apy_feed_value_bounds(records=recs, sender=sender)
    assert fired is False


def test_apy_at_max_in_bounds(monitor):
    # apy == APY_FEED_APY_MAX is allowed (> is bad, == is fine).
    recs = _records(aave=[_good(APY_FEED_APY_MAX, 1e9)])
    sender = FakeSender()
    fired = monitor.alert_apy_feed_value_bounds(records=recs, sender=sender)
    assert fired is False


def test_tvl_at_max_in_bounds(monitor):
    recs = _records(aave=[_good(5.0, APY_FEED_TVL_MAX)])
    sender = FakeSender()
    fired = monitor.alert_apy_feed_value_bounds(records=recs, sender=sender)
    assert fired is False


def test_uses_last_record_only(monitor):
    # Only the LAST record is range-checked; earlier oob records are ignored.
    recs = _records(aave=[_good(99999.0, 1e9), _good(5.0, 1e9)])
    sender = FakeSender()
    fired = monitor.alert_apy_feed_value_bounds(records=recs, sender=sender)
    assert fired is False


def test_extra_fields_ignored(monitor):
    recs = _records(aave=[_good(5.0, 1e9, date="2026-05-30", chain="eth")])
    sender = FakeSender()
    fired = monitor.alert_apy_feed_value_bounds(records=recs, sender=sender)
    assert fired is False


# ---------------------------------------------------------------------------
# out of bounds: apy
# ---------------------------------------------------------------------------

def test_apy_negative_fires(monitor):
    recs = _records(aave=[_good(-1.0, 1e9)])
    sender = FakeSender()
    fired = monitor.alert_apy_feed_value_bounds(records=recs, sender=sender)
    assert fired is True
    assert any("apy" in m.lower() and "< 0" in m for m in sender.messages)


def test_apy_over_max_fires(monitor):
    # 50000% — type-valid garbage.
    recs = _records(aave=[_good(50000.0, 1e9)])
    sender = FakeSender()
    fired = monitor.alert_apy_feed_value_bounds(records=recs, sender=sender)
    assert fired is True
    assert any("apy" in m.lower() and "> 1000" in m for m in sender.messages)


def test_apy_just_over_max_fires(monitor):
    recs = _records(aave=[_good(1000.0001, 1e9)])
    sender = FakeSender()
    fired = monitor.alert_apy_feed_value_bounds(records=recs, sender=sender)
    assert fired is True


# ---------------------------------------------------------------------------
# out of bounds: tvl
# ---------------------------------------------------------------------------

def test_tvl_zero_fires(monitor):
    # tvl_usd must be strictly > 0.
    recs = _records(aave=[_good(5.0, 0.0)])
    sender = FakeSender()
    fired = monitor.alert_apy_feed_value_bounds(records=recs, sender=sender)
    assert fired is True
    assert any("tvl_usd" in m.lower() and "<= 0" in m for m in sender.messages)


def test_tvl_negative_fires(monitor):
    recs = _records(aave=[_good(5.0, -100.0)])
    sender = FakeSender()
    fired = monitor.alert_apy_feed_value_bounds(records=recs, sender=sender)
    assert fired is True


def test_tvl_over_max_fires(monitor):
    # 100 trillion — absurd.
    recs = _records(aave=[_good(5.0, 1e14)])
    sender = FakeSender()
    fired = monitor.alert_apy_feed_value_bounds(records=recs, sender=sender)
    assert fired is True
    assert any("tvl_usd" in m.lower() for m in sender.messages)


def test_both_apy_and_tvl_oob_fires(monitor):
    recs = _records(aave=[_good(-5.0, 0.0)])
    sender = FakeSender()
    fired = monitor.alert_apy_feed_value_bounds(records=recs, sender=sender)
    assert fired is True
    # message should mention both violations
    assert any("apy" in m.lower() and "tvl_usd" in m.lower() for m in sender.messages)


# ---------------------------------------------------------------------------
# non-numeric records skipped (schema-drift's concern, not ours)
# ---------------------------------------------------------------------------

def test_non_numeric_apy_skipped_not_counted(monitor):
    # Non-numeric apy → skipped from bounds denominator; only the good one
    # counts and is in-bounds → no alert.
    recs = _records(
        aave=[_good(5.0, 1e9)],
        broken=[{"apy": "n/a", "tvl_usd": 1e9}],
    )
    sender = FakeSender()
    fired = monitor.alert_apy_feed_value_bounds(records=recs, sender=sender)
    assert fired is False
    assert sender.messages == []


def test_missing_field_skipped_not_counted(monitor):
    recs = _records(
        aave=[_good(5.0, 1e9)],
        broken=[{"apy": 5.0}],  # tvl_usd missing → skipped
    )
    sender = FakeSender()
    fired = monitor.alert_apy_feed_value_bounds(records=recs, sender=sender)
    assert fired is False


def test_bool_apy_skipped(monitor):
    # bool is not a usable number for bounds (schema-drift owns type policing).
    recs = _records(
        aave=[_good(5.0, 1e9)],
        broken=[{"apy": True, "tvl_usd": 1e9}],
    )
    sender = FakeSender()
    fired = monitor.alert_apy_feed_value_bounds(records=recs, sender=sender)
    assert fired is False


# ---------------------------------------------------------------------------
# bad-fraction threshold (< vs >=)
# ---------------------------------------------------------------------------

def test_bad_fraction_below_threshold_no_alert(monitor):
    # 1 of 3 oob = 33% < 50% → healthy (no alert).
    recs = _records(
        aave=[_good()],
        comp=[_good()],
        bad=[_good(99999.0, 1e9)],
    )
    sender = FakeSender()
    fired = monitor.alert_apy_feed_value_bounds(records=recs, sender=sender)
    assert fired is False
    assert sender.messages == []


def test_bad_fraction_at_threshold_fires(monitor):
    # 1 of 2 oob = 50% >= 50% → bad.
    recs = _records(
        aave=[_good()],
        bad=[_good(99999.0, 1e9)],
    )
    sender = FakeSender()
    fired = monitor.alert_apy_feed_value_bounds(records=recs, sender=sender)
    assert fired is True


def test_bad_fraction_above_threshold_fires(monitor):
    # 2 of 3 oob = 66% >= 50% → bad.
    recs = _records(
        aave=[_good()],
        bad1=[_good(-1.0, 1e9)],
        bad2=[_good(5.0, 0.0)],
    )
    sender = FakeSender()
    fired = monitor.alert_apy_feed_value_bounds(records=recs, sender=sender)
    assert fired is True


def test_mixed_below_above_threshold(monitor):
    # 2 of 5 oob = 40% < 50% → no alert; non-numeric ones excluded from denom.
    recs = _records(
        a=[_good()],
        b=[_good()],
        c=[_good()],
        bad1=[_good(-1.0, 1e9)],
        bad2=[_good(99999.0, 1e9)],
        skip=[{"apy": "x", "tvl_usd": "y"}],  # excluded
    )
    sender = FakeSender()
    fired = monitor.alert_apy_feed_value_bounds(records=recs, sender=sender)
    assert fired is False


# ---------------------------------------------------------------------------
# unreadable: missing / corrupt / no numeric protocols
# ---------------------------------------------------------------------------

def test_missing_file_unreadable_fires(monitor, tmp_path):
    feed = tmp_path / "historical_apy.json"  # does not exist
    sender = FakeSender()
    fired = monitor.alert_apy_feed_value_bounds(feed_path=str(feed), sender=sender)
    assert fired is True
    assert any("unreadable" in m.lower() for m in sender.messages)


def test_corrupt_file_unreadable_fires(monitor, tmp_path):
    feed = tmp_path / "historical_apy.json"
    feed.write_text("{not valid json", encoding="utf-8")
    sender = FakeSender()
    fired = monitor.alert_apy_feed_value_bounds(feed_path=str(feed), sender=sender)
    assert fired is True
    assert any("unreadable" in m.lower() for m in sender.messages)


def test_no_protocols_key_unreadable_fires(monitor, tmp_path):
    feed = tmp_path / "historical_apy.json"
    feed.write_text(json.dumps({"generated_at": "2026-05-30"}), encoding="utf-8")
    sender = FakeSender()
    fired = monitor.alert_apy_feed_value_bounds(feed_path=str(feed), sender=sender)
    assert fired is True


def test_all_non_numeric_unreadable_fires(monitor):
    # No usable numeric protocols → unreadable.
    recs = _records(
        a=[{"apy": "x", "tvl_usd": "y"}],
        b=[{"apy": None, "tvl_usd": None}],
    )
    sender = FakeSender()
    fired = monitor.alert_apy_feed_value_bounds(records=recs, sender=sender)
    assert fired is True


def test_empty_histories_unreadable_fires(monitor):
    recs = _records(a=[], b=[])
    sender = FakeSender()
    fired = monitor.alert_apy_feed_value_bounds(records=recs, sender=sender)
    assert fired is True


# ---------------------------------------------------------------------------
# too_few
# ---------------------------------------------------------------------------

def test_too_few_via_min_protocols(tmp_path):
    # Force the floor high to exercise the too_few branch deterministically.
    import alerts.risk_monitor as rm
    orig = rm.APY_FEED_BOUNDS_MIN_PROTOCOLS
    rm.APY_FEED_BOUNDS_MIN_PROTOCOLS = 5
    try:
        m = RiskMonitor(data_dir=tmp_path)
        recs = _records(aave=[_good()], comp=[_good()])  # only 2 usable < 5
        sender = FakeSender()
        fired = m.alert_apy_feed_value_bounds(records=recs, sender=sender)
        assert fired is True
        assert any("floor" in msg.lower() for msg in sender.messages)
    finally:
        rm.APY_FEED_BOUNDS_MIN_PROTOCOLS = orig


# ---------------------------------------------------------------------------
# streak / refire / reset
# ---------------------------------------------------------------------------

def test_streak_refire_then_reset(monitor):
    bad = _records(aave=[_good(99999.0, 1e9)])
    good = _records(aave=[_good()])
    sender = FakeSender()
    f1 = monitor.alert_apy_feed_value_bounds(records=bad, sender=sender)
    assert f1 is True
    f2 = monitor.alert_apy_feed_value_bounds(records=bad, sender=sender)
    assert f2 is True
    f3 = monitor.alert_apy_feed_value_bounds(records=good, sender=sender)
    assert f3 is False
    f4 = monitor.alert_apy_feed_value_bounds(records=good, sender=sender)
    assert f4 is False
    assert len(sender.messages) == 2


def test_recovery_then_rebad_fires_again(monitor):
    bad = _records(aave=[_good(5.0, 0.0)])
    good = _records(aave=[_good()])
    sender = FakeSender()
    assert monitor.alert_apy_feed_value_bounds(records=bad, sender=sender) is True
    assert monitor.alert_apy_feed_value_bounds(records=good, sender=sender) is False
    # bad returns after a healthy cycle → fires again (streak restarted)
    assert monitor.alert_apy_feed_value_bounds(records=bad, sender=sender) is True


# ---------------------------------------------------------------------------
# persistent state
# ---------------------------------------------------------------------------

def test_persistent_state_roundtrip(monitor, tmp_path):
    bad = _records(aave=[_good(99999.0, 1e9)])
    sender = FakeSender()
    monitor.alert_apy_feed_value_bounds(records=bad, sender=sender)
    state_file = tmp_path / "apy_feed_bounds_health_state.json"
    assert state_file.exists()
    data = json.loads(state_file.read_text())
    assert "prev_bad_keys" in data
    assert "consecutive_bounds" in data
    assert "last_alerted_cycle" in data
    assert "updated_at" in data
    assert data["consecutive_bounds"] == 1
    assert "aave" in data["prev_bad_keys"]


def test_state_survives_new_instance(monitor, tmp_path):
    bad = _records(aave=[_good(99999.0, 1e9)])
    sender = FakeSender()
    monitor.alert_apy_feed_value_bounds(records=bad, sender=sender)
    m2 = RiskMonitor(data_dir=tmp_path)
    s2 = FakeSender()
    fired = m2.alert_apy_feed_value_bounds(records=bad, sender=s2)
    assert fired is True


def test_corrupt_state_graceful(monitor, tmp_path):
    state_file = tmp_path / "apy_feed_bounds_health_state.json"
    state_file.write_text("{garbage", encoding="utf-8")
    bad = _records(aave=[_good(99999.0, 1e9)])
    sender = FakeSender()
    fired = monitor.alert_apy_feed_value_bounds(records=bad, sender=sender)
    assert fired is True


def test_healthy_state_written(monitor, tmp_path):
    good = _records(aave=[_good()])
    sender = FakeSender()
    monitor.alert_apy_feed_value_bounds(records=good, sender=sender)
    state_file = tmp_path / "apy_feed_bounds_health_state.json"
    assert state_file.exists()
    data = json.loads(state_file.read_text())
    assert data["consecutive_bounds"] == 0


# ---------------------------------------------------------------------------
# never raises
# ---------------------------------------------------------------------------

def test_never_raises_on_bad_records_type(monitor):
    sender = FakeSender()
    fired = monitor.alert_apy_feed_value_bounds(records="not-a-dict", sender=sender)
    assert fired in (True, False)


def test_never_raises_no_args(monitor):
    sender = FakeSender()
    fired = monitor.alert_apy_feed_value_bounds(sender=sender)
    assert fired in (True, False)


def test_never_raises_records_with_weird_values(monitor):
    sender = FakeSender()
    recs = {"aave": [{"apy": [1, 2, 3], "tvl_usd": {"nested": 1}}]}
    fired = monitor.alert_apy_feed_value_bounds(records=recs, sender=sender)
    # list/dict values are non-numeric → skipped → no usable → unreadable, no raise
    assert fired in (True, False)


def test_no_sender_no_crash(monitor):
    # sender=None path: lazy TelegramSender import will fail offline → swallowed.
    bad = _records(aave=[_good(99999.0, 1e9)])
    fired = monitor.alert_apy_feed_value_bounds(records=bad)
    assert fired in (True, False)


# ---------------------------------------------------------------------------
# feed-file reading + protocol_history alias
# ---------------------------------------------------------------------------

def test_feed_file_healthy_read(monitor, tmp_path):
    feed = tmp_path / "historical_apy.json"
    _write_feed(feed, {"aave": [_good()]})
    sender = FakeSender()
    fired = monitor.alert_apy_feed_value_bounds(feed_path=str(feed), sender=sender)
    assert fired is False


def test_feed_file_oob_read(monitor, tmp_path):
    feed = tmp_path / "historical_apy.json"
    _write_feed(feed, {"aave": [_good(99999.0, 1e9)]})
    sender = FakeSender()
    fired = monitor.alert_apy_feed_value_bounds(feed_path=str(feed), sender=sender)
    assert fired is True


def test_protocol_history_alias_key(monitor, tmp_path):
    feed = tmp_path / "historical_apy.json"
    _write_feed(feed, {"aave": [_good()]}, root_key="protocol_history")
    sender = FakeSender()
    fired = monitor.alert_apy_feed_value_bounds(feed_path=str(feed), sender=sender)
    assert fired is False


def test_records_takes_precedence_over_feed(monitor, tmp_path):
    feed = tmp_path / "historical_apy.json"
    _write_feed(feed, {"aave": [_good(99999.0, 1e9)]})  # oob in file
    sender = FakeSender()
    fired = monitor.alert_apy_feed_value_bounds(
        records=_records(aave=[_good()]), feed_path=str(feed), sender=sender
    )
    assert fired is False


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))
