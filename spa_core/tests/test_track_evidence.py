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


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
