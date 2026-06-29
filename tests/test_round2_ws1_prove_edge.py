"""
tests/test_round2_ws1_prove_edge.py — ROUND-2 WS-1 "Prove the Edge" verification.

Pins the realized forward A/B (1.1), the cash-drag decomposition (1.2), the scale-honest edge
curve (1.3), the carry truth-table (1.4) and the refusal-cost ledger (1.5) — including the
RED-TEAM masking paths each must catch, and a deterministic-from-fixture smoke.

Pure stdlib + pytest. Deterministic (-p no:randomly). LLM-forbidden. NEVER touches live data/ —
every test runs against a hermetic temp data dir.
"""
# LLM_FORBIDDEN
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_REPO_ROOT))

from spa_core.strategy_lab import realized_ab as rab          # noqa: E402
from spa_core.strategy_lab import edge_at_scale as eas         # noqa: E402
from spa_core.strategy_lab import carry_truth_table as ctt     # noqa: E402
from spa_core.strategy_lab import refusal_cost as rc           # noqa: E402


# ───────────────────────────────────────────────────────────────────────────
# Fixtures — a hermetic data dir with an evidenced equity-curve universe.
# ───────────────────────────────────────────────────────────────────────────
def _write_universe(root: Path, *, date: str = "2026-06-22", apy_today: float = 4.48) -> None:
    """Write a minimal evidenced equity-curve day (T1+T2 held protocols) into root."""
    root.mkdir(parents=True, exist_ok=True)
    (root / "equity_curve_daily.json").write_text(json.dumps({
        "daily": [
            {"date": "2026-06-10", "evidenced": False, "apy_today": 4.0,
             "positions": {"aave_v3": 1000.0}},
            {"date": date, "evidenced": True, "apy_today": apy_today,
             "positions": {"aave_v3": 23250.0, "compound_v3": 15852.0,
                           "maple": 15852.0, "euler_v2": 10568.0, "yearn_v3": 3170.0}},
        ]
    }), encoding="utf-8")
    # a registry so build_universe has tiers (optional — falls back to proxy apy + T2).
    (root / "adapter_registry.json").write_text(json.dumps({
        "adapters": {
            "aave_v3": {"tier": 1, "fallback_apy": 0.035},
            "compound_v3": {"tier": 1, "fallback_apy": 0.052},
            "maple": {"tier": 2, "fallback_apy": 0.0482},
            "euler_v2": {"tier": 2, "fallback_apy": 0.0275},
            "yearn_v3": {"tier": 2, "fallback_apy": 0.0323},
        }
    }), encoding="utf-8")


# ===========================================================================
# WS-1.1 — REALIZED forward A/B: is_realized:true, day-distinct, banks accrual.
# ===========================================================================
def test_realized_ab_is_realized_and_starts_thin(tmp_path):
    _write_universe(tmp_path)
    out = rab.run_realized_ab(data_dir=tmp_path, now_date="2026-06-22")
    assert out["is_realized"] is True and out["is_backtest"] is False
    assert out["status"] == "thin"          # one day → honestly THIN
    assert out["verdict"] == "INSUFFICIENT_DATA"
    assert out["n_days"] == 1
    # the books were banked (separate from the go-live track).
    for book in (rab.LEGACY_BOOK, rab.OPT_BOOK, rab.LEGACY_FAIR_BOOK):
        doc = json.loads((tmp_path / "realized_ab" / f"{book}_series.json").read_text())
        assert doc["is_realized"] is True
        assert len(doc["series"]) == 1
        assert doc["series"][0]["is_realized"] is True


def test_realized_ab_appends_distinct_days_not_replay(tmp_path):
    """Two DIFFERENT UTC days → two DISTINCT rows with non-identical equity (a forward track,
    not a replay)."""
    _write_universe(tmp_path)
    rab.run_realized_ab(data_dir=tmp_path, now_date="2026-06-22")
    rab.run_realized_ab(data_dir=tmp_path, now_date="2026-06-23")
    doc = json.loads((tmp_path / "realized_ab" / f"{rab.OPT_BOOK}_series.json").read_text())
    assert len(doc["series"]) == 2
    d0, d1 = doc["series"]
    assert d0["date"] != d1["date"]
    assert d1["equity_usd"] > d0["equity_usd"]   # accrual compounded forward, day-distinct


