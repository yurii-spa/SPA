# FROZEN-DATE-OK: valuation dates ARE the subject — the day-count convention is measured on them.
"""P1 Wave 2 step 3 — the paper track's return over its actual period, proven from the ledger.

Positive and negative cases: no flows ⇒ NAV ratio (TWR = MWR); a flow ⇒ TWR with MWR separate;
missing days count in ACT/365; costs are inside NAV; absence is None, never 0 (inv. #17).
"""
from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest

from spa_core.paper_trading.track_period_return import CONVENTION, period_return

ROOT = Path(__file__).resolve().parents[2]


def _bar(date, o, c, y, cost=0.0, **kw):
    b = {"date": date, "open_equity": o, "close_equity": c, "equity": c,
         "daily_yield_usd": y, "cost_usd": cost, "evidenced": True}
    b.update(kw)
    return b


def _clean_series():
    # 5 evidenced bars, one missing calendar day (06-04), one cost day, continuous NAV.
    return [
        {"date": "2026-06-01", "close_equity": 99_990.0, "equity": 99_990.0, "evidenced": False,
         "source": "reconstructed"},
        _bar("2026-06-02", 99_990.0, 100_000.0, 10.0),
        _bar("2026-06-03", 100_000.0, 100_010.0, 10.0),
        _bar("2026-06-05", 100_010.0, 99_980.0, 10.0, cost=40.0),
        _bar("2026-06-06", 99_980.0, 99_980.0, 0.0),
        _bar("2026-06-07", 99_980.0, 100_020.0, 40.0),
    ]


def test_no_flows_is_nav_ratio_from_the_close_of_the_first_evidenced_bar():
    r = period_return(_clean_series())
    assert r["state"] == "MEASURED" and r["method"] == "NAV_RATIO"
    assert r["nav_start"] == 100_000.0                    # close of 06-02, not its open
    assert r["nav_end"] == 100_020.0
    assert r["period_return_pct"] == pytest.approx(0.02, abs=1e-9)
    assert r["twr_pct"] == r["mwr_pct"] == r["period_return_pct"]
    assert r["flows"]["count"] == 0


def test_day_count_is_act_365_on_valuation_dates_and_keeps_missing_days():
    r = period_return(_clean_series())
    p = r["period"]
    assert p["convention"] == CONVENTION
    assert p["days_act"] == 5                             # 06-02 → 06-07, the missing 06-04 included
    assert p["evidenced_bars"] == 5 and p["accrual_bars"] == 4
    assert r["gaps"]["missing_dates"] == ["2026-06-04"]
    assert r["gaps"]["nav_continuous_across_missing"] is True
    assert r["gaps"]["zero_yield_dates"] == ["2026-06-06"]
    expected = ((100_020.0 / 100_000.0) ** (365.0 / 5) - 1.0) * 100.0
    assert r["annualised_equivalent_pct"] == pytest.approx(expected, abs=1e-6)
    assert r["annualised_approval_required"] is True


def test_costs_are_counted_and_already_inside_nav():
    r = period_return(_clean_series())
    assert r["costs_paid_usd"] == 40.0
    assert r["flows"]["count"] == 0                       # the cost explains the drop — not a flow


def test_negative_period_return():
    bars = [_bar("2026-06-02", 100_000.0, 100_000.0, 0.0),
            _bar("2026-06-03", 100_000.0, 99_900.0, 0.0, cost=100.0)]
    r = period_return(bars)
    assert r["period_return_pct"] == pytest.approx(-0.1, abs=1e-9)
    assert r["annualised_equivalent_pct"] < 0


