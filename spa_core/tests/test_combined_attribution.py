"""
spa_core/tests/test_combined_attribution.py — WS-4.2 COMBINED multi-sleeve captured-book attribution.

Pins: the combined floor-leg + carry-leg reconciles to the COMBINED captured-book NAV exactly; a
book that fails integrity (look-ahead / dup / gap / malformed) is REFUSED and EXCLUDED from the totals
(never an inflated combined carry); honest THIN; honest negative combined carry early.
"""
# LLM_FORBIDDEN
from __future__ import annotations

import datetime

from spa_core.strategy_lab import forward_analytics as fa
from spa_core.strategy_lab.forward_analytics import combined_book_attribution as comb


_FLOOR = 3.4


def _day(offset: int) -> str:
    return (datetime.date(2026, 6, 1) + datetime.timedelta(days=offset)).isoformat()


def _series(equities):
    return {"series": [
        {"date": _day(i), "equity_usd": float(e)} for i, e in enumerate(equities)]}


def _reconciles_legs(c):
    return abs((c["combined_floor_leg_usd"] + c["combined_carry_leg_usd"])
               - c["combined_realized_pnl_usd"]) < 1e-6


# ── PROPERTY: combined reconciliation to NAV ──────────────────────────────────────────────────
def test_combined_reconciles_to_nav():
    books = {
        "fixedcarry": _series([100000.0, 100050.0, 100110.0, 100180.0]),
        "rwa_sleeve": _series([100000.0, 100009.0, 100018.0, 100027.0]),
    }
    c = comb(books, floor_apy_pct=_FLOOR)
    assert c["reconciles"] is True
    assert _reconciles_legs(c)
    assert c["n_books_contributing"] == 2
    assert c["n_books_refused"] == 0
    # NAV identity: combined realized == combined NAV − combined initial (to the cent)
    assert abs((c["combined_nav_usd"] - c["combined_initial_capital_usd"])
               - c["combined_realized_pnl_usd"]) <= 0.02


def test_combined_carry_can_be_honestly_negative():
    # both books barely move (below the floor) → combined carry leg honestly negative
    books = {
        "fixedcarry": _series([100000.0, 100000.5, 100001.0, 100001.5]),
        "rwa_sleeve": _series([100000.0, 100000.5, 100001.0, 100001.5]),
    }
    c = comb(books, floor_apy_pct=_FLOOR)
    assert c["reconciles"] is True
    assert c["combined_carry_leg_usd"] < 0
    assert c["carry_beats_floor"] is False


def test_thin_flag():
    books = {"fixedcarry": _series([100000.0, 100030.0, 100070.0])}  # 3 pts < 7
    c = comb(books, floor_apy_pct=_FLOOR)
    assert c["thin"] is True
    assert c["status"] == "THIN"
    assert c["reconciles"] is True


# ── RED-TEAM: a tampered book is REFUSED + EXCLUDED, the clean books still reconcile ──────────
def test_redteam_lookahead_book_excluded():
    future = (datetime.date.today() + datetime.timedelta(days=400)).isoformat()
    books = {
        "clean": _series([100000.0, 100030.0, 100070.0, 100120.0]),
        "tampered": {"series": [
            {"date": "2026-06-25", "equity_usd": 100000.0},
            {"date": future, "equity_usd": 9_999_999.0}]},
    }
    c = comb(books, floor_apy_pct=_FLOOR)
    # the tampered book contributes NOTHING; the clean book still reconciles
    assert c["n_books_refused"] == 1
    assert c["n_books_contributing"] == 1
    assert c["reconciles"] is True
    assert _reconciles_legs(c)
    # the inflated 9.99M never leaked into the combined NAV
    assert c["combined_nav_usd"] < 200000.0
    tampered = next(b for b in c["books"] if b["name"] == "tampered")
    assert tampered["contributes"] is False
    assert tampered["status"] == "UNKNOWN"


def test_redteam_all_refused_yields_unknown_zero():
    books = {"tampered": {"series": [
        {"date": "2026-06-25", "equity_usd": 100000.0},
        {"date": "2026-06-25", "equity_usd": 500000.0}]}}  # duplicate
    c = comb(books, floor_apy_pct=_FLOOR)
    assert c["status"] == "UNKNOWN"
    assert c["n_books_contributing"] == 0
    assert c["combined_carry_leg_usd"] == 0.0
    assert c["combined_realized_pnl_usd"] == 0.0


def test_empty_books_unknown():
    c = comb({}, floor_apy_pct=_FLOOR)
    assert c["status"] == "UNKNOWN"
    assert c["reconciles"] is True  # trivially 0 == 0 + 0


# ── integration: the scorecard surfaces the combined attribution ──────────────────────────────
def test_scorecard_includes_combined(tmp_path):
    import json
    paper = tmp_path / "rates_desk" / "paper"
    paper.mkdir(parents=True)
    (paper / "rates_desk_fixed_carry_series.json").write_text(
        json.dumps({"id": "rates_desk_fixed_carry",
                    "series": [{"date": _day(i), "equity_usd": 100000.0 + 30.0 * i} for i in range(4)]}))
    out = fa.build_scorecard(data_dir=tmp_path, write=False, floor_apy_pct=_FLOOR,
                             now_iso="2026-06-28T00:00:00+00:00")
    assert "combined_book_attribution" in out
    c = out["combined_book_attribution"]
    assert c["reconciles"] is True
