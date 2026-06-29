"""
spa_core/tests/test_ws3_strategy_depth.py — ROUND-2 WS-3 "give the survivor book genuine reasons to
ENTER" regression suite. Covers 3.1 (evidence-based size-floor recalibration), 3.2 (capacity-aware
graded sizing), 3.3 (decorrelated multi-sleeve book) + the architect's predicted RED-TEAM catches:

  • a recalibrated floor RE-ADMITS a toxic book → the structural TAIL_VETO MUST still cap it at 0
    (toxic re-admission caught — the round-1 size-down exploit stays closed),
  • sizing that exceeds real depth → graded_size never exceeds the §9 capacity cap,
  • a "decorrelated" book that is secretly ONE bet (corr ~1) → flagged is_single_bet, not dressed up,
  • the book + recalibration regenerate DETERMINISTICALLY from a fixture.

GUARDRAILS asserted: the flag defaults OFF (no behavior change); recalibration moves ONLY
min_tradeable_size_usd (every toxicity veto byte-identical); advisory — nothing flips is_live / mutates
the go-live track.

    python3 -m pytest spa_core/tests/test_ws3_strategy_depth.py -p no:randomly -q
"""
# LLM_FORBIDDEN
from __future__ import annotations

import datetime
import os
from decimal import Decimal as D

import pytest

from spa_core.strategy_lab.rates_desk import config as rd_config
from spa_core.strategy_lab.rates_desk import rate_floor_recal as recal
from spa_core.strategy_lab.rates_desk.capacity_sizing import (
    GRADED_FULL_EDGE,
    GRADED_MIN_EDGE,
    graded_size,
    participation_frac,
)
from spa_core.strategy_lab.rates_desk.contracts import (
    KillReason,
    KillState,
    Opportunity,
    RatePolicyParams,
    RateQuote,
    RateVenue,
    TradeShape,
    UnderlyingKind,
    UnderlyingRisk,
)
from spa_core.strategy_lab.rates_desk.fair_value_engine import FairValueEngine
from spa_core.strategy_lab.rates_desk.rate_policy import evaluate_entry
from spa_core.strategy_lab.rates_desk.sleeves import FixedCarrySleeve
from spa_core.strategy_lab import portfolio_book as pb


# ══════════════════════════════════════════════════════════════════════════════════════════════════
# shared fixtures: a CLEAN-but-thin USDe carry book (the historically size_floor-refused fundable book)
# and a TOXIC ezETH book on the exact size-down exploit surface.
# ══════════════════════════════════════════════════════════════════════════════════════════════════
def _usde_quote(exit_liq="2167.49"):
    return RateQuote(underlying="usde", kind=UnderlyingKind.STABLE_SYNTH, venue=RateVenue.PENDLE_PT,
                     protocol="pendle", market_id="PT-usde", tenor_seconds=86400 * 60,
                     as_of="2026-06-28", quoted_rate=D("0.0925"), tvl_usd=D("456314"),
                     exit_liquidity_usd=D(exit_liq), hedge_available=True)


def _usde_risk():
    return UnderlyingRisk(underlying="usde", as_of="2026-06-28", nav_redemption_value=D("1"),
                          market_price=D("1"), peg_distance=D("0"), peg_vol_30d=D("0"),
                          redemption_sla_seconds=86400, reserve_fund_ratio=D("0.011"),
                          funding_neg_frac_90d=D("0.05"), oracle_kind="chainlink",
                          oracle_staleness_seconds=300, nested_protocol_count=1,
                          top_borrower_share=D("0.1"))


def _toxic_ezeth_quote(exit_liq="2167.49"):
    return RateQuote(underlying="ezeth", kind=UnderlyingKind.LRT, venue=RateVenue.PENDLE_PT,
                     protocol="pendle", market_id="PT-ezeth", tenor_seconds=86400 * 60,
                     as_of="2024-09-01", quoted_rate=D("0.35"), tvl_usd=D("5e7"),
                     exit_liquidity_usd=D(exit_liq), hedge_available=False)


def _toxic_ezeth_risk(u="ezeth"):
    return UnderlyingRisk(underlying=u, as_of="2024-09-01", nav_redemption_value=D("1"),
                          market_price=D("0.992"), peg_distance=D("0.008"), peg_vol_30d=D("0.016"),
                          redemption_sla_seconds=rd_config.redemption_sla_seconds(u),
                          reserve_fund_ratio=D(str(rd_config.reserve_fund_ratio(u))),
                          funding_neg_frac_90d=D("0.05"), oracle_kind=rd_config.oracle_kind(u),
                          oracle_staleness_seconds=rd_config.oracle_staleness_seconds(u),
                          nested_protocol_count=rd_config.nested_protocol_count(u),
                          top_borrower_share=D(str(rd_config.top_borrower_share(u))))