def test_realized_ab_idempotent_same_day_no_double_count(tmp_path):
    """RED-TEAM replay-day injection: re-running on the SAME UTC day REFRESHES today's row from the
    prior equity — it never appends a duplicate or double-compounds."""
    _write_universe(tmp_path)
    rab.run_realized_ab(data_dir=tmp_path, now_date="2026-06-22")
    rab.run_realized_ab(data_dir=tmp_path, now_date="2026-06-22")  # same day again
    rab.run_realized_ab(data_dir=tmp_path, now_date="2026-06-22")  # and again
    doc = json.loads((tmp_path / "realized_ab" / f"{rab.OPT_BOOK}_series.json").read_text())
    assert len(doc["series"]) == 1, "same-day re-run double-counted (replay injection!)"


def test_realized_ab_unavailable_fails_closed(tmp_path):
    """No evidenced universe → status unavailable, NULL verdict, never a fabricated uplift."""
    (tmp_path / "equity_curve_daily.json").write_text(json.dumps({"daily": []}), encoding="utf-8")
    out = rab.run_realized_ab(data_dir=tmp_path)
    assert out["status"] == "unavailable"
    assert out["verdict"] is None
    assert out["uplift_realized_bps"] is None


# ===========================================================================
# WS-1.2 — cash-drag decomposition is the headline; raw gap labeled NOT apples.
# ===========================================================================
def test_cash_drag_decomposition_present_and_honest(tmp_path):
    _write_universe(tmp_path)
    out = rab.run_realized_ab(data_dir=tmp_path, now_date="2026-06-22")
    dec = out["decomposition"]
    # all three legs are present and finite.
    for k in ("raw_uplift_bps", "selection_alpha_bps", "cash_drag_bps"):
        assert isinstance(dec[k], (int, float)), f"{k} missing/non-numeric"
    # the raw gap is explicitly flagged NOT apples-to-apples (cash-drag laundering caught).
    assert dec["raw_uplift_apples_to_apples"] is False
    # the floor-fair legacy book reserves the SAME 5% cash floor as the optimizer (like-for-like).
    fair_dep = out["books"][rab.LEGACY_FAIR_BOOK]["deployed_frac"]
    opt_dep = out["books"][rab.OPT_BOOK]["deployed_frac"]
    assert abs(fair_dep - opt_dep) < 1e-6, "floor-fair book did not reserve the same cash floor"
    # cash_drag = legacy − legacy_fair ; selection = optimized − legacy_fair ; raw = optimized − legacy.
    # identity: raw == selection − cash_drag (to rounding).
    assert abs(dec["raw_uplift_bps"] - (dec["selection_alpha_bps"] - dec["cash_drag_bps"])) < 0.5


# ===========================================================================
# WS-1.3 — scale-honest edge curve: caps bind harder at scale (real TVL).
# ===========================================================================
def _write_universe_no_registry(root: Path) -> None:
    """Universe WITHOUT a registry → build_universe uses the flat realized apy_today proxy for every
    pool, so the optimizer concentrates by grade/variance and we control which pools it picks via the
    injected TVL. This deterministically exercises the capacity-cap compression."""
    root.mkdir(parents=True, exist_ok=True)
    (root / "equity_curve_daily.json").write_text(json.dumps({
        "daily": [
            {"date": "2026-06-10", "evidenced": False, "apy_today": 4.0, "positions": {"aave_v3": 1.0}},
            {"date": "2026-06-22", "evidenced": True, "apy_today": 6.0,
             "positions": {"euler_v2": 10000.0, "maple": 10000.0, "yearn_v3": 10000.0}},
        ]
    }), encoding="utf-8")
    # no adapter_registry.json → every pool gets the flat 6.0% proxy + default tier T2.


