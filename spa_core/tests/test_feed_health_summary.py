"""
Offline tests for SPA-V347 aggregated feed-health summary
(spa_core/alerts/feed_health_summary.py).

No network, no real state files — everything is driven by tmp_path fixtures.
"""
import json
from datetime import datetime, timedelta, timezone

import pytest

from alerts import feed_health_summary as fhs


# --------------------------------------------------------------------------
# helpers
# --------------------------------------------------------------------------

def _write_state(data_dir, filename, **fields):
    (data_dir / filename).write_text(json.dumps(fields), encoding="utf-8")


def _filename(key):
    for k, fn, *_ in fhs.SIGNALS:
        if k == key:
            return fn
    raise KeyError(key)


# --------------------------------------------------------------------------
# classify_streak
# --------------------------------------------------------------------------

def test_classify_zero_is_ok():
    assert fhs.classify_streak(0, 3) == "ok"


def test_classify_below_threshold_is_warn():
    assert fhs.classify_streak(1, 3) == "warn"
    assert fhs.classify_streak(2, 3) == "warn"


def test_classify_at_threshold_is_degraded():
    assert fhs.classify_streak(3, 3) == "degraded"
    assert fhs.classify_streak(9, 3) == "degraded"


def test_classify_threshold_one_warn_never_happens():
    # threshold 1 -> any positive streak is immediately degraded.
    assert fhs.classify_streak(1, 1) == "degraded"


def test_classify_bad_input_is_unknown():
    assert fhs.classify_streak("x", 3) == "unknown"
    assert fhs.classify_streak(None, 3) == "unknown"


# --------------------------------------------------------------------------
# registry sanity
# --------------------------------------------------------------------------

def test_eight_signals_registered():
    assert len(fhs.SIGNALS) == 9
    keys = {k for k, *_ in fhs.SIGNALS}
    assert keys == {
        "covariance", "apy_feed_stale", "protocol_drop", "tvl_drop",
        "protocol_anomaly", "schema_drift", "protocol_stale", "value_bounds",
        "date_monotonicity",
    }


def test_thresholds_match_monitors():
    th = {k: t for k, _f, _l, _s, t in fhs.SIGNALS}
    assert th["covariance"] == 3
    assert th["apy_feed_stale"] == 2
    assert th["protocol_drop"] == 1
    assert th["tvl_drop"] == 1
    assert th["protocol_anomaly"] == 1
    assert th["schema_drift"] == 1
    assert th["protocol_stale"] == 1
    assert th["value_bounds"] == 1
    assert th["date_monotonicity"] == 1


# --------------------------------------------------------------------------
# evaluate_signal / collect_feed_health
# --------------------------------------------------------------------------

def test_missing_state_is_ok(tmp_path):
    rec = fhs.evaluate_signal(
        tmp_path, "covariance", _filename("covariance"),
        "Covariance source", "consecutive_degraded", 3,
    )
    assert rec["status"] == "ok"
    assert rec["present"] is False
    assert rec["streak"] == 0


def test_all_missing_overall_ok(tmp_path):
    doc = fhs.build_summary_document(tmp_path)
    assert doc["overall_status"] == "ok"
    assert doc["signal_count"] == 9
    assert doc["counts"]["ok"] == 9


def test_degraded_signal_drives_overall(tmp_path):
    _write_state(tmp_path, _filename("covariance"),
                 consecutive_degraded=3, last_alerted_cycle=3,
                 updated_at="2026-05-30T00:00:00Z")
    doc = fhs.build_summary_document(tmp_path)
    assert doc["overall_status"] == "degraded"
    cov = next(s for s in doc["signals"] if s["key"] == "covariance")
    assert cov["status"] == "degraded"
    assert cov["streak"] == 3
    assert cov["present"] is True
    assert cov["last_alerted_cycle"] == 3


def test_warn_signal_drives_overall_when_no_degraded(tmp_path):
    # covariance threshold 3, streak 1 -> warn (not degraded).
    _write_state(tmp_path, _filename("covariance"), consecutive_degraded=1)
    doc = fhs.build_summary_document(tmp_path)
    assert doc["overall_status"] == "warn"


def test_worst_of_wins(tmp_path):
    # one warn + one degraded -> overall degraded.
    _write_state(tmp_path, _filename("covariance"), consecutive_degraded=1)  # warn
    _write_state(tmp_path, _filename("schema_drift"), consecutive_drifts=1)  # degraded
    doc = fhs.build_summary_document(tmp_path)
    assert doc["overall_status"] == "degraded"
    assert doc["counts"]["warn"] == 1
    assert doc["counts"]["degraded"] == 1


def test_corrupt_state_is_unknown(tmp_path):
    (tmp_path / _filename("apy_feed_stale")).write_text("{not json", encoding="utf-8")
    doc = fhs.build_summary_document(tmp_path)
    stale = next(s for s in doc["signals"] if s["key"] == "apy_feed_stale")
    assert stale["status"] == "unknown"
    # unknown ranks above ok -> overall unknown (no warn/degraded present).
    assert doc["overall_status"] == "unknown"


def test_non_dict_state_is_unknown(tmp_path):
    (tmp_path / _filename("tvl_drop")).write_text("[1,2,3]", encoding="utf-8")
    rec = fhs.evaluate_signal(
        tmp_path, "tvl_drop", _filename("tvl_drop"),
        "TVL drop", "consecutive_drops", 1,
    )
    assert rec["status"] == "unknown"