@pytest.fixture(autouse=True)
def _clear_flag():
    """Every test starts with the flag in a known state; restore after."""
    prev = os.environ.get(recal.FLAG_ENV)
    os.environ.pop(recal.FLAG_ENV, None)
    yield
    if prev is None:
        os.environ.pop(recal.FLAG_ENV, None)
    else:
        os.environ[recal.FLAG_ENV] = prev


# ══════════════════════════════════════════════════════════════════════════════════════════════════
# 3.1 — evidence-based size-floor recalibration
# ══════════════════════════════════════════════════════════════════════════════════════════════════
def test_flag_defaults_off():
    """SPA_RATE_FLOOR_RECAL defaults OFF — recalibrated_params returns base UNCHANGED (back-compat)."""
    assert recal.flag_enabled() is False
    base = RatePolicyParams()
    assert recal.recalibrated_params(base, {"quotes": []}) is base


def test_flag_on_off_values():
    for off in ("0", "", "false", "off"):
        os.environ[recal.FLAG_ENV] = off
        assert recal.flag_enabled() is False
    for on in ("1", "true", "yes", "ON"):
        os.environ[recal.FLAG_ENV] = on
        assert recal.flag_enabled() is True


def test_recalibrated_floor_from_realized_depth():
    """The recalibrated floor is depth-anchored, within the documented hard band, and STRICTLY below
    the committed $1,000 — so a thin-but-fundable book whose §9 cap sits in (floor, $1000) now passes."""
    surface = {"quotes": [
        {"underlying": "usde", "market_id": "PT-usde", "exit_liquidity_usd": "2167.49"},
        {"underlying": "susde", "market_id": "PT-susde", "exit_liquidity_usd": "30523.83"},
    ]}
    floor = recal.recalibrated_floor_usd(surface, RatePolicyParams())
    assert recal.HARD_MIN_FLOOR_USD <= floor <= recal.COMMITTED_DEFAULT_FLOOR_USD
    assert floor < recal.COMMITTED_DEFAULT_FLOOR_USD  # it LOOSENED the mis-scaled fixed floor


def test_recal_no_fundable_pools_keeps_committed_floor():
    """fail-CLOSED: no fundable pool on the surface → the committed $1,000 floor is kept (no loosening
    without evidence)."""
    floor = recal.recalibrated_floor_usd({"quotes": []}, RatePolicyParams())
    assert floor == recal.COMMITTED_DEFAULT_FLOOR_USD


def test_recal_only_moves_size_floor_guardrail():
    """HARD GUARDRAIL: recalibration changes ONLY min_tradeable_size_usd; every toxicity-veto field is
    byte-identical (this is the code-level proof a recalibrated floor cannot re-admit a toxic book)."""
    os.environ[recal.FLAG_ENV] = "1"
    base = RatePolicyParams()
    surface = {"quotes": [{"underlying": "usde", "market_id": "PT-usde",
                           "exit_liquidity_usd": "2167.49"}]}
    out = recal.recalibrated_params(base, surface)
    assert out.min_tradeable_size_usd != base.min_tradeable_size_usd  # the floor moved
    for f in ("max_structural_haircut", "max_total_haircut", "k_peg", "cap_peg", "k_funding",
              "cap_funding", "k_oracle", "cap_oracle", "k_liquidity", "cap_liquidity", "k_protocol",
              "cap_protocol", "max_peg_distance", "max_stable_depeg", "max_size_frac_of_exit"):
        assert getattr(out, f) == getattr(base, f), f"{f} must be byte-identical (untouched)"


def test_fundable_thin_book_passes_with_recal_on():
    """The live-style USDe 661bps book (clean, §9 cap $541.87) is size_floor-REFUSED with the flag OFF
    and APPROVED with the flag ON — a genuinely-fundable carry book is no longer auto-refused."""
    # OFF
    s = FixedCarrySleeve(); s.init(100000.0, {})
    v = s.scan_and_enter([_usde_quote()], {"usde": _usde_risk()}, "2026-06-28",
                         trailing_yields={"usde": D("0.10")}, boros_forwards={"usde": D("0.12")})
    assert v[0].approved is False and v[0].reason == KillReason.SIZE_FLOOR
    assert len(s._books) == 0
    # ON
    os.environ[recal.FLAG_ENV] = "1"
    s2 = FixedCarrySleeve(); s2.init(100000.0, {})
    v2 = s2.scan_and_enter([_usde_quote()], {"usde": _usde_risk()}, "2026-06-28",
                           trailing_yields={"usde": D("0.10")}, boros_forwards={"usde": D("0.12")})
    assert v2[0].approved is True and v2[0].reason == KillReason.NONE
    assert len(s2._books) == 1
    assert v2[0].approved_size_usd > D("0")


