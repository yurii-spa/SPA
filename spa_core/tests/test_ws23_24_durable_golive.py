#!/usr/bin/env python3
"""WS-2.3 / WS-2.4 — durable go-live gate + evidenced risk + miss-guard.

Property / red-team / smoke tests for the "Yield Capture" 2.3+2.4 sprint:

  * 2.4 golive re-derive — folding GoLiveChecker into the 5-min cycle_gap_monitor
    re-derives golive_status.json on the SHORT cadence (not next-day); a STALE
    snapshot is replaced by the LIVE count.
  * 2.4 telegram miss-guard — a silently missed digest day is made VISIBLE
    (logged + flagged in telegram_alert_state.json), never a fabricated send.
  * 2.4 telegram_alert_today — reflects reality (sent today, or yesterday-sent
    pre-digest grace), and a missed day is not permanently penalized.
  * 2.3 evidenced Sharpe/Sortino — computed on the evidenced curve, THIN (None)
    below the minimum evidenced points (no degenerate small-sample Sharpe).
  * 2.3 kill-switch parity — the Sharpe trigger reads the EVIDENCED series.
  * fail-closed invariant — a corrupted/partial golive result can NEVER serialize
    ready=True; gap-monitor day-count is monotone under dup/future/out-of-order.

Stdlib + pytest only. Deterministic.
"""
from __future__ import annotations

import json
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import pytest

from spa_core.paper_trading import track_evidence as te
from spa_core.paper_trading.golive_checker import GoLiveChecker, GoLiveResult
from spa_core.paper_trading.cycle_gap_monitor import rederive_golive_status
from spa_core.governance.kill_switch import KillSwitchChecker
from spa_core.telegram.reports import daily as digest

ANCHOR = te.PAPER_REAL_START  # date(2026, 6, 10)


# ── helpers ──────────────────────────────────────────────────────────────────


def _evidenced_daily(n: int, start_equity: float = 100_000.0,
                     daily_ret: float = 0.0001) -> list[dict]:
    """n evidenced (unlabeled, post-anchor) bars with a small steady return."""
    bars = []
    eq = start_equity
    for i in range(n):
        bars.append({
            "date": (ANCHOR + timedelta(days=i)).isoformat(),
            "open_equity": round(eq, 6),
            "close_equity": round(eq * (1 + daily_ret), 6),
            "equity": round(eq * (1 + daily_ret), 6),
        })
        eq *= (1 + daily_ret)
    return bars


def _write(ddir: Path, name: str, obj) -> None:
    (ddir / name).write_text(json.dumps(obj, indent=2), encoding="utf-8")


# ══════════════════════════════════════════════════════════════════════════════
# 2.3 — evidenced Sharpe / Sortino, THIN below N (no degenerate)
# ══════════════════════════════════════════════════════════════════════════════


def test_evidenced_sharpe_thin_below_minimum():
    """Fewer than MIN_EVIDENCED_RETURNS evidenced returns → None (THIN), not degen."""
    daily = _evidenced_daily(5)  # 4 returns ≪ minimum
    assert te.real_sharpe_ratio(daily) is None
    assert te.real_sortino_ratio(daily) is None
    rm = te.evidenced_risk_metrics(daily)
    assert rm["status"] == "THIN"
    assert rm["sharpe"] is None and rm["sortino"] is None


def test_evidenced_sharpe_ok_above_minimum():
    """With enough evidenced returns the Sharpe is a finite number, status OK."""
    daily = _evidenced_daily(te.MIN_EVIDENCED_RETURNS_FOR_SHARPE + 5)
    s = te.real_sharpe_ratio(daily)
    assert s is not None and isinstance(s, float)
    rm = te.evidenced_risk_metrics(daily)
    assert rm["status"] == "OK"
    assert rm["n_returns"] >= te.MIN_EVIDENCED_RETURNS_FOR_SHARPE


def test_evidenced_sharpe_ignores_pre_anchor_and_backfill():
    """Warmup/backfill bars never enter the evidenced returns series."""
    warmup = [{"date": (ANCHOR - timedelta(days=3)).isoformat(),
               "close_equity": 5_000_000.0, "is_warmup": True}]
    backfill = [{"date": (ANCHOR + timedelta(days=i)).isoformat(),
                 "close_equity": 100_000.0, "evidenced": False,
                 "source": "backfill"} for i in range(40)]
    real = _evidenced_daily(te.MIN_EVIDENCED_RETURNS_FOR_SHARPE + 2)
    mixed = warmup + backfill + real
    # The evidenced returns must equal the real-only returns (no contamination).
    assert te.evidenced_daily_returns(mixed) == te.evidenced_daily_returns(real)


def test_kill_switch_sharpe_reads_evidenced_series(tmp_path):
    """The Sharpe trigger reads the EVIDENCED equity curve, fail-closed when THIN."""
    # THIN evidenced series → no kill (parity with drawdown fail-closed).
    _write(tmp_path, "equity_curve_daily.json",
           {"daily": _evidenced_daily(4), "is_demo": False})
    checker = KillSwitchChecker(data_dir=tmp_path)
    triggered, reason = checker.check_sharpe_trigger()
    assert triggered is False
    assert "thin" in reason.lower() or "insufficient" in reason.lower()