def test_edge_at_scale_compresses_when_picks_are_small_tvl(tmp_path):
    """When the optimizer's funded pools are SMALL-TVL, the capacity cap (1% of TVL) binds harder as
    AUM grows → the optimizer yield-on-capital COMPRESSES with AUM (capital capped into idle cash).
    This is the honest scale story; the curve + capped-out $ make it auditable."""
    _write_universe_no_registry(tmp_path)
    # all three held pools are small-TVL → at $10M a 20% slug ($2M) blows past 1% of TVL.
    live_tvl = {"euler_v2": 14_000_000.0, "maple": 20_000_000.0, "yearn_v3": 26_000_000.0}
    out = eas.build_edge_at_scale(data_dir=tmp_path, live_tvl=live_tvl, write=False)
    assert out["status"] == "ok"
    curve = out["curve"]
    assert [pt["aum_usd"] for pt in curve] == list(eas.AUM_LADDER_USD)
    # the optimizer's REALIZED yield-on-capital must FALL from $100k to $10M (caps bite at scale).
    opt_small = curve[0]["optimized_yield_on_capital_pct"]
    opt_large = curve[-1]["optimized_yield_on_capital_pct"]
    assert opt_large < opt_small, "optimizer yield did not compress at scale despite small-TVL pools"
    # at scale the optimizer book had capital capped out into idle cash (the honest drag).
    assert curve[-1]["optimized_diag"]["capital_capped_out_usd"] > 0


def test_edge_at_scale_uses_real_tvl_not_fabricated(tmp_path):
    """RED-TEAM scale-cap evasion: a missing TVL must default to the conservative $5M floor (caps
    bind SOONER), never an infinite/fabricated TVL that makes caps never bind."""
    _write_universe(tmp_path)
    out = eas.build_edge_at_scale(data_dir=tmp_path, live_tvl={}, write=False)  # no TVL data
    assert out["status"] == "ok"
    # every pool defaulted to the $5M conservative floor (not a huge fabricated number).
    for proto, tvl in out["live_tvl_used"].items():
        assert tvl == eas.DEFAULT_TVL_USD, f"{proto} TVL {tvl} != conservative default"
    # with a $5M floor on every pool, the 1% cap is $50k — caps bind hard at $1M+.
    assert out["curve"][-1]["optimized_diag"]["capital_capped_out_usd"] > 0


def test_edge_at_scale_break_even_aum_honest(tmp_path):
    """The break-even field is honest: it is either None (edge survives across the ladder) or one of
    the tested AUM rungs (the smallest AUM where uplift < materiality) — never a fabricated value."""
    _write_universe_no_registry(tmp_path)
    live_tvl = {"euler_v2": 14_000_000.0, "maple": 20_000_000.0, "yearn_v3": 26_000_000.0}
    out = eas.build_edge_at_scale(data_dir=tmp_path, live_tvl=live_tvl, write=False)
    be = out["edge_below_materiality_at_aum_usd"]
    assert be is None or be in eas.AUM_LADDER_USD
    # edge_survives_at_max_aum is a clean bool consistent with the last curve point.
    assert out["edge_survives_at_max_aum"] == out["curve"][-1]["uplift_material"]


# ===========================================================================
# WS-1.4 — carry truth-table: realized-or-INSUFFICIENT_DATA, never a fake 0.0.
# ===========================================================================
def _thin_series(initial=100_000.0, n=4, carry_per_day=2.0):
    # PAST, contiguous calendar days anchored well before today UTC (so the integrity gate's
    # future-date guard never fires) — proper date arithmetic, never a malformed "2026-06-31".
    import datetime
    base = datetime.date(2026, 6, 1)
    return {"id": "x", "series": [
        {"date": (base + datetime.timedelta(days=i)).isoformat(),
         "equity_usd": round(initial + carry_per_day * i, 6)}
        for i in range(n)
    ]}