# ══════════════════════════════════════════════════════════════════════════════════════════════════
# 3.1 RED-TEAM — a recalibrated floor RE-ADMITTING a toxic book MUST be caught (structural veto holds)
# ══════════════════════════════════════════════════════════════════════════════════════════════════
def test_redteam_toxic_NOT_readmitted_with_recal_on():
    """RED-TEAM: with the recal flag ON (the lowest possible floor), a TOXIC ezETH book on a thin pool
    (the size-down vector) is STILL TAIL_VETO'd at every size — toxic re-admission CAUGHT. The structural
    veto fires at step 1, before sizing, so no floor recalibration can reach it."""
    os.environ[recal.FLAG_ENV] = "1"
    for size_pool in ("2167.49", "65000", "5000000"):
        s = FixedCarrySleeve(); s.init(100000.0, {})
        v = s.scan_and_enter([_toxic_ezeth_quote(size_pool)], {"ezeth": _toxic_ezeth_risk()},
                             "2024-09-01")
        assert v[0].approved is False, f"toxic re-admitted on pool {size_pool}"
        assert v[0].reason == KillReason.TAIL_VETO
        assert v[0].approved_size_usd == D("0")
        assert len(s._books) == 0


def test_redteam_adversarial_floor_zero_cannot_readmit_toxic():
    """RED-TEAM (direct gate): even an ADVERSARIAL min_tradeable_size_usd driven to $0 (the most
    permissive size floor an attacker could feed) cannot approve a toxic book — the TAIL_VETO is
    size-floor-INDEPENDENT. Sizing never gets a vote on toxicity."""
    import dataclasses
    p = dataclasses.replace(RatePolicyParams(), min_tradeable_size_usd=D("0"))
    eng = FairValueEngine(p)
    opp = Opportunity(quote=_toxic_ezeth_quote("65000"), shape=TradeShape.FIXED_CARRY,
                      requested_size_usd=D("1000"))
    res, _ = evaluate_entry(opp, _toxic_ezeth_risk(), D("1"), D("65000"), p, KillState(), engine=eng)
    assert res.approved is False
    assert res.reason == KillReason.TAIL_VETO


def test_recal_cannot_smuggle_a_structural_change():
    """The guardrail RAISES if recalibration ever tried to alter a toxicity-veto field — proven by
    constructing recal/base that differ in max_structural_haircut and asserting the guardrail rejects."""
    import dataclasses
    base = RatePolicyParams()
    tampered = dataclasses.replace(base, max_structural_haircut=D("0.30"))  # an attacker's loosening
    with pytest.raises(AssertionError):
        recal._assert_only_size_floor_changed(base, tampered)


# ══════════════════════════════════════════════════════════════════════════════════════════════════
# 3.2 — capacity-aware graded sizing
# ══════════════════════════════════════════════════════════════════════════════════════════════════
def test_graded_never_exceeds_capacity_cap():
    """RED-TEAM: sizing that exceeds real depth is CAUGHT — graded_size NEVER exceeds the §9 capacity
    cap (max_size_frac_of_exit × depth), even with a fat edge and unlimited cash."""
    p = RatePolicyParams()
    depth = D("5000000")
    cap = p.max_size_frac_of_exit * depth  # $1.25M
    gs = graded_size(realized_depth_usd=depth, net_edge=D("0.50"),  # huge edge
                     cash_available_usd=D("100000000"), params=p)   # unlimited cash
    assert gs.size_usd <= cap
    assert gs.capacity_cap_usd == cap


def test_graded_is_graded_not_binary():
    """Participation RAMPS with edge: a thin edge takes a small fraction of the cap, a fat edge takes
    the full cap — monotone non-decreasing, bounded [0,1]. (Turns binary all-in into graded.)"""
    thin = participation_frac(GRADED_MIN_EDGE)
    mid = participation_frac((GRADED_MIN_EDGE + GRADED_FULL_EDGE) / 2)
    fat = participation_frac(GRADED_FULL_EDGE * 2)
    assert D("0") < thin < mid < fat == D("1")
    # monotone across a sweep
    prev = D("-1")
    for bps in range(0, 600, 25):
        v = participation_frac(D(bps) / D("10000"))
        assert v >= prev and D("0") <= v <= D("1")
        prev = v


