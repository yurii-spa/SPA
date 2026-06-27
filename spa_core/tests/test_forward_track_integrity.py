"""
Tests for spa_core/strategy_lab/track_integrity.py — the forward-track continuity/integrity guard.

The forward live-paper tracks (rates_desk/paper + strategy_lab_paper) are the future fundability
evidence. They need the SAME gap-monitor discipline as the main go-live track NOW. These tests pin:
  - a clean continuous series is ok,
  - an injected DUPLICATE date is flagged,
  - a GAP (missing day) is flagged,
  - an OUT-OF-ORDER append is flagged,
  - a FUTURE date is flagged,
  - fail-CLOSED on a malformed series,
  - check_all over fixtures aggregates correctly + writes the report file,
  - the paper-tick wiring runs without breaking the tick (and flags a broken track).
"""
# LLM_FORBIDDEN
from __future__ import annotations

import datetime
import json

import pytest

from spa_core.strategy_lab import track_integrity as ti


def _day(offset: int) -> str:
    base = datetime.date(2026, 6, 20)
    return (base + datetime.timedelta(days=offset)).isoformat()


def _series(dates):
    return {"id": "x", "series": [{"date": d, "equity_usd": 100000.0 + i}
                                  for i, d in enumerate(dates)]}


# ── single-series checks ────────────────────────────────────────────────────────────────────────
def test_clean_series_is_ok():
    res = ti.check_track_integrity(_series([_day(0), _day(1), _day(2)]))
    assert res["ok"] is True
    assert res["reason"] == "ok"
    assert res["n_points"] == 3
    assert res["first_date"] == _day(0)
    assert res["last_date"] == _day(2)
    assert res["duplicates"] == []
    assert res["gaps"] == []
    assert res["out_of_order"] == []
    assert res["future"] == []


def test_accepts_bare_list_form():
    res = ti.check_track_integrity([{"date": _day(0)}, {"date": _day(1)}])
    assert res["ok"] is True


def test_empty_series_is_ok_but_flagged_empty():
    res = ti.check_track_integrity({"id": "x", "series": []})
    assert res["ok"] is True
    assert res["reason"] == "empty"
    assert res["n_points"] == 0


def test_duplicate_date_flagged():
    res = ti.check_track_integrity(_series([_day(0), _day(1), _day(1), _day(2)]))
    assert res["ok"] is False
    assert res["reason"] == "duplicates"
    assert res["duplicates"] == [_day(1)]


def test_gap_missing_day_flagged():
    # 2026-06-20 then 2026-06-23 → 2 missing days (21, 22).
    res = ti.check_track_integrity(_series([_day(0), _day(3)]))
    assert res["ok"] is False
    assert res["reason"] == "gaps"
    assert res["gaps"] == [{"from": _day(0), "to": _day(3), "days_missed": 2}]


def test_out_of_order_flagged():
    res = ti.check_track_integrity(_series([_day(0), _day(2), _day(1)]))
    assert res["ok"] is False
    assert res["reason"] == "out_of_order"
    assert res["out_of_order"] == [{"prev": _day(2), "next": _day(1)}]


def test_future_date_flagged():
    today = datetime.datetime.now(datetime.timezone.utc).date()
    future = (today + datetime.timedelta(days=2)).isoformat()
    res = ti.check_track_integrity({"id": "x", "series": [
        {"date": (today - datetime.timedelta(days=1)).isoformat()},
        {"date": future},
    ]})
    assert res["ok"] is False
    assert res["reason"] == "future"
    assert future in res["future"]


def test_schedule_hours_widens_allowed_spacing():
    # weekly schedule (168h = 7 days): a 3-day step is NOT a gap.
    res = ti.check_track_integrity(_series([_day(0), _day(3)]), schedule_hours=168)
    assert res["ok"] is True
    assert res["gaps"] == []


@pytest.mark.parametrize("bad", [
    42,
    "not-a-series",
    {"id": "x"},                       # no "series" key
    {"id": "x", "series": "nope"},     # series not a list
    {"id": "x", "series": [42]},       # point not a dict
    {"id": "x", "series": [{"equity_usd": 1}]},        # point missing "date"
    {"id": "x", "series": [{"date": 20260620}]},       # non-string date
    {"id": "x", "series": [{"date": "garbage"}]},      # unparseable date
])
def test_fail_closed_on_malformed(bad):
    res = ti.check_track_integrity(bad)
    assert res["ok"] is False
    assert res["reason"] == "malformed"


# ── aggregate check over fixtures ─────────────────────────────────────────────────────────────────
def _write_series(path, dates):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(_series(dates)))


