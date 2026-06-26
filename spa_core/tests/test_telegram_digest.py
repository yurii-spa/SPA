"""Tests for the consolidated daily/weekly digests (spa_core/telegram/reports).

Covers:
  * ONE daily message consolidates the day + the demoted digest-queue items
    (no per-event spam — counts by event_key);
  * the date-stamp idempotency guard refuses a second send for the same UTC date;
  * drain_digest_queue empties the queue once consumed;
  * weekly idempotency per ISO week.

Transport mocked — nothing is sent to Telegram.
"""
from __future__ import annotations

from datetime import datetime, timezone

import pytest

from spa_core.telegram import push_policy
from spa_core.telegram.reports import daily as daily_digest
from spa_core.telegram.reports import weekly as weekly_digest


@pytest.fixture
def sent_daily(monkeypatch):
    captured: list[str] = []
    monkeypatch.setattr(daily_digest, "_send_html",
                        lambda msg: (captured.append(msg) or True))
    return captured


@pytest.fixture
def sent_weekly(monkeypatch):
    captured: list[str] = []
    monkeypatch.setattr(weekly_digest, "_send_html",
                        lambda msg: (captured.append(msg) or True))
    return captured


def _dt(day=15, h=8, m=10):
    return datetime(2026, 6, day, h, m, tzinfo=timezone.utc)


# ── consolidation: ONE message folds in the queued events ────────────────────
def test_daily_digest_consolidates_queue_into_one_message(tmp_path, sent_daily):
    # Seed the digest queue with several demoted events (incl. dups).
    for key in ["dashboard_watch", "dashboard_watch", "apy_spike", "tournament"]:
        push_policy.enqueue_digest(key, key, "body", data_dir=str(tmp_path))

    res = daily_digest.run_daily_digest(
        "2026-06-15", data_dir=str(tmp_path), send=True, now=_dt()
    )
    assert res["sent"] is True
    assert len(sent_daily) == 1  # EXACTLY one message
    msg = sent_daily[0]
    # The digest section summarises by event_key with counts (no N separate msgs).
    assert "Today's digest" in msg
    assert "dashboard_watch" in msg and "×2" in msg
    assert "4 non-critical event" in msg
    # Queue drained after a real send.
    assert push_policy.drain_digest_queue(data_dir=str(tmp_path), clear=False) == []


def test_daily_digest_idempotent_per_utc_date(tmp_path, sent_daily):
    first = daily_digest.run_daily_digest(
        "2026-06-15", data_dir=str(tmp_path), send=True, now=_dt()
    )
    assert first["sent"] is True
    assert len(sent_daily) == 1
    # Second fire same day → SKIPPED (no double send).
    second = daily_digest.run_daily_digest(
        "2026-06-15", data_dir=str(tmp_path), send=True, now=_dt(h=8, m=12)
    )
    assert second["skipped"] is True
    assert second["sent"] is False
    assert len(sent_daily) == 1  # still one


def test_daily_digest_force_overrides_guard(tmp_path, sent_daily):
    daily_digest.run_daily_digest("2026-06-15", data_dir=str(tmp_path), send=True, now=_dt())
    daily_digest.run_daily_digest(
        "2026-06-15", data_dir=str(tmp_path), send=True, force=True, now=_dt()
    )
    assert len(sent_daily) == 2


def test_daily_check_does_not_drain_queue(tmp_path):
    push_policy.enqueue_digest("apy_spike", "x", "y", data_dir=str(tmp_path))
    msg, _ = daily_digest.build_digest_message(
        "2026-06-15", data_dir=str(tmp_path), drain=False
    )
    assert "Today's digest" in msg
    # NOT drained.
    assert push_policy.drain_digest_queue(data_dir=str(tmp_path), clear=False)


def test_daily_digest_no_queue_still_one_message(tmp_path, sent_daily):
    res = daily_digest.run_daily_digest(
        "2026-06-15", data_dir=str(tmp_path), send=True, now=_dt()
    )
    assert res["sent"] is True
    assert len(sent_daily) == 1
    assert "Today's digest" not in sent_daily[0]  # no section when nothing queued


def test_daily_digest_never_raises_on_corrupt_data(tmp_path, sent_daily):
    (tmp_path / "equity_curve_daily.json").write_text("{ not json")
    res = daily_digest.run_daily_digest(
        "2026-06-15", data_dir=str(tmp_path), send=True, now=_dt()
    )
    # Degrades, still emits one message, never raises.
    assert res["error"] is None or res["sent"] is True
    assert len(sent_daily) == 1


# ── weekly ───────────────────────────────────────────────────────────────────
def test_weekly_digest_sends_one_and_is_idempotent(tmp_path, sent_weekly):
    first = weekly_digest.run_weekly_digest(
        "2026-06-21", data_dir=str(tmp_path), send=True, now=_dt(day=21, h=10)
    )
    assert first["sent"] is True
    assert len(sent_weekly) == 1
    # Same ISO week → skip.
    second = weekly_digest.run_weekly_digest(
        "2026-06-21", data_dir=str(tmp_path), send=True, now=_dt(day=21, h=11)
    )
    assert second["skipped"] is True
    assert len(sent_weekly) == 1