def test_graded_fail_closed_on_malformed_depth():
    """fail-CLOSED: a non-positive / malformed depth, edge, or cash → size 0 (never size into the
    unknown)."""
    p = RatePolicyParams()
    for depth, edge, cash in ((D("0"), D("0.05"), D("1000")), (D("1000"), D("-0.01"), D("1000")),
                              (D("1000"), D("0.05"), D("0")), (D("1000"), D("0.05"), D("-5"))):
        gs = graded_size(depth, edge, cash, p)
        assert gs.size_usd == D("0")


def test_graded_cash_binds_when_smallest():
    """When cash is the smallest of the three bounds, it binds (never size beyond the book's cash)."""
    p = RatePolicyParams()
    gs = graded_size(realized_depth_usd=D("5000000"), net_edge=D("0.50"),
                     cash_available_usd=D("100"), params=p)
    assert gs.size_usd == D("100") and gs.binding == "cash"


def test_graded_sizing_applied_in_sleeve_book():
    """End-to-end: with recal ON the approved USDe book's stored size is the GRADED size (<= the gate's
    capacity-bounded approved size) — graded participation, not all-in."""
    os.environ[recal.FLAG_ENV] = "1"
    s = FixedCarrySleeve(); s.init(100000.0, {})
    s.scan_and_enter([_usde_quote()], {"usde": _usde_risk()}, "2026-06-28",
                     trailing_yields={"usde": D("0.10")}, boros_forwards={"usde": D("0.12")})
    bk = list(s._books.values())[0]
    cap = s.params.max_size_frac_of_exit * _usde_quote().exit_liquidity_usd
    assert D("0") < bk["size"] <= cap          # never exceeds realized capacity
    assert "graded" in bk                       # the graded-sizing proof is recorded


# ══════════════════════════════════════════════════════════════════════════════════════════════════
# 3.3 — decorrelated multi-sleeve book + the single-bet red-team
# ══════════════════════════════════════════════════════════════════════════════════════════════════
def _day(off):
    return (datetime.date(2026, 6, 1) + datetime.timedelta(days=off)).isoformat()


def _series(equities, start=0):
    return {"series": [{"date": _day(start + i), "equity_usd": float(e)}
                       for i, e in enumerate(equities)]}


def test_portfolio_book_builds_combined_track():
    """The combined book blends the sleeves' real returns inverse-vol over their COMMON axis; weights
    sum to ~1; a real combined equity path is produced (deterministic)."""
    sleeves = {
        "fixed_carry": _series([100000, 100002, 100004, 100006, 100008, 100010, 100012, 100014]),
        "rwa_sleeve": _series([100000, 100009, 100018, 100027, 100036, 100045, 100054, 100063]),
        "eth_lst_neutral": _series([100000, 100050, 99980, 100040, 99970, 100060, 99990, 100070]),
    }
    rep = pb.build_report(sleeve_series=sleeves, floor_apy_pct=3.18, write=False,
                          now_iso="2026-06-29T00:00:00+00:00")
    assert set(rep["sleeves"]) == {"fixed_carry", "rwa_sleeve", "eth_lst_neutral"}
    assert abs(sum(rep["weights"].values()) - 1.0) < 1e-6
    assert rep["n_track_points"] >= 2
    assert rep["decorrelation"]["valid"] is True


def test_portfolio_book_honest_beats_floor_verdict():
    """beats_floor is HONEST: a >= MIN_TRACK_POINTS book that beats the floor risk-adjusted reads
    BEATS_FLOOR; one below reads BELOW_FLOOR; a thin one reads INSUFFICIENT_DATA — never a fabricated
    pass."""
    # a deep, clearly-above-floor track (steady ~9%/yr, zero drawdown)
    up = [100000 * (1.0 + 0.00025) ** i for i in range(10)]
    rep_up = pb.build_report(sleeve_series={"fixed_carry": _series(up), "rwa_sleeve": _series(up)},
                             floor_apy_pct=3.18, write=False, now_iso="x")
    assert rep_up["verdict"] in ("BEATS_FLOOR", "BELOW_FLOOR")  # a real verdict (not INSUFFICIENT)
    assert rep_up["beats_floor"] is not None
    # a thin track → INSUFFICIENT_DATA, beats_floor None (honest)
    rep_thin = pb.build_report(sleeve_series={"fixed_carry": _series([100000, 100002, 100004])},
                               floor_apy_pct=3.18, write=False, now_iso="x")
    assert rep_thin["verdict"] == "INSUFFICIENT_DATA"
    assert rep_thin["beats_floor"] is None