def test_kill_switch_sharpe_ignores_nonevidenced_analytics(tmp_path):
    """A toxic analytics_summary.json must NOT drive the kill — only evidenced data."""
    # Plant a catastrophic non-evidenced Sharpe; provide NO evidenced curve.
    _write(tmp_path, "analytics_summary.json",
           {"num_days": 90, "metrics": {"sharpe": -99.0}})
    checker = KillSwitchChecker(data_dir=tmp_path)
    triggered, reason = checker.check_sharpe_trigger()
    assert triggered is False  # no evidenced curve → fail-closed, analytics ignored


# ══════════════════════════════════════════════════════════════════════════════
# 2.4 — golive re-derive on the short cadence (stale → live)
# ══════════════════════════════════════════════════════════════════════════════


def test_rederive_replaces_stale_golive_snapshot(tmp_path):
    """A STALE golive_status.json is recomputed to the LIVE passed-count."""
    now = datetime(2026, 6, 28, 15, 0, tzinfo=timezone.utc)
    # Seed a stale snapshot with a deliberately wrong low count.
    _write(tmp_path, "golive_status.json",
           {"ready": False, "passed": 25, "total": 29, "timestamp": "2026-06-28T06:00:00+00:00"})
    # Provide the real inputs so the live recompute differs from the stale 25.
    live = rederive_golive_status(tmp_path, now=now)
    assert live is not None
    on_disk = json.loads((tmp_path / "golive_status.json").read_text())
    # Re-derived value matches a fresh GoLiveChecker run (the LIVE count), not 25.
    fresh = GoLiveChecker(data_dir=tmp_path, now=now).check(write=False)
    assert on_disk["passed"] == sum(fresh.checks.values())
    assert on_disk["timestamp"].startswith("2026-06-28T15")  # uses the live clock


def test_rederive_failsafe_never_raises(tmp_path, monkeypatch):
    """A failure inside the recompute is swallowed (monitor must never crash)."""
    import spa_core.paper_trading.cycle_gap_monitor as cgm

    class _Boom:
        def __init__(self, *a, **k):
            raise RuntimeError("boom")

    monkeypatch.setattr(
        "spa_core.paper_trading.golive_checker.GoLiveChecker", _Boom
    )
    # Must return None, not raise.
    assert cgm.rederive_golive_status(tmp_path) is None


# ══════════════════════════════════════════════════════════════════════════════
# 2.4 — fail-closed go-live-gate invariant
# ══════════════════════════════════════════════════════════════════════════════


def test_corrupted_ready_true_can_never_serialize_true():
    """A result object with ready=True but a failing check serializes ready=False."""
    bad = GoLiveResult(
        ready=True,  # corrupted / out-of-band flip
        checks={"a": True, "b": False, "c": True},  # b fails
    )
    assert bad.to_dict()["ready"] is False


def test_all_pass_serializes_ready_true():
    """Sanity: when every check passes, ready serializes True."""
    good = GoLiveResult(ready=True, checks={"a": True, "b": True})
    assert good.to_dict()["ready"] is True


def test_empty_checks_never_ready():
    """A partial/empty result (no criteria) can never be ready."""
    empty = GoLiveResult(ready=True, checks={})
    assert empty.to_dict()["ready"] is False


# ══════════════════════════════════════════════════════════════════════════════
# 2.4 — gap-monitor / track day-count MONOTONE (dup / future / out-of-order)
# ══════════════════════════════════════════════════════════════════════════════


def test_day_count_monotone_under_duplicates_and_disorder():
    """Duplicate + out-of-order evidenced dates collapse to a stable unique count."""
    d0, d1, d2 = ANCHOR, ANCHOR + timedelta(days=1), ANCHOR + timedelta(days=2)
    daily = [
        {"date": d2.isoformat(), "close_equity": 100_002.0},
        {"date": d0.isoformat(), "close_equity": 100_000.0},
        {"date": d1.isoformat(), "close_equity": 100_001.0},
        {"date": d1.isoformat(), "close_equity": 100_001.0},  # duplicate
        {"date": d0.isoformat(), "close_equity": 100_000.0},  # duplicate
    ]
    assert te.count_evidenced(daily) == 3  # never over-counts the duplicates


def test_future_dated_bar_never_over_counts():
    """A future-dated bar (after `today`) is excluded — cannot evidence a non-run cycle."""
    today = ANCHOR + timedelta(days=2)
    future = ANCHOR + timedelta(days=10)
    daily = _evidenced_daily(3)  # ANCHOR, +1, +2 (all <= today)
    daily.append({"date": future.isoformat(), "close_equity": 999_999.0})
    # Without the guard a stray future bar would inflate to 4; guarded → 3.
    assert te.count_evidenced(daily, today=today) == 3
    assert te.count_evidenced(daily) == 4  # unguarded default counts it (back-compat)


