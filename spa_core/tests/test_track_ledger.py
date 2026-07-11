"""Tests for the Q2-18 evidenced-track ledger (spa_core/paper_trading/track_ledger.py).

Verifies: only EVIDENCED bars are counted (warmup/backfill excluded via the single segregation point),
drawdown-from-running-peak is computed correctly, the summary counts + days_remaining are right, and a
missing/malformed equity file yields an empty ledger fail-closed (never a fabricated day). Deterministic.
"""
import json

import pytest

from spa_core.paper_trading import track_ledger as tl


def _bar(date, close, *, evidenced=True, source="cycle", daily_return_pct=0.0):
    b = {"date": date, "close_equity": close, "daily_return_pct": daily_return_pct,
         "evidenced": evidenced, "source": source}
    return b


def _equity_file(tmp_path, bars):
    p = tmp_path / "equity_curve_daily.json"
    p.write_text(json.dumps({"daily": bars}))
    return p


def test_only_evidenced_bars_counted(tmp_path):
    bars = [
        _bar("2026-06-08", 100000, evidenced=False, source="warmup"),   # pre-anchor warmup → excluded
        _bar("2026-06-22", 100150, daily_return_pct=0.15),               # evidenced
        _bar("2026-06-23", 100300, daily_return_pct=0.15),               # evidenced
        _bar("2026-06-24", 100200, evidenced=False, source="backfill"),  # backfill → excluded
    ]
    rep = tl.build_ledger(equity_path=_equity_file(tmp_path, bars), write=False)
    assert rep["n_evidenced_days"] == 2
    assert [r["date"] for r in rep["ledger"]] == ["2026-06-22", "2026-06-23"]
    assert rep["first_evidenced_date"] == "2026-06-22"
    assert rep["last_evidenced_date"] == "2026-06-23"


def test_drawdown_from_peak(tmp_path):
    # rises to 101000 then dips to 99990 → drawdown from peak = (99990/101000 - 1)*100 ≈ -1.0%
    bars = [
        _bar("2026-06-22", 100000),
        _bar("2026-06-23", 101000),
        _bar("2026-06-24", 99990),
    ]
    rep = tl.build_ledger(equity_path=_equity_file(tmp_path, bars), write=False)
    last = rep["ledger"][-1]
    assert last["drawdown_from_peak_pct"] == pytest.approx((99990 / 101000 - 1) * 100, abs=1e-3)
    assert rep["max_drawdown_from_peak_pct"] <= last["drawdown_from_peak_pct"] + 1e-9
    # cumulative return is vs the FIRST evidenced close
    assert last["cumulative_return_pct"] == pytest.approx((99990 / 100000 - 1) * 100, abs=1e-3)


def test_days_remaining_and_needed(tmp_path):
    bars = [_bar(f"2026-06-{22 + i:02d}", 100000 + i) for i in range(5)]
    rep = tl.build_ledger(equity_path=_equity_file(tmp_path, bars), write=False)
    assert rep["days_needed"] == tl.DAYS_NEEDED
    assert rep["n_evidenced_days"] == 5
    assert rep["days_remaining"] == tl.DAYS_NEEDED - 5


def test_missing_file_fail_closed(tmp_path):
    rep = tl.build_ledger(equity_path=tmp_path / "does_not_exist.json", write=False)
    assert rep["n_evidenced_days"] == 0
    assert rep["ledger"] == []
    assert rep["first_evidenced_date"] is None
    assert rep["cumulative_return_pct"] == 0.0


def test_deterministic(tmp_path):
    bars = [_bar("2026-06-22", 100000), _bar("2026-06-23", 100200)]
    p = _equity_file(tmp_path, bars)
    assert tl.build_ledger(equity_path=p, write=False) == tl.build_ledger(equity_path=p, write=False)
