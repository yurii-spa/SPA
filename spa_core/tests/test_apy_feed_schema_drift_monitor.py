"""
Tests for SPA-V345: APY-feed schema-drift validation + alert.

Covers RiskMonitor.alert_apy_feed_schema_drift — the consecutive-drift streak
tracker that validates the STRUCTURE / KEYS / TYPES of historical_apy.json and
fires the moment the feed schema drifts (apy/tvl_usd arrive as strings instead
of numbers, a required field disappears, a history record stops being a dict, or
the per-protocol history stops being a list) — a blind spot none of the
aggregate or per-protocol monitors can see, because they all already assume a
well-formed schema.

Like the protocol-drop monitor, a schema drift alerts on the very first
drifted cycle (threshold 1). All tests run fully offline (FakeSender) with a
tmp_path-isolated data_dir — no network, no real data/ writes.
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
    APY_FEED_REQUIRED_FIELDS,
    APY_FEED_SCHEMA_MAX_BAD_PCT,
    APY_FEED_SCHEMA_MIN_PROTOCOLS,
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
    """A well-formed history record."""
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
    assert APY_FEED_REQUIRED_FIELDS == ("apy", "tvl_usd")
    assert 0 < APY_FEED_SCHEMA_MAX_BAD_PCT <= 1
    assert APY_FEED_SCHEMA_MIN_PROTOCOLS >= 1


# ---------------------------------------------------------------------------
# healthy cases — no alert
# ---------------------------------------------------------------------------

def test_healthy_schema_no_alert(monitor):
    recs = _records(
        aave=[_good(5.0, 1e9)],
        compound=[_good(4.0, 5e8)],
    )
    sender = FakeSender()
    fired = monitor.alert_apy_feed_schema_drift(records=recs, sender=sender)
    assert fired is False
    assert sender.messages == []


def test_healthy_with_numeric_string_ok(monitor):
    # numeric strings are accepted (coerced via float).
    recs = _records(aave=[{"apy": "5.0", "tvl_usd": "1000000000"}])
    sender = FakeSender()
    fired = monitor.alert_apy_feed_schema_drift(records=recs, sender=sender)
    assert fired is False
    assert sender.messages == []


def test_healthy_with_extra_known_fields_ok(monitor):
    recs = _records(aave=[_good(5.0, 1e9, timestamp="2026-05-30", chain="eth")])
    sender = FakeSender()
    fired = monitor.alert_apy_feed_schema_drift(records=recs, sender=sender)
    assert fired is False


def test_unexpected_fields_not_fatal(monitor):
    # Unexpected fields are recorded for context but never fatal on their own.
    recs = _records(aave=[_good(5.0, 1e9, weird_field=123, another="x")])
    sender = FakeSender()
    fired = monitor.alert_apy_feed_schema_drift(records=recs, sender=sender)
    assert fired is False
    assert sender.messages == []


def test_uses_last_record_only(monitor):
    # Only the LAST record is validated; earlier bad records are ignored.
    recs = _records(aave=[{"bogus": 1}, _good(5.0, 1e9)])
    sender = FakeSender()
    fired = monitor.alert_apy_feed_schema_drift(records=recs, sender=sender)
    assert fired is False


def test_empty_history_skipped_not_usable(monitor):
    # A protocol with empty history is not counted as usable. With one good
    # protocol alongside, schema stays healthy.
    recs = _records(empty=[], aave=[_good()])
    sender = FakeSender()
    fired = monitor.alert_apy_feed_schema_drift(records=recs, sender=sender)
    assert fired is False


# ---------------------------------------------------------------------------
# drift: missing required field
# ---------------------------------------------------------------------------

def test_missing_required_field_fires(monitor):
    recs = _records(aave=[{"apy": 5.0}])  # tvl_usd missing
    sender = FakeSender()
    fired = monitor.alert_apy_feed_schema_drift(records=recs, sender=sender)
    assert fired is True
    assert any("missing field" in m.lower() for m in sender.messages)


def test_missing_apy_field_fires(monitor):
    recs = _records(aave=[{"tvl_usd": 1e9}])  # apy missing
    sender = FakeSender()
    fired = monitor.alert_apy_feed_schema_drift(records=recs, sender=sender)
    assert fired is True
    assert any("missing field" in m.lower() for m in sender.messages)


# ---------------------------------------------------------------------------
# drift: bad type for required field
# ---------------------------------------------------------------------------

def test_bad_type_non_numeric_string_fires(monitor):
    recs = _records(aave=[{"apy": "n/a", "tvl_usd": 1e9}])
    sender = FakeSender()
    fired = monitor.alert_apy_feed_schema_drift(records=recs, sender=sender)
    assert fired is True
    assert any("bad type" in m.lower() for m in sender.messages)


def test_bad_type_none_fires(monitor):
    recs = _records(aave=[{"apy": None, "tvl_usd": 1e9}])
    sender = FakeSender()
    fired = monitor.alert_apy_feed_schema_drift(records=recs, sender=sender)
    assert fired is True
    assert any("bad type" in m.lower() for m in sender.messages)


def test_bad_type_bool_fires(monitor):
    # bool must be rejected even though isinstance(True, int) is True.
    recs = _records(aave=[{"apy": True, "tvl_usd": 1e9}])
    sender = FakeSender()
    fired = monitor.alert_apy_feed_schema_drift(records=recs, sender=sender)
    assert fired is True
    assert any("bad type" in m.lower() for m in sender.messages)


def test_bad_type_tvl_string_fires(monitor):
    recs = _records(aave=[{"apy": 5.0, "tvl_usd": "lots"}])
    sender = FakeSender()
    fired = monitor.alert_apy_feed_schema_drift(records=recs, sender=sender)
    assert fired is True
    assert any("bad type" in m.lower() for m in sender.messages)


# ---------------------------------------------------------------------------
# drift: non-dict record / history not list
# ---------------------------------------------------------------------------

def test_non_dict_record_fires(monitor):
    recs = _records(aave=["not-a-dict"])
    sender = FakeSender()
    fired = monitor.alert_apy_feed_schema_drift(records=recs, sender=sender)
    assert fired is True
    assert any("non-dict" in m.lower() for m in sender.messages)


def test_history_not_list_fires(monitor):
    recs = _records(aave={"apy": 5.0, "tvl_usd": 1e9})  # history is a dict, not list
    sender = FakeSender()
    fired = monitor.alert_apy_feed_schema_drift(records=recs, sender=sender)
    assert fired is True
    assert any("not list" in m.lower() for m in sender.messages)


# ---------------------------------------------------------------------------
# unreadable: empty / corrupt file
# ---------------------------------------------------------------------------

def test_missing_file_unreadable_fires(monitor, tmp_path):
    feed = tmp_path / "historical_apy.json"  # does not exist
    sender = FakeSender()
    fired = monitor.alert_apy_feed_schema_drift(feed_path=str(feed), sender=sender)
    assert fired is True
    assert any("unreadable" in m.lower() for m in sender.messages)


def test_corrupt_file_unreadable_fires(monitor, tmp_path):
    feed = tmp_path / "historical_apy.json"
    feed.write_text("{not valid json", encoding="utf-8")
    sender = FakeSender()
    fired = monitor.alert_apy_feed_schema_drift(feed_path=str(feed), sender=sender)
    assert fired is True
    assert any("unreadable" in m.lower() for m in sender.messages)


def test_no_protocols_key_unreadable_fires(monitor, tmp_path):
    feed = tmp_path / "historical_apy.json"
    feed.write_text(json.dumps({"generated_at": "2026-05-30"}), encoding="utf-8")
    sender = FakeSender()
    fired = monitor.alert_apy_feed_schema_drift(feed_path=str(feed), sender=sender)
    assert fired is True


def test_all_empty_histories_unreadable_fires(monitor):
    # No usable protocols at all → unreadable drift.
    recs = _records(a=[], b=[])
    sender = FakeSender()
    fired = monitor.alert_apy_feed_schema_drift(records=recs, sender=sender)
    assert fired is True


# ---------------------------------------------------------------------------
# bad-fraction threshold (< vs >=)
# ---------------------------------------------------------------------------

def test_bad_fraction_below_threshold_no_alert(monitor):
    # 1 of 3 bad = 33% < 50% → healthy (no alert).
    recs = _records(
        aave=[_good()],
        comp=[_good()],
        bad=[{"apy": "x", "tvl_usd": 1e9}],
    )
    sender = FakeSender()
    fired = monitor.alert_apy_feed_schema_drift(records=recs, sender=sender)
    assert fired is False
    assert sender.messages == []


def test_bad_fraction_at_threshold_fires(monitor):
    # 1 of 2 bad = 50% >= 50% → drift.
    recs = _records(
        aave=[_good()],
        bad=[{"apy": "x", "tvl_usd": 1e9}],
    )
    sender = FakeSender()
    fired = monitor.alert_apy_feed_schema_drift(records=recs, sender=sender)
    assert fired is True


def test_bad_fraction_above_threshold_fires(monitor):
    # 2 of 3 bad = 66% >= 50% → drift.
    recs = _records(
        aave=[_good()],
        bad1=[{"apy": "x", "tvl_usd": 1e9}],
        bad2=[{"tvl_usd": 1e9}],
    )
    sender = FakeSender()
    fired = monitor.alert_apy_feed_schema_drift(records=recs, sender=sender)
    assert fired is True


# ---------------------------------------------------------------------------
# streak / refire / reset
# ---------------------------------------------------------------------------

def test_streak_refire_then_reset(monitor):
    bad = _records(aave=[{"apy": "x", "tvl_usd": 1e9}])
    good = _records(aave=[_good()])
    sender = FakeSender()
    # first drift → fire
    f1 = monitor.alert_apy_feed_schema_drift(records=bad, sender=sender)
    assert f1 is True
    # second consecutive drift → refire
    f2 = monitor.alert_apy_feed_schema_drift(records=bad, sender=sender)
    assert f2 is True
    # healthy → reset, no fire
    f3 = monitor.alert_apy_feed_schema_drift(records=good, sender=sender)
    assert f3 is False
    # next healthy → still no fire
    f4 = monitor.alert_apy_feed_schema_drift(records=good, sender=sender)
    assert f4 is False
    assert len(sender.messages) == 2


def test_recovery_then_redrift_fires_again(monitor):
    bad = _records(aave=[{"apy": None, "tvl_usd": 1e9}])
    good = _records(aave=[_good()])
    sender = FakeSender()
    assert monitor.alert_apy_feed_schema_drift(records=bad, sender=sender) is True
    assert monitor.alert_apy_feed_schema_drift(records=good, sender=sender) is False
    # drift returns after a healthy cycle → fires again (streak restarted)
    assert monitor.alert_apy_feed_schema_drift(records=bad, sender=sender) is True


# ---------------------------------------------------------------------------
# persistent state
# ---------------------------------------------------------------------------

def test_persistent_state_roundtrip(monitor, tmp_path):
    bad = _records(aave=[{"apy": "x", "tvl_usd": 1e9}])
    sender = FakeSender()
    monitor.alert_apy_feed_schema_drift(records=bad, sender=sender)
    state_file = tmp_path / "apy_feed_schema_health_state.json"
    assert state_file.exists()
    data = json.loads(state_file.read_text())
    assert "prev_bad_keys" in data
    assert "consecutive_drifts" in data
    assert "last_alerted_cycle" in data
    assert "updated_at" in data
    assert data["consecutive_drifts"] == 1
    assert "aave" in data["prev_bad_keys"]


def test_state_survives_new_instance(monitor, tmp_path):
    bad = _records(aave=[{"apy": "x", "tvl_usd": 1e9}])
    sender = FakeSender()
    monitor.alert_apy_feed_schema_drift(records=bad, sender=sender)
    # new instance, same data_dir → streak continues, refires
    m2 = RiskMonitor(data_dir=tmp_path)
    s2 = FakeSender()
    fired = m2.alert_apy_feed_schema_drift(records=bad, sender=s2)
    assert fired is True


def test_corrupt_state_graceful(monitor, tmp_path):
    state_file = tmp_path / "apy_feed_schema_health_state.json"
    state_file.write_text("{garbage", encoding="utf-8")
    bad = _records(aave=[{"apy": "x", "tvl_usd": 1e9}])
    sender = FakeSender()
    # corrupt state → treated as fresh, still fires
    fired = monitor.alert_apy_feed_schema_drift(records=bad, sender=sender)
    assert fired is True


def test_healthy_state_written(monitor, tmp_path):
    good = _records(aave=[_good()])
    sender = FakeSender()
    monitor.alert_apy_feed_schema_drift(records=good, sender=sender)
    state_file = tmp_path / "apy_feed_schema_health_state.json"
    assert state_file.exists()
    data = json.loads(state_file.read_text())
    assert data["consecutive_drifts"] == 0


# ---------------------------------------------------------------------------
# never raises
# ---------------------------------------------------------------------------

def test_never_raises_on_bad_records_type(monitor):
    sender = FakeSender()
    # records of wrong type → falls through to unreadable, no crash
    fired = monitor.alert_apy_feed_schema_drift(records="not-a-dict", sender=sender)
    assert fired in (True, False)


def test_never_raises_no_args(monitor):
    sender = FakeSender()
    fired = monitor.alert_apy_feed_schema_drift(sender=sender)
    assert fired in (True, False)


def test_never_raises_records_with_weird_values(monitor):
    sender = FakeSender()
    recs = {"aave": [{"apy": [1, 2, 3], "tvl_usd": {"nested": 1}}]}
    fired = monitor.alert_apy_feed_schema_drift(records=recs, sender=sender)
    # list/dict values are non-numeric → drift, but must not raise
    assert fired in (True, False)


def test_no_sender_no_crash(monitor):
    # sender=None path: lazy TelegramSender import will fail offline → swallowed.
    bad = _records(aave=[{"apy": "x", "tvl_usd": 1e9}])
    fired = monitor.alert_apy_feed_schema_drift(records=bad)
    assert fired in (True, False)


# ---------------------------------------------------------------------------
# feed-file reading + protocol_history alias
# ---------------------------------------------------------------------------

def test_feed_file_healthy_read(monitor, tmp_path):
    feed = tmp_path / "historical_apy.json"
    _write_feed(feed, {"aave": [_good()]})
    sender = FakeSender()
    fired = monitor.alert_apy_feed_schema_drift(feed_path=str(feed), sender=sender)
    assert fired is False


def test_feed_file_drift_read(monitor, tmp_path):
    feed = tmp_path / "historical_apy.json"
    _write_feed(feed, {"aave": [{"apy": "bad", "tvl_usd": 1e9}]})
    sender = FakeSender()
    fired = monitor.alert_apy_feed_schema_drift(feed_path=str(feed), sender=sender)
    assert fired is True


def test_protocol_history_alias_key(monitor, tmp_path):
    feed = tmp_path / "historical_apy.json"
    _write_feed(feed, {"aave": [_good()]}, root_key="protocol_history")
    sender = FakeSender()
    fired = monitor.alert_apy_feed_schema_drift(feed_path=str(feed), sender=sender)
    assert fired is False


def test_records_takes_precedence_over_feed(monitor, tmp_path):
    # If both records and feed_path given, records wins (here records is good).
    feed = tmp_path / "historical_apy.json"
    _write_feed(feed, {"aave": [{"apy": "bad", "tvl_usd": 1e9}]})
    sender = FakeSender()
    fired = monitor.alert_apy_feed_schema_drift(
        records=_records(aave=[_good()]), feed_path=str(feed), sender=sender
    )
    assert fired is False