def test_golive_checker_pins_today_to_now(tmp_path):
    """The gate's track-day count excludes future bars (pins today=now.date())."""
    now = datetime(2026, 6, 12, 12, 0, tzinfo=timezone.utc)
    daily = _evidenced_daily(3)  # 06-10, 06-11, 06-12
    daily.append({"date": "2026-07-01", "close_equity": 1_000_000.0})  # future
    _write(tmp_path, "equity_curve_daily.json", {"daily": daily, "is_demo": False})
    checker = GoLiveChecker(data_dir=tmp_path, now=now)
    checker.check(write=False)
    assert checker._real_track_days == 3  # the future bar did not over-count


# ══════════════════════════════════════════════════════════════════════════════
# 2.4 — telegram digest miss-guard (visible, not silent; no fabricated send)
# ══════════════════════════════════════════════════════════════════════════════


def test_missed_digest_day_is_visible_not_silent(tmp_path, caplog):
    """A >1-day gap is logged + recorded in telegram_alert_state.json (not fabricated)."""
    # Last successful send was 2 days before today → 06-27 was silently missed.
    _write(tmp_path, "telegram_alert_state.json", {"daily_summary": "2026-06-26"})
    import logging
    with caplog.at_level(logging.WARNING, logger="spa.telegram.reports.daily"):
        info = digest._detect_and_record_miss(tmp_path, "2026-06-28",
                                              "2026-06-28T08:10:00+00:00")
    assert info["days_missed"] == 1
    assert any("MISSED" in r.getMessage() for r in caplog.records)
    state = json.loads((tmp_path / "telegram_alert_state.json").read_text())
    # The miss is recorded — but NO sent-state was fabricated for 06-27.
    assert state["daily_summary"] == "2026-06-26"  # unchanged (not faked forward)
    assert state["daily_summary_misses"][-1]["days_missed"] == 1
    assert state["daily_summary_misses"][-1]["last_sent"] == "2026-06-26"


def test_consecutive_day_is_not_a_miss(tmp_path):
    """Sending on the next calendar day is normal — records no miss."""
    _write(tmp_path, "telegram_alert_state.json", {"daily_summary": "2026-06-27"})
    info = digest._detect_and_record_miss(tmp_path, "2026-06-28",
                                          "2026-06-28T08:10:00+00:00")
    assert info["days_missed"] == 0
    state = json.loads((tmp_path / "telegram_alert_state.json").read_text())
    assert "daily_summary_misses" not in state  # nothing recorded


def test_first_ever_run_is_not_a_miss(tmp_path):
    """No prior send (first run) is not a 'miss' — no fabricated gap."""
    _write(tmp_path, "telegram_alert_state.json", {})
    info = digest._detect_and_record_miss(tmp_path, "2026-06-28",
                                          "2026-06-28T08:10:00+00:00")
    assert info["days_missed"] == 0


# ══════════════════════════════════════════════════════════════════════════════
# 2.4 — telegram_alert_today reflects reality (grace, not fabrication)
# ══════════════════════════════════════════════════════════════════════════════


def _checker_with_alert(tmp_path, sent_date: str | None, now: datetime):
    if sent_date is not None:
        _write(tmp_path, "telegram_alert_state.json", {"daily_summary": sent_date})
    return GoLiveChecker(data_dir=tmp_path, now=now)


def test_alert_today_passes_when_sent_today(tmp_path):
    now = datetime(2026, 6, 28, 12, 0, tzinfo=timezone.utc)
    c = _checker_with_alert(tmp_path, "2026-06-28", now)
    assert c._check_telegram_alert_today([]) is True


def test_alert_today_grace_pass_pre_digest_when_yesterday_sent(tmp_path):
    """Before ~08:10 UTC, yesterday-sent grants a grace pass (no daily false-dip)."""
    now = datetime(2026, 6, 28, 7, 0, tzinfo=timezone.utc)  # pre-digest
    c = _checker_with_alert(tmp_path, "2026-06-27", now)
    assert c._check_telegram_alert_today([]) is True


def test_alert_today_fails_after_grace_if_not_sent(tmp_path):
    """Past the grace hour with no send today → honest FAIL (visible, real miss)."""
    now = datetime(2026, 6, 28, 12, 0, tzinfo=timezone.utc)  # post-digest window
    c = _checker_with_alert(tmp_path, "2026-06-27", now)
    blockers: list[str] = []
    assert c._check_telegram_alert_today(blockers) is False
    assert blockers and "telegram_alert_today" in blockers[0]


def test_alert_today_no_grace_when_yesterday_also_missed(tmp_path):
    """If the most recent send is >1 day old, even pre-digest gives no grace pass."""
    now = datetime(2026, 6, 28, 7, 0, tzinfo=timezone.utc)  # pre-digest
    c = _checker_with_alert(tmp_path, "2026-06-26", now)  # 2 days stale
    assert c._check_telegram_alert_today([]) is False


if __name__ == "__main__":
    import sys
    sys.exit(pytest.main([__file__, "-v"]))
