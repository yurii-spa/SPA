"""Tests for the track-accrual freshness gate (P4-2).

Covers the shared deterministic, fail-CLOSED gate
(:mod:`spa_core.paper_trading.track_freshness`) used by both the live health
endpoint and the agent-health monitor:

  * fresh evidenced bar within SLA → ok
  * stale evidenced bar (frozen clock) → degraded + age reported
  * last_cycle_ts fallback when no evidenced bar
  * fail-CLOSED: unreadable / empty / missing track → degraded, never ok
  * non-evidenced (backfill/reconstructed/warmup) bars do not make a stale
    track look fresh
"""
from __future__ import annotations

import json
from datetime import datetime, timezone

from spa_core.paper_trading import track_freshness as tf

NOW = datetime(2026, 6, 26, 12, 0, 0, tzinfo=timezone.utc)


def _bar(date, evidenced=True, **extra):
    b = {"date": date, "close_equity": 100000.0, "open_equity": 100000.0}
    b.update(extra)
    # An explicit honesty label drives is_evidenced_bar; leave unset for legacy.
    if evidenced is not None:
        b["evidenced"] = evidenced
        b["source"] = "cycle" if evidenced else "backfill"
    return b


# ─── assess_track_freshness (no I/O) ───────────────────────────────────────────

def test_fresh_within_sla_is_ok():
    equity = {"daily": [_bar("2026-06-25"), _bar("2026-06-26")]}
    r = tf.assess_track_freshness(equity, {}, now=NOW)
    assert r["track_fresh"] is True
    assert r["status"] == "ok"
    assert r["age_hours"] is not None and r["age_hours"] <= tf.SLA_HOURS
    assert r["last_evidenced_date"] == "2026-06-26"


def test_stale_evidenced_bar_is_degraded():
    # newest evidenced bar is 2026-06-24 → 60h old at NOW (>30h SLA)
    equity = {"daily": [_bar("2026-06-23"), _bar("2026-06-24")]}
    r = tf.assess_track_freshness(equity, {}, now=NOW)
    assert r["track_fresh"] is False
    assert r["status"] == "degraded"
    assert r["age_hours"] > tf.SLA_HOURS
    assert "SLA" in r["reason"]


def test_non_evidenced_bars_do_not_freshen():
    # a fresh-dated but NON-evidenced (backfill) bar must not count; the newest
    # evidenced bar is the old one → degraded.
    equity = {
        "daily": [
            _bar("2026-06-23", evidenced=True),
            _bar("2026-06-26", evidenced=False),  # backfill, fresh date but excluded
        ]
    }
    r = tf.assess_track_freshness(equity, {}, now=NOW)
    assert r["last_evidenced_date"] == "2026-06-23"
    assert r["track_fresh"] is False


def test_last_cycle_ts_fallback_when_no_evidenced_bar():
    status = {"last_cycle_ts": "2026-06-26T06:00:00+00:00"}
    r = tf.assess_track_freshness({"daily": []}, status, now=NOW)
    assert r["track_fresh"] is True
    assert r["status"] == "ok"
    assert r["last_cycle_ts"] == "2026-06-26T06:00:00+00:00"


def test_stale_last_cycle_ts_fallback_degraded():
    status = {"last_cycle_ts": "2026-06-23T06:00:00+00:00"}  # ~78h old
    r = tf.assess_track_freshness({"daily": []}, status, now=NOW)
    assert r["track_fresh"] is False
    assert r["status"] == "degraded"


# ─── fail-CLOSED ───────────────────────────────────────────────────────────────

def test_fail_closed_no_inputs():
    r = tf.assess_track_freshness(None, None, now=NOW)
    assert r["track_fresh"] is False
    assert r["status"] == "degraded"
    assert r["age_hours"] is None


def test_fail_closed_empty_daily_no_status():
    r = tf.assess_track_freshness({"daily": []}, {}, now=NOW)
    assert r["track_fresh"] is False
    assert r["status"] == "degraded"


def test_fail_closed_unparseable_timestamp():
    equity = {"daily": [_bar("not-a-date")]}
    r = tf.assess_track_freshness(equity, {}, now=NOW)
    assert r["track_fresh"] is False
    assert r["status"] == "degraded"


# ─── filesystem entry point ────────────────────────────────────────────────────

def test_check_track_freshness_reads_files(tmp_path):
    (tmp_path / "equity_curve_daily.json").write_text(
        json.dumps({"daily": [_bar("2026-06-26")]}), encoding="utf-8"
    )
    r = tf.check_track_freshness(tmp_path, now=NOW)
    assert r["track_fresh"] is True
    assert r["status"] == "ok"


def test_check_track_freshness_missing_dir_fail_closed(tmp_path):
    r = tf.check_track_freshness(tmp_path / "nope", now=NOW)
    assert r["track_fresh"] is False
    assert r["status"] == "degraded"


def test_check_track_freshness_corrupt_file_fail_closed(tmp_path):
    (tmp_path / "equity_curve_daily.json").write_text("{broken", encoding="utf-8")
    r = tf.check_track_freshness(tmp_path, now=NOW)
    assert r["track_fresh"] is False
    assert r["status"] == "degraded"
