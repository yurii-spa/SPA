"""Tests for the consolidated daily/weekly digests (spa_core/telegram/reports).

Covers:
  * the morning is TWO messages — a ≤900-char Russian headline, then the full
    details — and the demoted digest-queue items are folded into the details
    as a count + the most important bodies in words (no per-event spam);
    (аудит 08.09: до этого — ровно одно сообщение с гистограммой event_key)
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


# ── consolidation: the DETAILS message folds in the queued events ────────────
def test_daily_digest_consolidates_queue_into_the_details_message(tmp_path, sent_daily):
    # Seed the digest queue with several demoted events (incl. dups). Bodies are
    # what the owner now sees (аудит 08.09: 15 of 62 bodies carried CRITICAL while
    # the section listed only event_keys), so the fixture carries real bodies.
    for key, body in [
        ("dashboard_watch", "🖥️ <b>Dashboard Alert</b>\n━━━━\n🔴 System health CRITICAL (overall)\n\n📊 Portfolio: $1"),
        ("dashboard_watch", "🖥️ <b>Dashboard Alert</b>\n━━━━\n🔴 System health CRITICAL (overall)\n\n📊 Portfolio: $1"),
        ("apy_spike", "compound_v3 9.20% > 8.00%"),
        ("tournament", "🏆 <b>SPA Tournament</b>\n\nDaily standings"),
    ]:
        push_policy.enqueue_digest(key, key, body, data_dir=str(tmp_path))

    res = daily_digest.run_daily_digest(
        "2026-06-15", data_dir=str(tmp_path), send=True, now=_dt()
    )
    assert res["sent"] is True
    # Changed 08.09 (inv. #16, reason): the morning is now headline + details —
    # EXACTLY two messages, in that order; the queue section lives in the details.
    assert len(sent_daily) == 2
    assert "Подробности — следующим сообщением" in sent_daily[0]
    msg = sent_daily[1]
    # The section counts events + CRITICAL bodies and names the bodies in WORDS
    # (CRITICAL first, identical bodies collapsed ×N) — not the event_key histogram.
    assert "События за сутки" in msg
    assert "событий с прошлого отчёта: 4, из них с CRITICAL: 2" in msg
    assert "System health CRITICAL (overall) ×2" in msg
    assert "compound_v3 9.20% &gt; 8.00%" in msg  # body text is HTML-escaped (parse_mode=HTML)
    assert "dashboard_watch" not in msg  # internal key is not what the owner reads
    # Queue drained after a real send.
    assert push_policy.drain_digest_queue(data_dir=str(tmp_path), clear=False) == []


def test_digest_section_keeps_the_histogram_when_bodies_are_too_few(tmp_path):
    """Fewer than 3 bodies ⇒ the event_key histogram is all that is known — keep it."""
    for key in ["dashboard_watch", "dashboard_watch", "apy_spike"]:
        push_policy.enqueue_digest(key, key, "", data_dir=str(tmp_path))
    msg, _ = daily_digest.build_digest_message(
        "2026-06-15", data_dir=str(tmp_path), drain=False
    )
    assert "dashboard_watch ×2" in msg and "apy_spike" in msg


def test_daily_digest_idempotent_per_utc_date(tmp_path, sent_daily):
    first = daily_digest.run_daily_digest(
        "2026-06-15", data_dir=str(tmp_path), send=True, now=_dt()
    )
    assert first["sent"] is True
    assert len(sent_daily) == 2  # 08.09: headline + details (was 1 — one message)
    # Second fire same day → SKIPPED (no double send).
    second = daily_digest.run_daily_digest(
        "2026-06-15", data_dir=str(tmp_path), send=True, now=_dt(h=8, m=12)
    )
    assert second["skipped"] is True
    assert second["sent"] is False
    assert len(sent_daily) == 2  # still the one pair


def test_daily_digest_force_overrides_guard(tmp_path, sent_daily):
    daily_digest.run_daily_digest("2026-06-15", data_dir=str(tmp_path), send=True, now=_dt())
    daily_digest.run_daily_digest(
        "2026-06-15", data_dir=str(tmp_path), send=True, force=True, now=_dt()
    )
    assert len(sent_daily) == 4  # 08.09: two pairs (was 2 — two single messages)


def test_daily_check_does_not_drain_queue(tmp_path):
    push_policy.enqueue_digest("apy_spike", "x", "y", data_dir=str(tmp_path))
    msg, _ = daily_digest.build_digest_message(
        "2026-06-15", data_dir=str(tmp_path), drain=False
    )
    assert "События за сутки" in msg  # 08.09: section header is Russian now
    # NOT drained.
    assert push_policy.drain_digest_queue(data_dir=str(tmp_path), clear=False)


def test_daily_digest_no_queue_still_the_pair(tmp_path, sent_daily):
    res = daily_digest.run_daily_digest(
        "2026-06-15", data_dir=str(tmp_path), send=True, now=_dt()
    )
    assert res["sent"] is True
    assert len(sent_daily) == 2  # 08.09: headline + details, nothing more
    assert "События за сутки" not in sent_daily[1]  # no section when nothing queued


def test_daily_digest_never_raises_on_corrupt_data(tmp_path, sent_daily):
    (tmp_path / "equity_curve_daily.json").write_text("{ not json")
    res = daily_digest.run_daily_digest(
        "2026-06-15", data_dir=str(tmp_path), send=True, now=_dt()
    )
    # Degrades, still emits the pair, never raises.
    assert res["error"] is None or res["sent"] is True
    assert len(sent_daily) == 2  # 08.09: headline + details


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


# ── go-live regression: digest writes telegram_alert_state (GAP 2) ───────────
def test_daily_digest_writes_telegram_alert_state(tmp_path, sent_daily):
    """A successful daily digest must record daily_summary=today in
    telegram_alert_state.json so GoLive's telegram_alert_today can pass — the
    retired legacy daily-report agents used to own that write."""
    import json

    state = tmp_path / "telegram_alert_state.json"
    # Pre-seed other keys to prove they survive the partial update.
    state.write_text(json.dumps(
        {"daily_summary": "2026-06-01", "red_flag": "2026-06-14",
         "weekly_report": "2026-06-08"}
    ))

    res = daily_digest.run_daily_digest(
        "2026-06-15", data_dir=str(tmp_path), send=True, now=_dt()
    )
    assert res["sent"] is True

    doc = json.loads(state.read_text())
    assert doc["daily_summary"] == "2026-06-15"           # set to today (UTC)
    assert doc["red_flag"] == "2026-06-14"                # preserved
    assert doc["weekly_report"] == "2026-06-08"           # preserved

    # And the go-live criterion now passes against that state.
    from spa_core.paper_trading.golive_checker import GoLiveChecker

    gc = GoLiveChecker(data_dir=tmp_path, now=_dt())
    blockers: list[str] = []
    assert gc._check_telegram_alert_today(blockers) is True
    assert blockers == []


def test_daily_digest_failed_send_leaves_alert_state_untouched(tmp_path, monkeypatch):
    """An UNSUCCESSFUL send must NOT mark daily_summary — honest, not force-pass."""
    import json

    monkeypatch.setattr(daily_digest, "_send_html", lambda msg: False)
    state = tmp_path / "telegram_alert_state.json"
    state.write_text(json.dumps({"daily_summary": "2026-06-01"}))

    res = daily_digest.run_daily_digest(
        "2026-06-15", data_dir=str(tmp_path), send=True, now=_dt()
    )
    assert res["sent"] is False
    assert json.loads(state.read_text())["daily_summary"] == "2026-06-01"