def test_an_external_flow_switches_to_twr_and_reports_mwr_separately():
    bars = [_bar("2026-06-02", 100_000.0, 100_000.0, 0.0),
            _bar("2026-06-03", 100_000.0, 100_100.0, 100.0),
            _bar("2026-06-04", 110_100.0, 110_210.1, 110.1)]   # +10 000 deposited before the open
    r = period_return(bars)
    assert r["method"] == "TWR"
    assert r["flows"]["count"] == 1 and r["flows"]["items"][0]["kind"] == "open_jump"
    twr = (100_100.0 / 100_000.0) * (110_210.1 / 110_100.0) - 1.0
    assert r["twr_pct"] == pytest.approx(twr * 100.0, abs=1e-6)
    assert r["period_return_pct"] == r["twr_pct"]
    assert r["mwr_pct"] is not None and r["mwr_pct"] != pytest.approx(10.21, abs=0.01)  # not the raw NAV ratio
    raw_ratio = (110_210.1 / 100_000.0 - 1.0) * 100.0
    assert r["period_return_pct"] != pytest.approx(raw_ratio, abs=0.01)


def test_an_unexplained_intraday_jump_is_a_flow_not_absorbed():
    bars = [_bar("2026-06-02", 100_000.0, 100_000.0, 0.0),
            _bar("2026-06-03", 100_000.0, 100_500.0, 10.0)]     # +490 not explained by yield − cost
    r = period_return(bars)
    assert r["method"] == "TWR"
    assert r["flows"]["items"][0]["kind"] == "unexplained_intraday"


@pytest.mark.parametrize("bars", [None, [], [_bar("2026-06-02", 1.0, 1.0, 0.0)],
                                  [{"date": "2026-06-02", "evidenced": False, "equity": 1.0}]])
def test_unknown_is_none_never_zero(bars):
    r = period_return(bars)
    assert r["state"] == "UNMEASURED" and r["reason"]
    for k in ("period_return_pct", "twr_pct", "mwr_pct", "annualised_equivalent_pct",
              "nav_start", "nav_end", "costs_paid_usd"):
        assert r[k] is None, k


def test_provenance_is_counted_from_the_ledger_fields():
    bars = [_bar("2026-06-02", 1.0, 1.0, 0.0, recovered_from="self_heal"),
            _bar("2026-06-03", 1.0, 1.0, 0.0, accrual_source="live"),
            _bar("2026-06-04", 1.0, 1.0, 0.0, accrual_source="fallback", continuity_repaired=True),
            _bar("2026-06-05", 1.0, 1.0, 0.0)]
    r = period_return(bars)
    assert r["provenance"] == {"restored_from_cycle_log": 1, "live_rates": 1,
                               "fallback_rate": 1, "cycle_unlabelled": 1}
    assert r["continuity_repaired"] == ["2026-06-04"]


def _load_script(name):
    spec = importlib.util.spec_from_file_location(name, ROOT / "scripts" / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    sys.path.insert(0, str(ROOT / "scripts"))
    spec.loader.exec_module(mod)
    return mod


def test_shelf_period_block_unmeasured_carries_nulls_with_reasons():
    bsn = _load_script("build_site_numbers")
    blk = bsn._period_block({"track_period": {"state": "UNMEASURED", "reason": "no bars"}})
    assert blk["state"] == "UNMEASURED" and blk["reason"] == "no bars"
    for k in ("return", "twr", "mwr", "nav_start", "nav_end", "costs_paid_usd"):
        assert blk[k]["value"] is None and blk[k]["unavailable_reason"], k


def test_shelf_period_block_measured_reads_the_one_definition():
    bsn = _load_script("build_site_numbers")
    tp = period_return(_clean_series())
    blk = bsn._period_block({"track_period": tp})
    assert blk["state"] == "MEASURED" and blk["method"] == "NAV_RATIO"
    assert blk["return"]["value"] == pytest.approx(tp["period_return_pct"])
    assert blk["return"]["kind"] == bsn.MEASUREMENT
    assert blk["period"]["days_act"] == 5
    assert bsn._tp({"track_period": tp}, "annualised_equivalent_pct") == tp["annualised_equivalent_pct"]
    assert bsn._tp({"track_period": {"state": "UNMEASURED"}}, "annualised_equivalent_pct") is None