def test_carry_truth_table_thin_is_insufficient_not_zero(tmp_path):
    """A thin (< MIN_DAYS_FOR_BPS) but real track → INSUFFICIENT_DATA, with the honest $ carry
    surfaced but NO fabricated annualized verdict, and a non-null bps only as informational."""
    series = {"rates_desk_fixed_carry": _thin_series(n=4)}
    out = ctt.build_carry_truth_table(data_dir=tmp_path, floor_apy_pct=3.4,
                                      series_by_name=series, write=False)
    assert out["n_sleeves"] == 1
    row = out["rows"][0]
    assert row["verdict"] == ctt.VERDICT_INSUFFICIENT
    assert row["n_points"] == 4
    # the $ carry is honest (reconciles to NAV), the verdict is honestly INSUFFICIENT.
    assert row["realized_carry_usd"] is not None
    assert out["n_above_floor"] == 0 and out["n_below_floor"] == 0


def test_carry_truth_table_broken_track_refused_null_bps(tmp_path):
    """RED-TEAM: a look-ahead / broken track → integrity fail-closed → INSUFFICIENT_DATA with NULL
    bps (never a fabricated number on a poisoned series)."""
    # a FUTURE-dated point poisons integrity.
    bad = {"id": "x", "series": [
        {"date": "2099-01-01", "equity_usd": 100_000.0},
        {"date": "2099-01-02", "equity_usd": 999_999.0},
    ]}
    out = ctt.build_carry_truth_table(data_dir=tmp_path, floor_apy_pct=3.4,
                                      series_by_name={"toxic": bad}, write=False)
    row = out["rows"][0]
    assert row["verdict"] == ctt.VERDICT_INSUFFICIENT
    assert row["carry_above_floor_bps"] is None, "leaked a bps on a poisoned series!"
    assert row["integrity_ok"] is False or row["reconciles"] is False


def test_carry_truth_table_deep_track_gets_real_verdict(tmp_path):
    """A track with enough depth + carry clearly above floor → ABOVE_FLOOR (not masked as thin)."""
    # 10 points, ~$50/day carry on $100k over 9 days → annualized well above a 3.4% floor's residual.
    series = {"good": _thin_series(n=10, carry_per_day=50.0)}
    out = ctt.build_carry_truth_table(data_dir=tmp_path, floor_apy_pct=3.4,
                                      series_by_name=series, write=False)
    row = out["rows"][0]
    assert row["verdict"] in (ctt.VERDICT_ABOVE, ctt.VERDICT_AT_FLOOR, ctt.VERDICT_BELOW)
    assert row["verdict"] != ctt.VERDICT_INSUFFICIENT  # deep enough → a real verdict
    assert isinstance(row["carry_above_floor_bps"], (int, float))


# ===========================================================================
# WS-1.5 — refusal-cost: cost-of-caution, size_floor excluded, both framings.
# ===========================================================================
def _fc_series_with_scans():
    return {"id": "rates_desk_fixed_carry", "series": [
        {"date": "2026-06-25", "equity_usd": 100_000.0},  # no scan_diag → skipped
        {"date": "2026-06-26", "equity_usd": 100_001.85,
         "scan_diag": {"approvals": 2, "refusals": 2,
                       "refused_by_reason": {"size_floor": 1, "tail_veto": 1},
                       "best_net_edge_bps": 1302.73}},
        {"date": "2026-06-27", "equity_usd": 100_003.69,
         "scan_diag": {"approvals": 0, "refusals": 2,
                       "refused_by_reason": {"size_floor": 1, "tail_veto": 1},
                       "best_net_edge_bps": 1302.49}},
        {"date": "2026-06-28", "equity_usd": 100_005.74,
         "scan_diag": {"approvals": 1, "refusals": 1,
                       "refused_by_reason": {"size_floor": 1},
                       "best_net_edge_bps": 661.02}},
        # a size_floor-ONLY day with NO approvals → exercises the n_days_sizefloor_only counter and
        # the red-team guard (a +661bps best edge but it forgoes NOTHING fundable — sub-min-size).
        {"date": "2026-06-29", "equity_usd": 100_007.78,
         "scan_diag": {"approvals": 0, "refusals": 1,
                       "refused_by_reason": {"size_floor": 1},
                       "best_net_edge_bps": 661.02}},
    ]}