def test_each_streak_field_read(tmp_path):
    # Verify each signal uses its own streak field name.
    _write_state(tmp_path, _filename("apy_feed_stale"), consecutive_stale=2)
    _write_state(tmp_path, _filename("protocol_drop"), consecutive_drops=1)
    _write_state(tmp_path, _filename("protocol_anomaly"), consecutive_anomalies=1)
    _write_state(tmp_path, _filename("schema_drift"), consecutive_drifts=1)
    _write_state(tmp_path, _filename("protocol_stale"), consecutive_stale=1)
    doc = fhs.build_summary_document(tmp_path)
    by = {s["key"]: s for s in doc["signals"]}
    assert by["apy_feed_stale"]["status"] == "degraded"   # 2 >= 2
    assert by["protocol_drop"]["status"] == "degraded"     # 1 >= 1
    assert by["protocol_anomaly"]["status"] == "degraded"
    assert by["schema_drift"]["status"] == "degraded"
    assert by["protocol_stale"]["status"] == "degraded"


# --------------------------------------------------------------------------
# write / serialisation / CLI
# --------------------------------------------------------------------------

def test_write_creates_file_and_returns_doc(tmp_path):
    out = tmp_path / "feed_health_summary.json"
    doc = fhs.write_feed_health_summary(str(out), data_dir=tmp_path)
    assert out.exists()
    loaded = json.loads(out.read_text(encoding="utf-8"))
    assert loaded == doc
    assert loaded["schema_version"] == fhs.SCHEMA_VERSION


def test_write_default_path(tmp_path):
    doc = fhs.write_feed_health_summary(data_dir=tmp_path)
    assert (tmp_path / "feed_health_summary.json").exists()
    assert doc["overall_status"] == "ok"


def test_document_is_json_serialisable(tmp_path):
    _write_state(tmp_path, _filename("covariance"), consecutive_degraded=5)
    doc = fhs.build_summary_document(tmp_path)
    json.dumps(doc)  # must not raise


def test_generated_at_is_iso_z(tmp_path):
    doc = fhs.build_summary_document(tmp_path)
    assert doc["generated_at"].endswith("Z")


def test_cli_json_round_trip(tmp_path, capsys):
    rc = fhs._cli(["--data-dir", str(tmp_path), "--json"])
    assert rc == 0
    out = capsys.readouterr().out
    doc = json.loads(out)
    assert doc["signal_count"] == 9


def test_cli_write(tmp_path):
    out = tmp_path / "summary.json"
    rc = fhs._cli(["--data-dir", str(tmp_path), "--write", str(out)])
    assert rc == 0
    assert out.exists()


def test_never_raises_on_unreadable_dir():
    # Pointing at a path that is a file, not a dir, must not raise.
    doc = fhs.build_summary_document("/nonexistent/path/xyz")
    assert doc["overall_status"] == "ok"  # all missing -> ok


# --------------------------------------------------------------------------
# SPA-V359: last_alert_age_hours (per-signal updated_at age)
# --------------------------------------------------------------------------

class TestLastAlertAgeHours:
    def test_age_computed_from_recent_updated_at(self, tmp_path):
        five_h_ago = (
            datetime.now(timezone.utc) - timedelta(hours=5)
        ).isoformat().replace("+00:00", "Z")
        _write_state(tmp_path, _filename("covariance"),
                     consecutive_degraded=3, last_alerted_cycle=3,
                     updated_at=five_h_ago)
        rec = fhs.evaluate_signal(
            tmp_path, "covariance", _filename("covariance"),
            "Covariance source", "consecutive_degraded", 3,
        )
        assert rec["last_alert_age_hours"] is not None
        assert rec["last_alert_age_hours"] == pytest.approx(5.0, abs=0.2)

    def test_age_none_when_no_updated_at(self, tmp_path):
        _write_state(tmp_path, _filename("covariance"), consecutive_degraded=3)
        rec = fhs.evaluate_signal(
            tmp_path, "covariance", _filename("covariance"),
            "Covariance source", "consecutive_degraded", 3,
        )
        assert rec["last_alert_age_hours"] is None

    def test_age_none_on_garbage_updated_at_and_other_fields_intact(self, tmp_path):
        _write_state(tmp_path, _filename("covariance"),
                     consecutive_degraded=3, last_alerted_cycle=7,
                     updated_at="not-a-date")
        # must not raise
        rec = fhs.evaluate_signal(
            tmp_path, "covariance", _filename("covariance"),
            "Covariance source", "consecutive_degraded", 3,
        )
        assert rec["last_alert_age_hours"] is None
        # other fields stay correct despite the bad timestamp
        assert rec["status"] == "degraded"
        assert rec["streak"] == 3
        assert rec["present"] is True
        assert rec["last_alerted_cycle"] == 7
        assert rec["updated_at"] == "not-a-date"

    def test_missing_state_has_age_key_none(self, tmp_path):
        rec = fhs.evaluate_signal(
            tmp_path, "covariance", _filename("covariance"),
            "Covariance source", "consecutive_degraded", 3,
        )
        assert "last_alert_age_hours" in rec
        assert rec["last_alert_age_hours"] is None

    def test_age_key_present_in_every_summary_signal(self, tmp_path):
        doc = fhs.build_summary_document(tmp_path)
        assert len(doc["signals"]) == 9
        for s in doc["signals"]:
            assert "last_alert_age_hours" in s

    def test_age_hours_helper_handles_naive_and_z(self):
        naive = (datetime.now(timezone.utc) - timedelta(hours=2)).replace(
            tzinfo=None
        ).isoformat()
        assert fhs._age_hours(naive) == pytest.approx(2.0, abs=0.2)
        z = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat().replace(
            "+00:00", "Z"
        )
        assert fhs._age_hours(z) == pytest.approx(1.0, abs=0.2)
        assert fhs._age_hours(None) is None
        assert fhs._age_hours("not-a-date") is None


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))
