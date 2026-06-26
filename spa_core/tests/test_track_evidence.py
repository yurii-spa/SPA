"""Tests for the HONEST TRACK RESET evidence model (2026-06-26).

Pins the operator-approved rule: the go-live track counts ONLY days backed by a
real ``daily_cycle`` log. Flat-rate backfill and reconstructed (interpolated)
days are NOT counted; history is preserved (flagged, never deleted). A new real
cycle day must increment the count.
"""
from __future__ import annotations

import json
from datetime import date, datetime, timezone
from pathlib import Path

import pytest

from spa_core.paper_trading import track_evidence as te
from spa_core.paper_trading.golive_checker import GoLiveChecker

PAPER_START = date(2026, 6, 10)


# ─── helpers ──────────────────────────────────────────────────────────────────


def _write_cycle_log(logs_dir: Path, d: date, real: bool = True) -> None:
    logs_dir.mkdir(parents=True, exist_ok=True)
    path = logs_dir / f"daily_cycle_{d.strftime('%Y%m%d')}.log"
    body = (
        f"[{d.isoformat()}T06:00:01Z] Starting daily paper cycle (cycle_runner)\n"
        "INFO spa.cycle_runner: cycle complete\n"
    ) if real else "garbage with no header\n"
    path.write_text(body, encoding="utf-8")


def _bar(d: str, **extra) -> dict:
    b = {"date": d, "open_equity": 100000.0, "close_equity": 100010.0}
    b.update(extra)
    return b


# ─── has_cycle_log / evidence detection ────────────────────────────────────────


def test_has_cycle_log_true_for_real_log(tmp_path):
    logs = tmp_path / "logs"
    _write_cycle_log(logs, date(2026, 6, 22))
    assert te.has_cycle_log(date(2026, 6, 22), logs) is True


def test_has_cycle_log_false_when_missing(tmp_path):
    logs = tmp_path / "logs"
    logs.mkdir()
    assert te.has_cycle_log(date(2026, 6, 22), logs) is False


def test_has_cycle_log_false_without_header(tmp_path):
    """Fail-CLOSED: a header-less file is not a real cycle."""
    logs = tmp_path / "logs"
    _write_cycle_log(logs, date(2026, 6, 22), real=False)
    assert te.has_cycle_log(date(2026, 6, 22), logs) is False


# ─── classify_bar (ground truth) ───────────────────────────────────────────────


def test_classify_cycle_day(tmp_path):
    logs = tmp_path / "logs"
    _write_cycle_log(logs, date(2026, 6, 22))
    src, ev = te.classify_bar(_bar("2026-06-22"), logs_dir=logs)
    assert (src, ev) == (te.SOURCE_CYCLE, True)


def test_classify_backfill_day(tmp_path):
    """Dated >= anchor, no cycle log → flat-rate backfill, NOT evidenced."""
    logs = tmp_path / "logs"
    logs.mkdir()
    src, ev = te.classify_bar(_bar("2026-06-12"), logs_dir=logs)
    assert (src, ev) == (te.SOURCE_BACKFILL, False)


def test_classify_reconstructed_day(tmp_path):
    logs = tmp_path / "logs"
    _write_cycle_log(logs, date(2026, 6, 21))  # even with a log, reconstructed wins
    src, ev = te.classify_bar(_bar("2026-06-21", reconstructed=True), logs_dir=logs)
    assert (src, ev) == (te.SOURCE_RECONSTRUCTED, False)


def test_classify_warmup_pre_anchor(tmp_path):
    logs = tmp_path / "logs"
    logs.mkdir()
    src, ev = te.classify_bar(_bar("2026-05-21"), logs_dir=logs)
    assert (src, ev) == (te.SOURCE_WARMUP, False)


# ─── is_evidenced_bar (counting predicate, reads labels) ───────────────────────


def test_evidenced_bar_explicit_true():
    assert te.is_evidenced_bar(_bar("2026-06-22", evidenced=True, source="cycle"))


def test_backfill_label_not_counted():
    assert not te.is_evidenced_bar(_bar("2026-06-12", evidenced=False, source="backfill"))


def test_reconstructed_not_counted():
    assert not te.is_evidenced_bar(_bar("2026-06-21", reconstructed=True))


def test_unlabeled_legacy_bar_counts():
    """Backward-compat: a post-anchor bar with no honesty label still counts."""
    assert te.is_evidenced_bar(_bar("2026-06-22"))


def test_pre_anchor_not_counted():
    assert not te.is_evidenced_bar(_bar("2026-05-21", evidenced=True, source="cycle"))


# ─── the honest reset scenario (capstone) ──────────────────────────────────────