def test_check_all_all_ok(tmp_path):
    _write_series(tmp_path / "rates_desk" / "paper" / "rates_desk_fixed_carry_series.json",
                  [_day(0), _day(1), _day(2)])
    _write_series(tmp_path / "strategy_lab_paper" / "variant_n_series.json",
                  [_day(0), _day(1), _day(2)])
    rep = ti.check_all_forward_tracks(tmp_path)
    assert rep["all_ok"] is True
    assert rep["n_tracks"] == 2
    assert rep["n_failing"] == 0
    names = {t["name"] for t in rep["tracks"]}
    assert "paper/rates_desk_fixed_carry" in names
    assert "strategy_lab_paper/variant_n" in names
    # report file written atomically
    written = json.loads((tmp_path / "forward_track_integrity.json").read_text())
    assert written["all_ok"] is True


def test_check_all_flags_a_broken_track(tmp_path):
    _write_series(tmp_path / "strategy_lab_paper" / "variant_n_series.json",
                  [_day(0), _day(1), _day(2)])               # clean
    _write_series(tmp_path / "strategy_lab_paper" / "variant_d_series.json",
                  [_day(0), _day(3)])                        # gap
    rep = ti.check_all_forward_tracks(tmp_path)
    assert rep["all_ok"] is False
    assert rep["n_failing"] == 1
    broken = [t for t in rep["tracks"] if not t["ok"]]
    assert len(broken) == 1
    assert broken[0]["name"] == "strategy_lab_paper/variant_d"
    assert broken[0]["reason"] == "gaps"


def test_check_all_unreadable_file_is_not_ok(tmp_path):
    f = tmp_path / "strategy_lab_paper" / "broken_series.json"
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_text("{ this is not valid json")
    # check_all must surface it as a not-ok track, never crash (fail-CLOSED).
    rep = ti.check_all_forward_tracks(tmp_path)
    broken = [t for t in rep["tracks"] if not t["ok"]]
    assert any(t["name"] == "strategy_lab_paper/broken" and t["reason"] == "unreadable"
               for t in broken)


def test_check_all_empty_dir(tmp_path):
    rep = ti.check_all_forward_tracks(tmp_path, write=False)
    assert rep["all_ok"] is True
    assert rep["n_tracks"] == 0


# ── advisory flag does not raise + routes to digest ────────────────────────────────────────────────
def test_flag_if_broken_no_break_is_noop(tmp_path):
    _write_series(tmp_path / "strategy_lab_paper" / "variant_n_series.json",
                  [_day(0), _day(1)])
    rep = ti.flag_if_broken(data_dir=tmp_path)
    assert rep["all_ok"] is True


def test_flag_if_broken_enqueues_digest_on_break(tmp_path, monkeypatch):
    _write_series(tmp_path / "strategy_lab_paper" / "variant_d_series.json",
                  [_day(0), _day(3)])  # gap
    calls = []

    import spa_core.telegram.push_policy as pp
    monkeypatch.setattr(pp, "enqueue_digest",
                        lambda *a, **k: calls.append((a, k)))
    rep = ti.flag_if_broken(data_dir=tmp_path)
    assert rep["all_ok"] is False
    assert len(calls) == 1  # one digest line for the one broken track


def test_flag_if_broken_never_raises_even_if_digest_fails(tmp_path, monkeypatch):
    _write_series(tmp_path / "strategy_lab_paper" / "variant_d_series.json",
                  [_day(0), _day(3)])
    import spa_core.telegram.push_policy as pp

    def _boom(*a, **k):
        raise RuntimeError("digest down")
    monkeypatch.setattr(pp, "enqueue_digest", _boom)
    # must NOT propagate — the advisory flag is fail-open.
    rep = ti.flag_if_broken(data_dir=tmp_path)
    assert rep["all_ok"] is False


# ── wiring: the paper tick still runs with the guard inline ────────────────────────────────────────
def test_paper_service_method_present_and_safe(tmp_path, monkeypatch):
    """The PaperService gained _check_forward_track_integrity and it never raises even when the
    integrity module is made to blow up (fail-open guard)."""
    from spa_core.strategy_lab.paper import PaperService
    svc = PaperService.__new__(PaperService)
    svc._state_dir = tmp_path  # parent acts as data dir
    # No tracks under tmp_path → no break, no raise.
    svc._check_forward_track_integrity()

    # Force the guard's import target to raise: still must not propagate.
    import spa_core.strategy_lab.track_integrity as tmod
    monkeypatch.setattr(tmod, "flag_if_broken",
                        lambda *a, **k: (_ for _ in ()).throw(RuntimeError("boom")))
    svc._check_forward_track_integrity()  # swallowed


def test_rates_paper_service_method_present_and_safe(tmp_path, monkeypatch):
    from spa_core.strategy_lab.rates_desk.paper_rates import RatesDeskPaperService
    svc = RatesDeskPaperService.__new__(RatesDeskPaperService)
    svc._state_dir = tmp_path / "rates_desk" / "paper"
    svc._state_dir.mkdir(parents=True, exist_ok=True)
    svc._check_forward_track_integrity()

    import spa_core.strategy_lab.track_integrity as tmod
    monkeypatch.setattr(tmod, "flag_if_broken",
                        lambda *a, **k: (_ for _ in ()).throw(RuntimeError("boom")))
    svc._check_forward_track_integrity()