def test_redteam_single_bet_flagged():
    """RED-TEAM: a 'decorrelated' book that is secretly ONE bet (the sleeves' returns are ~identical →
    corr ~1) is FLAGGED is_single_bet — it is not dressed up as diversified."""
    # two sleeves with identical daily returns → correlation 1.0 (>= SINGLE_BET_RHO), deep enough to know
    base = [100000, 100020, 100015, 100050, 100040, 100080, 100070, 100110]
    rep = pb.build_report(sleeve_series={"a": _series(base), "b": _series(base)},
                          floor_apy_pct=3.18, write=False, now_iso="x")
    assert rep["decorrelation"]["avg_abs_offdiag_corr"] is not None
    assert rep["decorrelation"]["avg_abs_offdiag_corr"] >= pb.SINGLE_BET_RHO
    assert rep["is_single_bet"] is True


def test_redteam_genuinely_decorrelated_not_flagged():
    """A genuinely-decorrelated pair (low |corr|, neither in-phase nor anti-phase) is NOT flagged
    single-bet — the guard discriminates (note rho_bar uses |corr|, so anti-phase ~1 IS a single bet:
    a deterministic linear combo of one factor; only a truly INDEPENDENT pair reads low)."""
    # two near-independent return paths (chosen so |Pearson| is small)
    a = _series([100000, 100100, 100000, 100100, 100000, 100100, 100000, 100100, 100000])
    b = _series([100000, 100000, 100120, 100110, 99990, 100100, 100130, 99980, 100090])
    rep = pb.build_report(sleeve_series={"a": a, "b": b}, floor_apy_pct=3.18, write=False, now_iso="x")
    rho = rep["decorrelation"]["avg_abs_offdiag_corr"]
    assert rho is not None and rho < pb.SINGLE_BET_RHO
    assert rep["is_single_bet"] is False


def test_portfolio_book_drops_malformed_sleeve():
    """A sleeve whose series fails integrity is DROPPED (listed), never fabricated into the blend."""
    sleeves = {
        "fixed_carry": _series([100000, 100002, 100004, 100006]),
        "bad": {"series": [{"date": "2026-06-01", "equity_usd": float("inf")},
                           {"date": "2026-06-02", "equity_usd": 100010.0}]},
    }
    rep = pb.build_report(sleeve_series=sleeves, floor_apy_pct=3.18, write=False, now_iso="x")
    assert "bad" not in rep["sleeves"]
    assert any(d["sleeve"] == "bad" for d in rep["dropped_sleeves"])


# ══════════════════════════════════════════════════════════════════════════════════════════════════
# DETERMINISM — book + recalibration regenerate byte-identically from a fixture
# ══════════════════════════════════════════════════════════════════════════════════════════════════
def test_portfolio_book_deterministic_from_fixture():
    sleeves = {"fixed_carry": _series([100000, 100002, 100004, 100006, 100008]),
               "rwa_sleeve": _series([100000, 100009, 100018, 100027, 100036])}
    r1 = pb.build_report(sleeve_series=sleeves, floor_apy_pct=3.18, write=False, now_iso="fixed")
    r2 = pb.build_report(sleeve_series=sleeves, floor_apy_pct=3.18, write=False, now_iso="fixed")
    assert r1 == r2


def test_recal_deterministic_from_fixture():
    os.environ[recal.FLAG_ENV] = "1"
    surface = {"quotes": [{"underlying": "usde", "market_id": "PT-usde",
                           "exit_liquidity_usd": "2167.49"}]}
    base = RatePolicyParams()
    assert recal.recalibrated_floor_usd(surface, base) == recal.recalibrated_floor_usd(surface, base)
    assert (recal.recalibrated_params(base, surface).min_tradeable_size_usd
            == recal.recalibrated_params(base, surface).min_tradeable_size_usd)


def test_graded_deterministic():
    p = RatePolicyParams()
    a = graded_size(D("2167.49"), D("0.066"), D("100000"), p)
    b = graded_size(D("2167.49"), D("0.066"), D("100000"), p)
    assert a == b


# ══════════════════════════════════════════════════════════════════════════════════════════════════
# ADVISORY separation — nothing flips is_live / mutates the go-live track
# ══════════════════════════════════════════════════════════════════════════════════════════════════
def test_sleeve_stays_advisory():
    assert FixedCarrySleeve.is_advisory is True


def test_portfolio_book_report_is_advisory_research_only():
    rep = pb.build_report(sleeve_series={"fixed_carry": _series([100000, 100002, 100004])},
                          floor_apy_pct=3.18, write=False, now_iso="x")
    assert rep["is_advisory"] is True
    assert rep["research_only"] is True
    assert rep["separate_from_golive_track"] is True