def _reset_scenario_daily() -> list[dict]:
    """The live shape: 11 backfill + 1 reconstructed + 5 real-cycle days."""
    daily: list[dict] = []
    # 06-10..06-20: flat-rate backfill (11 days)
    for day in range(10, 21):
        daily.append(_bar(f"2026-06-{day:02d}", evidenced=False, source="backfill"))
    # 06-21: reconstructed
    daily.append(_bar("2026-06-21", reconstructed=True, evidenced=False,
                      source="reconstructed"))
    # 06-22..06-26: real cycle days (5 evidenced)
    for day in range(22, 27):
        daily.append(_bar(f"2026-06-{day:02d}", evidenced=True, source="cycle"))
    return daily


def test_honest_count_excludes_backfill_and_reconstructed():
    daily = _reset_scenario_daily()
    dates = te.evidenced_dates(daily, paper_start=PAPER_START)
    assert dates == ["2026-06-22", "2026-06-23", "2026-06-24",
                     "2026-06-25", "2026-06-26"]
    assert te.count_evidenced(daily, paper_start=PAPER_START) == 5
    assert te.first_evidenced_date(daily, paper_start=PAPER_START) == "2026-06-22"


def test_new_real_cycle_day_increments_count():
    daily = _reset_scenario_daily()
    before = te.count_evidenced(daily, paper_start=PAPER_START)
    daily.append(_bar("2026-06-27", evidenced=True, source="cycle"))
    after = te.count_evidenced(daily, paper_start=PAPER_START)
    assert after == before + 1


def test_label_bars_preserves_history(tmp_path):
    """All bars are kept; only honesty fields are (re)written."""
    logs = tmp_path / "logs"
    _write_cycle_log(logs, date(2026, 6, 22))
    daily = [
        _bar("2026-06-12"),                       # backfill (no log)
        _bar("2026-06-21", reconstructed=True),   # reconstructed
        _bar("2026-06-22"),                        # cycle (has log)
    ]
    out = te.label_bars(daily, paper_start=PAPER_START, logs_dir=logs)
    assert len(out) == 3  # history preserved
    assert out[0]["source"] == "backfill" and out[0]["evidenced"] is False
    assert out[1]["source"] == "reconstructed" and out[1]["evidenced"] is False
    assert out[2]["source"] == "cycle" and out[2]["evidenced"] is True


def test_label_equity_file_atomic_and_honest(tmp_path):
    logs = tmp_path / "logs"
    for d in (22, 23):
        _write_cycle_log(logs, date(2026, 6, d))
    eq = tmp_path / "equity_curve_daily.json"
    doc = {
        "is_demo": False,
        "summary": {"real_days": 99},
        "daily": [
            _bar("2026-06-12"),
            _bar("2026-06-21", reconstructed=True),
            _bar("2026-06-22"),
            _bar("2026-06-23"),
        ],
    }
    eq.write_text(json.dumps(doc), encoding="utf-8")
    report = te.label_equity_file(eq, paper_start=PAPER_START, logs_dir=logs)
    assert report["evidenced"] == 2
    assert report["first_evidenced"] == "2026-06-22"
    on_disk = json.loads(eq.read_text())
    assert on_disk["summary"]["real_days"] == 2
    assert on_disk["summary"]["first_real_date"] == "2026-06-22"
    assert len(on_disk["daily"]) == 4  # history preserved
    # no temp file left behind
    assert not (tmp_path / "equity_curve_daily.json.tmp").exists()


# ─── golive_checker integration (honest count) ─────────────────────────────────


def test_golive_counts_only_evidenced(tmp_path):
    """golive_checker.real_track_days reflects the honest evidenced count."""
    ddir = tmp_path / "data"
    ddir.mkdir(parents=True)
    doc = {
        "is_demo": False,
        "source": "cycle_runner",
        "summary": {"max_drawdown_pct": 0.0},
        "daily": _reset_scenario_daily(),
    }
    (ddir / "equity_curve_daily.json").write_text(json.dumps(doc), encoding="utf-8")
    now = datetime(2026, 6, 26, 12, 0, tzinfo=timezone.utc)
    res = GoLiveChecker(data_dir=ddir, now=now, paper_start=PAPER_START).check(write=False)
    assert res.real_track_days == 5
    assert res.checks["min_track_days_30"] is False
    assert any("5/30" in b for b in res.blockers)


