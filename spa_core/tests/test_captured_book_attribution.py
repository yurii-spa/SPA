"""
Tests for the WS-1.6 captured-book PnL attribution in
spa_core/strategy_lab/forward_analytics.captured_book_attribution.

These pin the HONESTY contract the dashboard's captured-book panel + the /api/captured-book
surface depend on:

  * PROPERTY — reconciliation: floor_leg_usd + carry_leg_usd == realized_pnl_usd, to the cent,
    on ANY valid series (carry is the residual, so it reconciles to the captured-book NAV move
    by construction). reconciles=True only when |residual| < 1e-6.
  * the carry leg can be HONESTLY NEGATIVE when the book underperforms the RWA floor (a real
    fixed-carry book in its first few days) — we never floor it at 0 or fabricate a positive edge.
  * THIN flag — below MIN_POINTS_FOR_RATIO the $ split is still exact but risk_adjusted_known=False.
  * RED-TEAM / fail-CLOSED — a tampered / look-ahead (FUTURE-dated) / gapped / duplicate / malformed
    (non-finite equity) series is REFUSED by track_integrity → status UNKNOWN, reconciles=False, NO
    fabricated carry number (carry_leg_usd is None).
"""
# LLM_FORBIDDEN
from __future__ import annotations

import datetime

from spa_core.strategy_lab import forward_analytics as fa
from spa_core.strategy_lab.forward_analytics import captured_book_attribution as cba

_FLOOR = 3.4  # pin the RWA floor (no live network dependency in the test)


def _day(offset: int) -> str:
    return (datetime.date(2026, 6, 1) + datetime.timedelta(days=offset)).isoformat()


def _series(equities):
    return {
        "id": "rates_desk_fixed_carry",
        "series": [
            {"date": _day(i), "ts": f"{_day(i)}T00:00:00+00:00", "equity_usd": float(e)}
            for i, e in enumerate(equities)
        ],
    }


def _reconciles(a: dict) -> bool:
    return abs((a["floor_leg_usd"] + a["carry_leg_usd"]) - a["realized_pnl_usd"]) < 1e-6


# ── PROPERTY: reconciliation to NAV (carry + floor == realized) ──────────────────────────────
def test_reconciles_to_nav_when_beating_floor():
    # a book growing FAST (well above the ~3.4% floor) → carry leg positive, reconciles exactly.
    a = cba(_series([100000.0, 100050.0, 100110.0, 100180.0]), floor_apy_pct=_FLOOR)
    assert a["status"] in ("OK", "THIN")
    assert a["reconciles"] is True
    assert _reconciles(a)
    assert a["nav_usd"] == 100180.0
    assert a["realized_pnl_usd"] == 180.0
    assert a["carry_beats_floor"] is True
    assert a["carry_leg_usd"] > 0


def test_reconciles_with_honest_negative_carry():
    # a book BELOW the floor (barely moving) → carry leg HONESTLY negative, still reconciles to NAV.
    a = cba(_series([100000.0, 100000.5, 100001.0, 100001.5]), floor_apy_pct=_FLOOR)
    assert a["reconciles"] is True
    assert _reconciles(a)
    assert a["carry_leg_usd"] < 0           # honest: the book did NOT beat cash
    assert a["carry_beats_floor"] is False
    # the floor leg is positive (cash would have earned something)
    assert a["floor_leg_usd"] > 0


def test_thin_flag_below_min_points():
    a = cba(_series([100000.0, 100010.0, 100020.0]), floor_apy_pct=_FLOOR)  # 3 points < 7
    assert a["thin"] is True
    assert a["risk_adjusted_known"] is False
    assert a["reconciles"] is True          # the $ split is still exact
    assert _reconciles(a)


def test_not_thin_with_enough_points():
    eq = [100000.0 + 12.0 * i for i in range(8)]  # 8 points ≥ MIN_POINTS_FOR_RATIO
    a = cba(_series(eq), floor_apy_pct=_FLOOR)
    assert a["thin"] is False
    assert a["risk_adjusted_known"] is True
    assert a["reconciles"] is True
    assert _reconciles(a)


def test_single_point_trivially_reconciles():
    a = cba(_series([100000.0]), floor_apy_pct=_FLOOR)
    assert a["status"] == "THIN"
    assert a["reconciles"] is True
    assert a["realized_pnl_usd"] == 0.0
    assert a["floor_leg_usd"] == 0.0
    assert a["carry_leg_usd"] == 0.0


# ── RED-TEAM: a tampered / look-ahead series is REFUSED, never an inflated carry number ───────
def test_redteam_lookahead_future_dated_refused():
    future = (datetime.date.today() + datetime.timedelta(days=400)).isoformat()
    doc = {"series": [
        {"date": "2026-06-25", "equity_usd": 100000.0},
        {"date": future, "equity_usd": 9_999_999.0},  # absurd look-ahead spike
    ]}
    a = cba(doc, floor_apy_pct=_FLOOR)
    assert a["status"] == "UNKNOWN"
    assert a["reconciles"] is False
    assert a["integrity_reason"] == "future"
    assert a["carry_leg_usd"] is None       # NO fabricated number
    assert a["floor_leg_usd"] is None


def test_redteam_duplicate_date_tamper_refused():
    doc = {"series": [
        {"date": "2026-06-25", "equity_usd": 100000.0},
        {"date": "2026-06-25", "equity_usd": 500000.0},  # duplicate date inflating equity
    ]}
    a = cba(doc, floor_apy_pct=_FLOOR)
    assert a["status"] == "UNKNOWN"
    assert a["reconciles"] is False
    assert a["integrity_reason"] == "duplicates"
    assert a["carry_leg_usd"] is None


def test_redteam_nonfinite_equity_refused():
    doc = {"series": [
        {"date": "2026-06-25", "equity_usd": 100000.0},
        {"date": "2026-06-26", "equity_usd": float("inf")},
    ]}
    a = cba(doc, floor_apy_pct=_FLOOR)
    assert a["status"] == "UNKNOWN"
    assert a["reconciles"] is False
    assert a["integrity_reason"].startswith("malformed")
    assert a["carry_leg_usd"] is None


def test_redteam_gapped_series_refused():
    doc = {"series": [
        {"date": "2026-06-25", "equity_usd": 100000.0},
        {"date": "2026-06-30", "equity_usd": 100010.0},  # 5-day gap
    ]}
    a = cba(doc, floor_apy_pct=_FLOOR)
    assert a["status"] == "UNKNOWN"
    assert a["reconciles"] is False
    assert a["carry_leg_usd"] is None


def test_redteam_malformed_doc_refused():
    a = cba("not a series", floor_apy_pct=_FLOOR)
    assert a["status"] == "UNKNOWN"
    assert a["reconciles"] is False
    assert a["carry_leg_usd"] is None


# ── integration into the scorecard artifact ─────────────────────────────────────────────────
def test_build_scorecard_includes_captured_attribution(tmp_path):
    # write a clean carry series under the scanned rates_desk/paper dir
    paper = tmp_path / "rates_desk" / "paper"
    paper.mkdir(parents=True)
    import json
    (paper / "rates_desk_fixed_carry_series.json").write_text(
        json.dumps(_series([100000.0, 100030.0, 100070.0, 100120.0]))
    )
    out = fa.build_scorecard(data_dir=tmp_path, write=False,
                             now_iso="2026-06-28T00:00:00+00:00")
    assert "captured_book_attribution" in out
    ca = out["captured_book_attribution"]
    assert ca["reconciles"] is True
    assert _reconciles(ca)