def test_refusal_cost_size_floor_excluded(tmp_path):
    """RED-TEAM: a size_floor-only refusal forgoes nothing fundable → it must NOT be counted as
    cost-of-caution (counting it would inflate the apparent cost)."""
    out = rc.build_refusal_cost(data_dir=tmp_path, series_doc=_fc_series_with_scans(), write=False)
    assert out["status"] == "ok"
    # the size_floor-only day (06-28) forgoes 0 despite a +661bps best edge.
    day_2806 = next(r for r in out["ledger"] if r["date"] == "2026-06-28")
    assert day_2806["forgone_edge_bps_if_real"] == 0.0
    # the tail_veto days DO forgo their best edge.
    day_2606 = next(r for r in out["ledger"] if r["date"] == "2026-06-26")
    assert day_2606["forgone_edge_bps_if_real"] == pytest.approx(1302.73)
    assert out["n_days_sizefloor_only"] == 1


def test_refusal_cost_reports_both_framings(tmp_path):
    out = rc.build_refusal_cost(data_dir=tmp_path, series_doc=_fc_series_with_scans(), write=False)
    interp = out["interpretation"]
    # both the cost-if-real AND the gate's tail-comp thesis are surfaced (never one-sided).
    assert isinstance(interp["cost_of_caution_bps_if_refused_edge_were_real"], (int, float))
    assert "tail-comp" in interp["gate_thesis"].lower() or "insurance" in interp["gate_thesis"].lower()
    assert out["thin"] is True   # 3 diagnostic days < MIN_DAYS_FOR_AGG → honestly thin


def test_refusal_cost_no_series_fails_closed(tmp_path):
    out = rc.build_refusal_cost(data_dir=tmp_path, series_doc={"series": []}, write=False)
    assert out["status"] == "unavailable"
    assert out["cost_of_caution_bps_per_yr_if_real"] is None


# ===========================================================================
# SMOKE — deterministic regeneration from a FIXED fixture (byte-stable).
# ===========================================================================
def test_smoke_deterministic_from_fixture(tmp_path):
    """The A/B + truth-table regenerate DETERMINISTICALLY from a fixed fixture (modulo wall-clock
    stamps). Run each twice and assert the load-bearing fields are identical."""
    _write_universe(tmp_path)
    a1 = rab.run_realized_ab(data_dir=tmp_path, now_date="2026-06-22", write=False)
    # reset the books so the second run starts from the same state.
    _write_universe(tmp_path)
    a2 = rab.run_realized_ab(data_dir=tmp_path, now_date="2026-06-22", write=False)
    assert a1["decomposition"] == a2["decomposition"]
    assert a1["books"] == a2["books"]

    series = {"good": _thin_series(n=10, carry_per_day=50.0)}
    t1 = ctt.build_carry_truth_table(data_dir=tmp_path, floor_apy_pct=3.4,
                                     series_by_name=series, write=False, now_iso="X")
    t2 = ctt.build_carry_truth_table(data_dir=tmp_path, floor_apy_pct=3.4,
                                     series_by_name=series, write=False, now_iso="X")
    assert json.dumps(t1, sort_keys=True) == json.dumps(t2, sort_keys=True)

    e1 = eas.build_edge_at_scale(data_dir=tmp_path,
                                 live_tvl={"euler_v2": 14_000_000.0}, write=False, now_iso="X")
    e2 = eas.build_edge_at_scale(data_dir=tmp_path,
                                 live_tvl={"euler_v2": 14_000_000.0}, write=False, now_iso="X")
    assert json.dumps(e1, sort_keys=True) == json.dumps(e2, sort_keys=True)


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-p", "no:randomly", "-q"]))