def test_golive_target_anchored_to_first_evidenced(tmp_path):
    """Target date = first evidenced (06-22) + 29 days = 2026-07-21."""
    ddir = tmp_path / "data"
    ddir.mkdir(parents=True)
    doc = {
        "is_demo": False,
        "source": "cycle_runner",
        "summary": {"max_drawdown_pct": 0.0},
        "daily": _reset_scenario_daily(),
    }
    (ddir / "equity_curve_daily.json").write_text(json.dumps(doc), encoding="utf-8")
    now = datetime(2026, 6, 26, 12, 0, tzinfo=timezone.utc)
    res = GoLiveChecker(data_dir=ddir, now=now, paper_start=PAPER_START).check(write=False)
    det = res.details["min_track_days_30"]
    assert det["status"] == "PENDING"
    assert det["target_date"] == "2026-07-21"


# ─── T10: real-series segregation (clean evidenced metrics) ────────────────────


def test_real_series_returns_only_evidenced():
    """real_series / evidenced_bars yield ONLY the cycle bars, in order."""
    daily = _reset_scenario_daily()
    ev = te.evidenced_bars(daily, paper_start=PAPER_START)
    assert [b["date"] for b in ev] == [
        "2026-06-22", "2026-06-23", "2026-06-24", "2026-06-25", "2026-06-26"
    ]
    # real_series is the readable alias of the same function.
    assert te.real_series is te.evidenced_bars
    assert te.real_series(daily, paper_start=PAPER_START) == ev


def test_real_max_drawdown_ignores_warmup_crash():
    """A catastrophic WARMUP crash must NOT contaminate the real drawdown.

    The whole point of T10: the warmup→anchor discontinuity (here a fake -50%
    warmup drop) fabricates a drawdown the real evidenced series never had. The
    real series is monotonically rising → real drawdown 0.0%.
    """
    daily = [
        _bar("2026-05-21", open_equity=100000, close_equity=200000,
             is_warmup=True, source="warmup", evidenced=False),
        _bar("2026-05-22", open_equity=200000, close_equity=100000,
             is_warmup=True, source="warmup", evidenced=False),  # -50% (fake)
        _bar("2026-06-22", open_equity=100000, close_equity=100050,
             source="cycle", evidenced=True),
        _bar("2026-06-23", open_equity=100050, close_equity=100100,
             source="cycle", evidenced=True),
    ]
    assert te.real_max_drawdown_pct(daily, paper_start=PAPER_START) == 0.0


def test_real_total_return_over_evidenced_only():
    daily = [
        _bar("2026-06-12", open_equity=100000, close_equity=999999,
             evidenced=False, source="backfill"),  # backfill must not count
        _bar("2026-06-22", open_equity=100000, close_equity=100050,
             source="cycle", evidenced=True),
        _bar("2026-06-23", open_equity=100050, close_equity=100200,
             source="cycle", evidenced=True),
    ]
    # 100000 -> 100200 over the evidenced series = +0.2%
    assert te.real_total_return_pct(daily, paper_start=PAPER_START) == 0.2


def test_real_metrics_empty_series_are_zero():
    daily = [_bar("2026-06-12", evidenced=False, source="backfill")]
    assert te.evidenced_bars(daily, paper_start=PAPER_START) == []
    assert te.real_max_drawdown_pct(daily, paper_start=PAPER_START) == 0.0
    assert te.real_total_return_pct(daily, paper_start=PAPER_START) == 0.0


def test_golive_drawdown_uses_evidenced_series_not_summary(tmp_path):
    """The kill-switch criterion must read the REAL series, NOT summary roll-up.

    Contaminate summary.max_drawdown_pct with a kill-triggering -50% (spanning
    warmup bars) while the real evidenced series is flat (dd 0%). The gate must
    PASS — proving it no longer reads the contaminated summary field.
    """
    ddir = tmp_path / "data"
    ddir.mkdir(parents=True)
    daily = _reset_scenario_daily()
    # give the real cycle bars a rising, drawdown-free equity
    eq = 100000.0
    for b in daily:
        if b.get("evidenced"):
            b["open_equity"] = eq
            eq += 50.0
            b["close_equity"] = eq
    doc = {
        "is_demo": False,
        "source": "cycle_runner",
        # contaminated all-bars roll-up — would FALSE-FIRE the kill switch
        "summary": {"max_drawdown_pct": -50.0, "total_return_pct": -50.0,
                    "num_days": len(daily)},
        "daily": daily,
    }
    (ddir / "equity_curve_daily.json").write_text(json.dumps(doc), encoding="utf-8")
    now = datetime(2026, 6, 26, 12, 0, tzinfo=timezone.utc)
    checker = GoLiveChecker(data_dir=ddir, now=now, paper_start=PAPER_START)
    blockers: list[str] = []
    assert checker._check_drawdown_below_kill(blockers) is True
    assert blockers == []


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
